"""Deterministic filters over SQL-owned saved population definitions.

RunManager owns scheduling, cancellation, review and completion. This module
does not invoke a graph or a source backend. Unsupported analytical work stays
with the coordinator; a prepared filter never silently changes execution paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from data_analytics_agent.agents.text_to_sql.dashboard_queries import (
    compile_query,
    execute_dashboard_query,
    query_execution,
)
from data_analytics_agent.dashboard.schemas import (
    ChartComponent,
    MetricComponent,
    TableComponent,
    TextComponent,
)
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import (
    ActivityTool,
    ApprovalAction,
    ApprovalRequest,
    CoordinatorResponse,
)
from data_analytics_agent.visualization.schemas import ChartRequest
from data_analytics_agent.visualization.tools import create_chart_tool

FILTER_DESCRIPTION = (
    "Applied dashboard filters. See the saved evidence and report for this population."
)


def _service(owner):
    return DashboardService(
        owner.results, owner.analyses, owner.runs, owner.reports, owner.dashboards
    )


def _effective_filters(definition, applied):
    return {f.id: applied.get(f.id, []) for f in definition.filters}


def _chart_template(owner, revision, component, evidence):
    if component.chart_id:
        return evidence.chart(component.chart_id)
    for earlier in reversed(
        owner.dashboards.history(
            revision.dashboard_id, revision.thread_id, source_id=revision.source_id
        )
    ):
        if earlier.version > revision.version:
            continue
        for prior in earlier.spec.components:
            if (
                prior.id == component.id
                and isinstance(prior, ChartComponent)
                and prior.chart_id
            ):
                return evidence.chart(prior.chart_id)
    return None


def _filtered_chart_title(template, definition):
    labels = ", ".join(
        measure.name.replace("_", " ") for measure in definition.measures
    )
    if template and template.x:
        labels += " by " + template.x.replace("_", " ")
    return (labels[:1].upper() + labels[1:])[:160]


def prepare_action(services, revision, action) -> dict | None:
    """Return an application plan only when every affected query is established.

    API admission persists this plan under ``dashboard_execution_plans`` using
    the new run ID. A missing capability returns None. A corrupt saved receipt
    raises, so it cannot gain a less restrictive route through the coordinator.
    """
    if action.action != "filter":
        return None
    if revision.revision_id != action.expected_revision:
        raise ValueError("The dashboard changed. Reload before applying the action.")
    original_run = services.runs.get(revision.run_id)
    original = original_run.answer or original_run.findings
    if original and (original.partial or original.analyses):
        return None
    service = _service(services)
    service.validate_filter_values(revision.spec, action.filter_values)
    evidence = service._evidence(revision.thread_id, revision.source_id)
    affected = {
        binding.component_id
        for filtering in revision.spec.filters
        if filtering.id in action.filter_values
        for binding in filtering.bindings
    }
    if not affected:
        return None
    applied = {**revision.applied_filters, **action.filter_values}
    component_results = {}
    for component in revision.spec.components:
        result = service._component_result(component, evidence, analytical=True)
        if result is None:
            continue
        # A filter of a saved model output must not masquerade as a rerun of
        # its statistical procedure, including an indirect Python ancestor.
        if any(parent.kind == "python" for parent in evidence.results.values()):
            return None
        if component.id not in affected:
            continue
        receipt = query_execution(result, services.results)
        if receipt is None:
            return None
        declarations = {
            filtering.id: (binding.column, filtering.kind)
            for filtering in revision.spec.filters
            for binding in filtering.bindings
            if binding.component_id == component.id
        }
        if declarations != {
            f.id: (f.column, f.kind) for f in receipt.definition.filters
        }:
            return None
        if any(
            len([b for b in f.bindings if b.component_id == component.id]) > 1
            for f in revision.spec.filters
        ):
            return None
        previous_filters = _effective_filters(
            receipt.definition, revision.applied_filters
        )
        if {k: v for k, v in receipt.filter_values.items() if v} != {
            k: v for k, v in previous_filters.items() if v
        }:
            raise ValueError(
                "The saved query scope does not match the applied dashboard filters."
            )
        if isinstance(component, MetricComponent):
            if (
                receipt.definition.dimensions
                or component.metric.row_index != 0
                or component.metric.comparison
            ):
                return None
            if component.metric.column not in {
                m.name for m in receipt.definition.measures
            }:
                return None
        if isinstance(component, ChartComponent):
            template = _chart_template(services, revision, component, evidence)
            if (
                template is None
                or template.interval
                or template.forecast_start
                or template.error_y
            ):
                return None
        compile_query(
            receipt.definition,
            _effective_filters(receipt.definition, applied),
            services.results,
            revision.thread_id,
            revision.source_id,
        )
        component_results[component.id] = result.result_id
    if set(component_results) != affected:
        return None
    return {
        "kind": "saved_filter",
        "thread_id": revision.thread_id,
        "source_id": revision.source_id,
        "dashboard_id": revision.dashboard_id,
        "revision_id": revision.revision_id,
        "component_results": component_results,
    }


def _queries(owner, revision, action, plan):
    applied = {**revision.applied_filters, **action.filter_values}
    queries = []
    for result_id in dict.fromkeys(plan["component_results"].values()):
        result = owner.results.get(
            result_id, revision.thread_id, source_id=revision.source_id
        )
        receipt = query_execution(result, owner.results)
        values = _effective_filters(receipt.definition, applied)
        query, parameters = compile_query(
            receipt.definition,
            values,
            owner.results,
            revision.thread_id,
            revision.source_id,
        )
        queries.append(
            {
                "result_id": result_id,
                "definition": receipt.definition.model_dump(mode="json"),
                "filter_values": values,
                "query": query,
                "parameters": parameters,
            }
        )
    return queries


def _approval(owner, run, queries):
    return ApprovalRequest(
        interrupt_id=str(uuid4()),
        actions=[
            ApprovalAction(
                action_name="execute_dashboard_query",
                query=q["query"],
                arguments={
                    "definition": q["definition"],
                    "filter_values": q["filter_values"],
                    "parameters": q["parameters"],
                },
                allowed_decisions=["approve", "reject"],
                review_type="sql",
                source_id=run.source_id,
                dialect="duckdb",
                timeout_seconds=120,
                max_result_rows=owner.results.max_rows,
                description="Review the exact parameter-bound query over the saved data snapshot.",
            )
            for q in queries
        ],
    )


def _accept_review(state, command):
    pending = ApprovalRequest.model_validate(state["approval"])
    resumed = getattr(command, "resume", None)
    if not isinstance(resumed, dict) or set(resumed) != {pending.interrupt_id}:
        raise ValueError(
            "The saved dashboard query review does not match this decision."
        )
    payload = resumed[pending.interrupt_id]
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list) or len(decisions) != len(pending.actions):
        raise ValueError("One decision is required for each saved dashboard query.")
    if any(
        not isinstance(d, dict) or d.get("type") not in {"approve", "reject"}
        for d in decisions
    ):
        raise ValueError(
            "Saved dashboard queries accept approval or rejection; a new query requires an analytical turn."
        )
    state["rejected"] = any(d["type"] == "reject" for d in decisions)
    state["review_accepted"] = not state["rejected"]


def _report_spec(spec, results, thread_id, source_id, applied, input_result_ids):
    blocks = [
        {"type": "narrative", "title": "Applied filters", "body": FILTER_DESCRIPTION}
    ]
    scope = [
        "The filters use saved data snapshots. This action made no warehouse query.",
        f"Source: {source_id}",
        "Saved input datasets: " + ", ".join(input_result_ids),
        "Components without a filter binding retain their prior saved population.",
        "Selections below use JSON scalar values. An empty selection applies no constraint.",
    ]
    for filtering in spec.filters:
        bound = list(dict.fromkeys(b.component_id for b in filtering.bindings))
        scope.append(f"{filtering.label} (components: {', '.join(bound)}):")
        selected = applied.get(filtering.id, [])
        scope.extend(
            json.dumps(value, ensure_ascii=False, allow_nan=False) for value in selected
        )
        if not selected:
            scope.append("[] — all values")
    # Retain every permitted scalar without exceeding the report block limit.
    # Split between values, so an individual JSON scalar remains intact.
    body = []
    for line in scope:
        if sum(len(part) + 2 for part in body) + len(line) > 18_000:
            blocks.append(
                {
                    "type": "narrative",
                    "title": "Filter and snapshot scope",
                    "body": "\n\n".join(body),
                }
            )
            body = []
        body.append(line)
    if body:
        blocks.append(
            {
                "type": "narrative",
                "title": "Filter and snapshot scope",
                "body": "\n\n".join(body),
            }
        )
    metrics = []
    for component in spec.components:
        if isinstance(component, MetricComponent):
            result = results.get(
                component.metric.result_id, thread_id, source_id=source_id
            )
            if result.row_count:
                metrics.append(component.metric.model_dump(mode="json"))
            else:
                blocks.append(
                    {
                        "type": "narrative",
                        "title": component.metric.label,
                        "body": "No rows match the applied filters.",
                    }
                )
        elif isinstance(component, ChartComponent):
            if component.chart_id:
                blocks.append(
                    {
                        "type": "chart",
                        "chart_id": component.chart_id,
                        "summary": "Saved evidence for the applied dashboard population.",
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "table",
                        "title": "No rows match the applied filters",
                        "result_id": component.empty_result_id,
                        "row_limit": 10,
                    }
                )
        elif isinstance(component, TableComponent):
            blocks.append(
                {
                    "type": "table",
                    "title": component.title,
                    "result_id": component.result_id,
                    "columns": component.columns,
                    "row_limit": 10,
                }
            )
    blocks[1:1] = [
        {"type": "metrics", "metrics": metrics[i : i + 12]}
        for i in range(0, len(metrics), 12)
    ]
    return ReportSpec(
        title=spec.title,
        subtitle="Applied filters over a saved data snapshot",
        blocks=blocks,
        footer="Source completeness is unknown.",
    )


def _prepare_artifacts(owner, run, action_record, revision, plan, outputs):
    service = _service(owner)
    evidence = service._evidence(run.thread_id, run.source_id)
    components = []
    for component in revision.spec.components:
        if isinstance(component, TextComponent):
            components.append(
                component.model_copy(update={"title": None, "body": FILTER_DESCRIPTION})
            )
            continue
        prior_result_id = plan["component_results"].get(component.id)
        if prior_result_id is None:
            components.append(component)
            continue
        result = owner.results.get(
            outputs[prior_result_id], run.thread_id, source_id=run.source_id
        )
        if isinstance(component, MetricComponent):
            components.append(
                component.model_copy(
                    update={
                        "metric": component.metric.model_copy(
                            update={"result_id": result.result_id, "context": None}
                        )
                    }
                )
            )
        elif isinstance(component, TableComponent):
            components.append(
                component.model_copy(update={"result_id": result.result_id})
            )
        elif not result.row_count:
            template = _chart_template(owner, revision, component, evidence)
            receipt = query_execution(result, owner.results)
            components.append(
                component.model_copy(
                    update={
                        "chart_id": None,
                        "empty_result_id": result.result_id,
                        "title": _filtered_chart_title(template, receipt.definition),
                    }
                )
            )
        else:
            template = _chart_template(owner, revision, component, evidence)
            receipt = query_execution(result, owner.results)
            chart_request = ChartRequest.model_validate(
                {
                    **template.model_dump(
                        exclude={"chart_id", "source_result_id", "version"}
                    ),
                    "result_id": result.result_id,
                    "previous_chart_id": template.chart_id,
                    "title": _filtered_chart_title(template, receipt.definition),
                    "notes": [],
                }
            )
            runtime = SimpleNamespace(
                state={
                    "thread_id": run.thread_id,
                    "source_id": run.source_id,
                    "run_id": run.run_id,
                    "question": run.question,
                },
                tool_call_id=f"dashboard-chart-{component.id}",
            )
            chart = create_chart_tool(
                owner.results, owner.runs, source_id=run.source_id
            ).func(spec=chart_request, runtime=runtime)
            if not chart["ok"]:
                raise ValueError(chart["error"])
            components.append(
                component.model_copy(
                    update={
                        "chart_id": chart["chart_id"],
                        "empty_result_id": None,
                        "title": None,
                    }
                )
            )
    spec = revision.spec.model_copy(
        update={"components": components, "description": FILTER_DESCRIPTION}
    )
    result_ids, chart_ids = [], []
    for component in spec.components:
        result = service._component_result(component, evidence, analytical=True)
        if result is not None:
            result_ids.append(result.result_id)
        if isinstance(component, ChartComponent) and component.chart_id:
            chart_ids.append(component.chart_id)
    answer = resolve_answer(
        CoordinatorResponse(
            answer=FILTER_DESCRIPTION,
            result_ids=list(dict.fromkeys(result_ids)),
            chart_ids=chart_ids,
            assumptions=[
                "Filters use complete saved input populations.",
                "Source completeness is unknown.",
            ],
        ),
        thread_id=run.thread_id,
        source_id=run.source_id,
        results=owner.results,
        analyses=owner.analyses,
        runs=owner.runs,
    )
    service.validate_spec(
        spec, thread_id=run.thread_id, source_id=run.source_id, findings=answer
    )
    _, applied = service.validate_action_spec(
        spec, action_record, thread_id=run.thread_id, source_id=run.source_id
    )
    owner.runs.publish(run.run_id, answer)
    owner.dashboards.create_candidate(
        spec,
        thread_id=run.thread_id,
        source_id=run.source_id,
        run_id=run.run_id,
        question=revision.question,
        dashboard_id=revision.dashboard_id,
        expected_revision=revision.revision_id,
        request_id=action_record.request_id,
        applied_filters=applied,
        saved_filter_values=applied,
    )
    input_result_ids = list(
        dict.fromkeys(
            query_execution(
                owner.results.get(key, run.thread_id, source_id=run.source_id),
                owner.results,
            ).definition.input_result_id
            for key in outputs.values()
        )
    )
    report_spec = _report_spec(
        spec, owner.results, run.thread_id, run.source_id, applied, input_result_ids
    )
    owner.runs.save_report_spec(run.run_id, report_spec.model_dump(mode="json"))


async def execute_action(owner, run_id, command=None):
    """Execute one admitted action within RunManager's ordinary run lifecycle."""
    run = owner.runs.get(run_id)
    storage = owner.runs.storage
    plan = storage.get("dashboard_execution_plans", run_id, dict)
    action_record = owner.dashboards.action_for_run(run_id)
    if not plan or plan.get("kind") != "saved_filter" or not action_record:
        raise ValueError("The saved dashboard execution plan is unavailable.")
    if (plan["thread_id"], plan["source_id"]) != (run.thread_id, run.source_id):
        raise ValueError("The saved dashboard execution plan is outside this run.")
    revision = owner.dashboards.get_revision(
        plan["revision_id"], run.thread_id, source_id=run.source_id
    )
    head = owner.dashboards.get(
        revision.dashboard_id, run.thread_id, source_id=run.source_id
    )
    if head.revision_id != revision.revision_id:
        raise ValueError("The dashboard changed. Reload before resuming this action.")
    if (
        action_record.revision_id != revision.revision_id
        or action_record.dashboard_id != plan["dashboard_id"]
    ):
        raise ValueError(
            "The dashboard action does not match the saved execution plan."
        )
    if prepare_action(owner, revision, action_record.action) != plan:
        raise ValueError(
            "The saved dashboard query definitions changed. Start a new analytical turn."
        )
    state = storage.get("dashboard_execution_state", run_id, dict) or {
        "thread_id": run.thread_id,
        "source_id": run.source_id,
        "run_id": run_id,
        "outputs": {},
        "review_accepted": False,
    }
    if (state.get("thread_id"), state.get("source_id"), state.get("run_id")) != (
        run.thread_id,
        run.source_id,
        run_id,
    ):
        raise ValueError("The saved dashboard execution state is outside this run.")
    if state.get("rejected"):
        raise ValueError(
            "The dashboard query was rejected. Submit a new action to continue."
        )
    queries = _queries(owner, revision, action_record.action, plan)
    if state.get("queries") and json.dumps(
        state["queries"], sort_keys=True, allow_nan=False
    ) != json.dumps(queries, sort_keys=True, allow_nan=False):
        raise ValueError("The reviewed dashboard query or parameters changed.")
    state["queries"] = queries
    if set(state["outputs"]) - {q["result_id"] for q in queries}:
        raise ValueError(
            "The saved dashboard outputs do not match this execution plan."
        )
    for query in queries:
        if output_id := state["outputs"].get(query["result_id"]):
            output = owner.results.get(
                output_id, run.thread_id, source_id=run.source_id
            )
            receipt = query_execution(output, owner.results)
            if (
                receipt is None
                or receipt.definition.model_dump(mode="json") != query["definition"]
                or receipt.query != query["query"]
                or json.dumps(receipt.filter_values, sort_keys=True, allow_nan=False)
                != json.dumps(query["filter_values"], sort_keys=True, allow_nan=False)
                or json.dumps(receipt.parameters, sort_keys=True, allow_nan=False)
                != json.dumps(query["parameters"], sort_keys=True, allow_nan=False)
                or output.created_at < action_record.created_at
            ):
                raise ValueError(
                    "The cached dashboard output does not match its reviewed query and scope."
                )
    pending_queries = [q for q in queries if q["result_id"] not in state["outputs"]]
    if command is not None:
        if not state.get("approval"):
            raise ValueError("No saved dashboard query is awaiting that decision.")
        _accept_review(state, command)
        storage.put("dashboard_execution_state", run_id, state)
        if state.get("rejected"):
            raise ValueError(
                "The dashboard query was rejected. The previous dashboard is unchanged."
            )
    if owner.require_sql_approval and pending_queries and not state["review_accepted"]:
        if not state.get("approval"):
            state["approval"] = _approval(owner, run, pending_queries).model_dump(
                mode="json"
            )
        storage.put("dashboard_execution_state", run_id, state)
        owner.runs.require_approval(
            run_id, ApprovalRequest.model_validate(state["approval"])
        )
        return
    storage.put("dashboard_execution_state", run_id, state)
    for query in pending_queries:
        if reason := owner.runs.analysis_stop_reason(run_id):
            raise ValueError(reason)
        remaining = (
            getattr(owner.runs, "analysis_budget_seconds", 900)
            - owner.runs.diagnostics(run_id).active_ms / 1000
        )
        owner.runs.set_phase(run_id, "retrieving_data")
        owner.runs.add_event(
            run_id,
            "tool",
            "Calculate dashboard data",
            phase="started",
            agent="text-to-sql",
            tool=ActivityTool(name="execute_dashboard_query"),
        )

        def calculate(query=query):
            # Persist the output pointer inside the tracked worker. Cancellation
            # of its async waiter cannot lose a completed calculation's receipt.
            with owner.runs.worker(run_id):
                result = execute_dashboard_query(
                    query["definition"],
                    query["filter_values"],
                    results=owner.results,
                    runs=owner.runs,
                    thread_id=run.thread_id,
                    source_id=run.source_id,
                    run_id=run_id,
                    purpose="Apply dashboard filters",
                )
                state["outputs"][query["result_id"]] = result.result_id
                storage.put("dashboard_execution_state", run_id, state)

        async with asyncio.timeout(max(0, remaining)):
            await asyncio.to_thread(calculate)
        owner.runs.add_event(
            run_id,
            "tool",
            "Calculate dashboard data",
            phase="completed",
            agent="text-to-sql",
            tool=ActivityTool(name="execute_dashboard_query"),
        )
    if owner.runs.cancel_event(run_id).is_set():
        raise InterruptedError("Run stopped before dashboard publication.")
    if (
        not owner.runs.get(run_id).findings
        or not owner.dashboards.candidate_for_run(run_id)
        or not owner.runs.report_spec(run_id)
    ):

        def prepare():
            with owner.runs.worker(run_id):
                _prepare_artifacts(
                    owner, run, action_record, revision, plan, state["outputs"]
                )

        await asyncio.to_thread(prepare)
    owner.runs.set_phase(run_id, "preparing_report")
    current = owner.runs.get(run_id)
    artifact = None
    reference = owner.runs.report_reference(run_id)
    if reference:
        try:
            saved = owner.reports.get(
                reference["report_id"], run.thread_id, source_id=run.source_id
            )
            if (
                hashlib.sha256(saved.html.encode("utf-8")).hexdigest()
                == saved.html_sha256
                == reference["html_sha256"]
            ):
                artifact = saved
        except (StoreNotFound, FileNotFoundError):
            pass
    if artifact is None:

        def render():
            with owner.runs.worker(run_id):
                return generate_report(
                    ReportSpec.model_validate(owner.runs.report_spec(run_id)),
                    thread_id=run.thread_id,
                    source_id=run.source_id,
                    result_store=owner.results,
                    analysis_store=owner.analyses,
                    run_store=owner.runs,
                    report_store=owner.reports,
                    findings=current.findings,
                )

        async with asyncio.timeout(owner.presentation_budget_seconds):
            artifact = await asyncio.to_thread(render)
    owner.runs.attach_report(run_id, artifact.reference())
    owner._finish(run_id, current.findings)
