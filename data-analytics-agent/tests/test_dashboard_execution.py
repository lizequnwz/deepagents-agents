"""Established filters run through RunManager without a model or source query."""

import asyncio
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from data_analytics_agent.agents.text_to_sql.dashboard_queries import (
    QueryDefinition,
    execute_dashboard_query,
)
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.dashboard.execution import FILTER_DESCRIPTION, prepare_action
from data_analytics_agent.dashboard.schemas import (
    DashboardAction,
    DashboardSpec,
    DashboardViewEdit,
)
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChatTurn, CoordinatorResponse, RunStatus
from data_analytics_agent.visualization.schemas import ChartRequest
from data_analytics_agent.visualization.tools import create_chart_tool


@pytest.fixture
def fixed_dashboard(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Sales by region")
    services.conversations.begin_run(thread, run)
    population = services.results.save(
        thread_id=thread,
        source_id="test",
        columns=["region", "sales"],
        rows=[
            {"region": "North", "sales": 10},
            {"region": "North", "sales": 5},
            {"region": "South", "sales": 20},
        ],
        executed_sql="SELECT region, sales FROM transactions",
    )
    common = {
        "input_result_id": population.result_id,
        "measures": [{"name": "total", "aggregation": "sum", "column": "sales"}],
        "filters": [{"id": "region", "column": "region", "kind": "category"}],
    }
    scalar = execute_dashboard_query(
        QueryDefinition(**common),
        {},
        results=services.results,
        runs=services.runs,
        thread_id=thread,
        source_id="test",
        run_id=run,
        purpose="Total sales",
    )
    grouped = execute_dashboard_query(
        QueryDefinition(**common, dimensions=["region"]),
        {},
        results=services.results,
        runs=services.runs,
        thread_id=thread,
        source_id="test",
        run_id=run,
        purpose="Sales by region",
    )
    chart = create_chart_tool(services.results, services.runs, source_id="test").func(
        spec=ChartRequest(
            result_id=grouped.result_id,
            chart_type="bar",
            title="Sales increased by 900%",
            x="region",
            y=["total"],
            notes=["Sales increased by 900%"],
        ),
        runtime=SimpleNamespace(
            state={"thread_id": thread, "source_id": "test", "run_id": run},
            tool_call_id="first-chart",
        ),
    )
    assert chart["ok"], chart
    findings = resolve_answer(
        CoordinatorResponse(
            answer="Original interpretation",
            result_ids=[scalar.result_id, grouped.result_id],
            chart_ids=[chart["chart_id"]],
        ),
        thread_id=thread,
        source_id="test",
        results=services.results,
        analyses=services.analyses,
        runs=services.runs,
    )
    services.runs.publish(run, findings)
    report = generate_report(
        ReportSpec(
            title="Sales dashboard",
            blocks=[
                {
                    "type": "table",
                    "title": "Sales by region",
                    "result_id": grouped.result_id,
                }
            ],
        ),
        thread_id=thread,
        source_id="test",
        result_store=services.results,
        analysis_store=services.analyses,
        run_store=services.runs,
        report_store=services.reports,
        findings=findings,
    )
    services.runs.attach_report(run, report.reference())
    answer = findings.model_copy(update={"report": report.reference()})
    services.runs.complete(run, answer)
    services.conversations.complete_run(
        thread, run, ChatTurn(run_id=run, user_message="Sales by region", answer=answer)
    )
    spec = DashboardSpec.model_validate(
        {
            "title": "Sales by region",
            "components": [
                {
                    "id": "sales",
                    "type": "metric",
                    "metric": {
                        "label": "Total sales",
                        "result_id": scalar.result_id,
                        "column": "total",
                        "context": "Sales increased by 900%",
                    },
                },
                {"id": "chart", "type": "chart", "chart_id": chart["chart_id"]},
                {
                    "id": "table",
                    "type": "table",
                    "result_id": grouped.result_id,
                    "title": "Sales by region",
                },
                {"id": "notes", "type": "text", "body": "Sales increased by 900%"},
            ],
            "filters": [
                {
                    "id": "region",
                    "label": "Region",
                    "bindings": [
                        {"component_id": key, "column": "region"}
                        for key in ("sales", "chart", "table")
                    ],
                }
            ],
        }
    )
    service = DashboardService(
        services.results,
        services.analyses,
        services.runs,
        services.reports,
        services.dashboards,
    )
    revision = service.create_from_report(
        run,
        thread_id=thread,
        source_id="test",
        spec=spec,
        request_id="initial-dashboard",
    )
    # These sentinels also catch source metadata initialization and catalog work.
    for name in (
        "agent_for_source",
        "backend_for_source",
        "source_version",
        "source",
        "require_ready_source",
    ):
        setattr(
            services,
            name,
            Mock(
                side_effect=AssertionError(f"Unexpected provider/source work: {name}")
            ),
        )
    return SimpleNamespace(
        services=services,
        service=service,
        revision=revision,
        thread=thread,
        population=population,
        scalar=scalar,
        grouped=grouped,
        url=f"/api/conversations/{thread}/dashboards/{revision.dashboard_id}/actions",
    )


def action(w, values, request_id="apply-region"):
    revision = w.services.dashboards.get(
        w.revision.dashboard_id, w.thread, source_id="test"
    )
    return DashboardAction(
        action="filter",
        expected_revision=revision.revision_id,
        request_id=request_id,
        filter_values={"region": values},
    )


def submit(w, client, values, request_id="apply-region"):
    request = action(w, values, request_id)
    response = client.post(w.url, json=request.model_dump(mode="json"))
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def assert_no_source_work(w):
    for name in (
        "agent_for_source",
        "backend_for_source",
        "source_version",
        "source",
        "require_ready_source",
    ):
        getattr(w.services, name).assert_not_called()


def test_filter_recomputes_scalar_and_chart_then_publishes_matching_report(
    fixed_dashboard,
):
    w = fixed_dashboard
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        saved = w.services.runs.get(run)
        assert saved.status == RunStatus.COMPLETED, saved.error
        view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
        assert view.components[0].value == 20
        assert view.components[2].rows == [{"region": "South", "total": 20}]
        assert view.revision.applied_filters == {"region": ["South"]}
        assert view.revision.revision_id != w.revision.revision_id
        assert view.revision.report_id == saved.answer.report.report_id
        repeat = client.post(
            w.url,
            json=action(w, ["South"], "apply-region")
            .model_copy(update={"expected_revision": w.revision.revision_id})
            .model_dump(mode="json"),
        )
        assert repeat.status_code == 202 and repeat.json()["run_id"] == run
        report = w.services.reports.get(
            view.revision.report_id, w.thread, source_id="test"
        )
        assert "900%" not in report.html
        narrative = "\n".join(
            getattr(block, "body", "") for block in report.spec.blocks
        )
        assert '"South"' in narrative
        assert "Region (components: sales, chart, table)" in narrative
        assert w.population.result_id in narrative
        assert "Source: test" in narrative
        assert "made no warehouse query" in narrative
        assert view.components[3].body == FILTER_DESCRIPTION
        assert saved.answer.analyses == []
        assert (
            w.services.dashboards.get_revision(
                w.revision.revision_id, w.thread, source_id="test"
            )
            == w.revision
        )
        # Reset starts from the original complete population, not the last subset.
        reset = submit(w, client, [], "clear-region")
        assert w.services.runs.get(reset).status == RunStatus.COMPLETED
        assert (
            w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
            .components[0]
            .value
            == 35
        )
    assert_no_source_work(w)


def test_pending_review_survives_restart_without_reopening_a_graph(fixed_dashboard):
    w = fixed_dashboard
    w.services.settings = replace(w.services.settings, require_sql_approval=True)
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        pending = w.services.runs.get(run).approval
    reopened = Services(settings=w.services.settings)
    for name in (
        "agent_for_source",
        "backend_for_source",
        "source_version",
        "source",
        "require_ready_source",
    ):
        setattr(
            reopened,
            name,
            Mock(side_effect=AssertionError("Must resume the saved query review")),
        )
    with TestClient(create_app(reopened)) as client:
        response = client.post(
            f"/api/runs/{run}/decisions",
            json={
                "interrupt_id": pending.interrupt_id,
                "decisions": [{"action": "approve"} for _ in pending.actions],
            },
        )
        assert response.status_code == 202, response.text
        assert reopened.runs.get(run).status == RunStatus.COMPLETED, reopened.runs.get(
            run
        ).error
    for name in (
        "agent_for_source",
        "backend_for_source",
        "source_version",
        "source",
        "require_ready_source",
    ):
        getattr(reopened, name).assert_not_called()


def test_empty_filter_and_reset_restore_chart_without_a_model(fixed_dashboard):
    w = fixed_dashboard
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["Missing"])
        assert w.services.runs.get(run).status == RunStatus.COMPLETED, (
            w.services.runs.get(run).error
        )
        empty = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
        assert empty.components[0].value is None
        assert empty.components[1].chart_id is None
        assert empty.components[1].row_count == 0
        restored = submit(w, client, ["North", "South"], "restore-chart")
        assert w.services.runs.get(restored).status == RunStatus.COMPLETED, (
            w.services.runs.get(restored).error
        )
        view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
        assert view.components[0].value == 35
        assert view.components[1].chart_id is not None
    assert_no_source_work(w)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_configured_sql_review_preserves_exact_queries_and_previous_head(
    fixed_dashboard, decision
):
    w = fixed_dashboard
    w.services.settings = replace(w.services.settings, require_sql_approval=True)
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        pending = w.services.runs.get(run)
        assert pending.status == RunStatus.APPROVAL_REQUIRED, pending.error
        assert (
            w.services.dashboards.get(
                w.revision.dashboard_id, w.thread, source_id="test"
            )
            == w.revision
        )
        assert len(pending.approval.actions) == 2  # shared chart/table query runs once
        for review in pending.approval.actions:
            assert review.allowed_decisions == ["approve", "reject"]
            assert "$p0" in review.query and "South" not in review.query
            assert review.arguments["parameters"] == {"p0": "South"}
        response = client.post(
            f"/api/runs/{run}/decisions",
            json={
                "interrupt_id": pending.approval.interrupt_id,
                "decisions": [{"action": decision} for _ in pending.approval.actions],
            },
        )
        assert response.status_code == 202, response.text
        finished = w.services.runs.get(run)
        if decision == "approve":
            assert finished.status == RunStatus.COMPLETED, finished.error
            assert (
                w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
                .components[0]
                .value
                == 20
            )
        else:
            assert finished.status == RunStatus.FAILED
            assert "rejected" in finished.error
            assert (
                w.services.dashboards.get(
                    w.revision.dashboard_id, w.thread, source_id="test"
                )
                == w.revision
            )
            assert (
                w.services.storage.get("dashboard_execution_state", run, dict)[
                    "outputs"
                ]
                == {}
            )
    assert_no_source_work(w)


def test_report_retry_reuses_saved_outputs_and_never_calls_a_graph(
    fixed_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import execution

    w = fixed_dashboard
    renderer = execution.generate_report
    failing = Mock(side_effect=ValueError("Report rendering failed"))
    monkeypatch.setattr(execution, "generate_report", failing)
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        assert w.services.runs.get(run).status == RunStatus.FAILED
        assert w.services.runs.get(run).findings is not None
        outputs = w.services.storage.get("dashboard_execution_state", run, dict)[
            "outputs"
        ]
        assert len(outputs) == 2
        assert (
            w.services.dashboards.get(
                w.revision.dashboard_id, w.thread, source_id="test"
            )
            == w.revision
        )
        monkeypatch.setattr(execution, "generate_report", renderer)
        monkeypatch.setattr(
            execution,
            "execute_dashboard_query",
            Mock(side_effect=AssertionError("Must reuse saved results")),
        )
        response = client.post(f"/api/runs/{run}/retry-report")
        assert response.status_code == 202, response.text
        assert w.services.runs.get(run).status == RunStatus.COMPLETED, (
            w.services.runs.get(run).error
        )
        assert (
            w.services.storage.get("dashboard_execution_state", run, dict)["outputs"]
            == outputs
        )
    assert_no_source_work(w)


def test_report_retry_rejects_a_cached_output_from_the_wrong_population(
    fixed_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import execution

    w = fixed_dashboard
    monkeypatch.setattr(
        execution, "generate_report", Mock(side_effect=ValueError("Report failed"))
    )
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        assert w.services.runs.get(run).findings is not None
        state = w.services.storage.get("dashboard_execution_state", run, dict)
        state["outputs"][w.scalar.result_id] = w.scalar.result_id
        w.services.storage.put("dashboard_execution_state", run, state)
        monkeypatch.setattr(
            execution,
            "execute_dashboard_query",
            Mock(side_effect=AssertionError("Must not recompute corrupted state")),
        )
        response = client.post(f"/api/runs/{run}/retry-report")
        assert response.status_code == 202, response.text
        failed = w.services.runs.get(run)
        assert failed.status == RunStatus.FAILED
        assert "cached dashboard output" in failed.error
        assert (
            w.services.dashboards.get(
                w.revision.dashboard_id, w.thread, source_id="test"
            )
            == w.revision
        )
    assert_no_source_work(w)


def test_resume_reuses_a_completed_query_and_its_accepted_review(
    fixed_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import execution

    w = fixed_dashboard
    w.services.settings = replace(w.services.settings, require_sql_approval=True)
    calculate = execution.execute_dashboard_query
    attempts = []

    def interrupted_sequence(definition, filter_values, **kwargs):
        attempts.append(definition)
        if len(attempts) == 2:
            raise ValueError("Second calculation failed")
        return calculate(definition, filter_values, **kwargs)

    monkeypatch.setattr(execution, "execute_dashboard_query", interrupted_sequence)
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        pending = w.services.runs.get(run).approval
        response = client.post(
            f"/api/runs/{run}/decisions",
            json={
                "interrupt_id": pending.interrupt_id,
                "decisions": [{"action": "approve"} for _ in pending.actions],
            },
        )
        assert response.status_code == 202, response.text
        assert w.services.runs.get(run).status == RunStatus.FAILED
        state = w.services.storage.get("dashboard_execution_state", run, dict)
        assert state["review_accepted"] is True and len(state["outputs"]) == 1
        completed_outputs = dict(state["outputs"])
        remaining = Mock(wraps=calculate)
        monkeypatch.setattr(execution, "execute_dashboard_query", remaining)
        response = client.post(f"/api/runs/{run}/resume")
        assert response.status_code == 202, response.text
        assert w.services.runs.get(run).status == RunStatus.COMPLETED, (
            w.services.runs.get(run).error
        )
        assert remaining.call_count == 1
        resumed = w.services.storage.get("dashboard_execution_state", run, dict)
        assert completed_outputs.items() <= resumed["outputs"].items()
        assert (
            w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
            .components[0]
            .value
            == 20
        )
    assert_no_source_work(w)


def test_report_retry_rejects_a_changed_dashboard_head(fixed_dashboard, monkeypatch):
    from data_analytics_agent.dashboard import execution

    w = fixed_dashboard
    monkeypatch.setattr(
        execution, "generate_report", Mock(side_effect=ValueError("Report failed"))
    )
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        revised = w.service.edit_view(
            w.revision.dashboard_id,
            w.thread,
            source_id="test",
            edit=DashboardViewEdit(
                expected_revision=w.revision.revision_id,
                request_id="new-layout",
                title="Revised view",
            ),
        )
        monkeypatch.setattr(
            execution,
            "execute_dashboard_query",
            Mock(side_effect=AssertionError("Must not query a stale action")),
        )
        response = client.post(f"/api/runs/{run}/retry-report")
        assert response.status_code == 202, response.text
        failed = w.services.runs.get(run)
        assert failed.status == RunStatus.FAILED and "dashboard changed" in failed.error
        assert (
            w.services.dashboards.get(
                w.revision.dashboard_id, w.thread, source_id="test"
            )
            == revised
        )
    assert_no_source_work(w)


def test_prose_during_review_runs_after_the_fixed_action_with_committed_context(
    fixed_dashboard,
):
    from tests.test_run_manager import Graph, Stream

    w = fixed_dashboard
    w.services.settings = replace(w.services.settings, require_sql_approval=True)
    with TestClient(create_app(w.services)) as client:
        run = submit(w, client, ["South"])
        pending = w.services.runs.get(run).approval
        queued = client.post(
            f"/api/runs/{run}/corrections",
            json={"message": "Explain the saved population."},
        )
        assert queued.status_code == 202, queued.text
        follow_up = queued.json()["run_id"]
        assert queued.json()["disposition"] == "follow_up"
        assert w.services.runs.get(run).corrections == []
        assert w.services.runs.get(follow_up).status == RunStatus.QUEUED
        graph = Graph(
            [
                Stream(
                    CoordinatorResponse(
                        answer="The saved population is scoped to the applied filters."
                    )
                )
            ]
        )
        manager = w.services.manager()
        resolver = Mock(return_value=graph)
        manager.agent_resolver = resolver
        manager.catalog_version_resolver = None
        decision = client.post(
            f"/api/runs/{run}/decisions",
            json={
                "interrupt_id": pending.interrupt_id,
                "decisions": [{"action": "approve"} for _ in pending.actions],
            },
        )
        assert decision.status_code == 202, decision.text
        assert w.services.runs.get(run).status == RunStatus.COMPLETED
        assert w.services.runs.get(follow_up).status == RunStatus.COMPLETED
        assert resolver.call_count == 1 and len(graph.inputs) == 1
        context = next(
            message["content"]
            for message in graph.inputs[0]["messages"]
            if "Dashboard context:" in message["content"]
        )
        assert '"applied_filters": {"region": ["South"]}' in context
        assert w.services.dashboards.get(
            w.revision.dashboard_id, w.thread, source_id="test"
        ).applied_filters == {"region": ["South"]}
    assert_no_source_work(w)


def test_eligibility_rejects_grouped_metrics_and_python_ancestors(fixed_dashboard):
    w = fixed_dashboard
    proposed = w.revision.model_copy(deep=True)
    proposed.spec.components[0].metric.result_id = w.grouped.result_id
    assert prepare_action(w.services, proposed, action(w, ["South"])) is None
    python = w.services.results.save(
        thread_id=w.thread,
        source_id="test",
        columns=["region", "sales"],
        rows=w.population.preview,
        kind="python",
    )
    derived = execute_dashboard_query(
        QueryDefinition(
            input_result_id=python.result_id,
            dimensions=[],
            measures=[{"name": "total", "aggregation": "sum", "column": "sales"}],
            filters=[{"id": "region", "column": "region"}],
        ),
        {},
        results=w.services.results,
        runs=w.services.runs,
        thread_id=w.thread,
        source_id="test",
        run_id=w.revision.run_id,
        purpose="Python-derived input",
    )
    proposed.spec.components[0].metric.result_id = derived.result_id
    assert prepare_action(w.services, proposed, action(w, ["South"])) is None


async def test_cancellation_keeps_head_and_resume_reuses_completed_queries(
    fixed_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import execution

    w = fixed_dashboard
    request = action(w, ["South"])
    plan = prepare_action(w.services, w.revision, request)
    record = w.services.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=request
    )
    run = w.services.runs.create(w.thread, "test", "Apply dashboard filters")
    w.services.dashboards.attach_action_run(record.action_id, run)
    w.services.storage.put("dashboard_execution_plans", run, plan)
    w.services.conversations.begin_run(w.thread, run)
    entered, release = Event(), Event()
    renderer = execution.generate_report

    def blocked_report(*args, **kwargs):
        entered.set()
        assert release.wait(5), "Test did not release the rendering worker"
        return renderer(*args, **kwargs)

    monkeypatch.setattr(execution, "generate_report", blocked_report)
    manager = w.services.manager()
    task = asyncio.create_task(manager.start(run))
    assert await asyncio.to_thread(entered.wait, 5)
    await manager.stop(run)
    await asyncio.sleep(0.01)
    await manager.stop(run)
    release.set()
    await task
    assert w.services.runs.get(run).status == RunStatus.PAUSED
    assert (
        w.services.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )
    outputs = w.services.storage.get("dashboard_execution_state", run, dict)["outputs"]
    monkeypatch.setattr(execution, "generate_report", renderer)
    monkeypatch.setattr(
        execution,
        "execute_dashboard_query",
        Mock(side_effect=AssertionError("Must reuse committed data")),
    )
    w.services.conversations.begin_run(w.thread, run)
    await manager.resume(run)
    assert w.services.runs.get(run).status == RunStatus.COMPLETED, w.services.runs.get(
        run
    ).error
    assert (
        w.services.storage.get("dashboard_execution_state", run, dict)["outputs"]
        == outputs
    )
    assert_no_source_work(w)


async def test_stop_before_scheduled_start_requires_explicit_resume(fixed_dashboard):
    w = fixed_dashboard
    request = action(w, ["South"])
    record = w.services.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=request
    )
    run = w.services.runs.create(w.thread, "test", "Apply dashboard filters")
    w.services.dashboards.attach_action_run(record.action_id, run)
    w.services.storage.put(
        "dashboard_execution_plans",
        run,
        prepare_action(w.services, w.revision, request),
    )
    w.services.conversations.begin_run(w.thread, run)
    manager = w.services.manager()
    await manager.stop(run)
    await manager.start(run)
    assert w.services.runs.get(run).status == RunStatus.PAUSED
    assert w.services.storage.get("dashboard_execution_state", run, dict) is None
    assert (
        w.services.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )
    w.services.conversations.begin_run(w.thread, run)
    await manager.resume(run)
    assert w.services.runs.get(run).status == RunStatus.COMPLETED, w.services.runs.get(
        run
    ).error
    assert_no_source_work(w)
