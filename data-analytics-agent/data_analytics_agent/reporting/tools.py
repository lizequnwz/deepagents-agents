"""Shared evidence resolution and coordinator-owned report generation."""

from __future__ import annotations
import base64
from datetime import datetime, timezone
from pathlib import Path
import json
from langchain.tools import tool, ToolRuntime
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.reporting.schemas import (
    ReportSpec,
    ReportChartBlock,
    ReportTableBlock,
    ReportAnalysisBlock,
    ReportMetricsBlock,
    ResolvedDataAnalysis,
)
from data_analytics_agent.reporting.renderer import render_report
from data_analytics_agent.evidence import EvidenceResolver


def generate_report(
    spec,
    *,
    thread_id,
    source_id,
    result_store,
    analysis_store,
    run_store,
    report_store,
    findings=None,
):
    if findings:
        if findings.analytical_input:
            from data_analytics_agent.analytical_scope import scope_description
            from data_analytics_agent.reporting.schemas import ReportCalloutBlock

            blocks = [b for b in spec.blocks if not (isinstance(b, ReportCalloutBlock) and b.title == "Analytical population")]
            population = scope_description(findings.analytical_input)
            if findings.source_expansion_allowed:
                population += " Additional source retrieval was authorized. The selected snapshot is the starting population; consult the attached evidence for the resulting populations."
            spec = spec.model_copy(update={"blocks": [ReportCalloutBlock(title="Analytical population", body=population, variant="note"), *blocks]})
        selected_results = {r.result_id for r in findings.results}
        selected_analyses = {a.analysis_id for a in findings.analyses}
        selected_charts = {c.chart_id for c in findings.charts}
        for block in spec.blocks:
            references, allowed = [], set()
            if isinstance(block, ReportTableBlock):
                references, allowed = [block.result_id], selected_results
            elif isinstance(block, ReportMetricsBlock):
                references, allowed = (
                    [m.result_id for m in block.metrics],
                    selected_results,
                )
            elif isinstance(block, ReportChartBlock):
                references, allowed = [block.chart_id], selected_charts
            elif isinstance(block, ReportAnalysisBlock):
                references, allowed = [block.analysis_id], selected_analyses
            if unknown := set(references) - allowed:
                raise ValueError(
                    f"Report references were not selected in published findings: {sorted(unknown)}. Use the published evidence."
                )
        blocks = list(spec.blocks)
        chart_ids = {b.chart_id for b in blocks if isinstance(b, ReportChartBlock)}
        analysis_ids = {
            b.analysis_id for b in blocks if isinstance(b, ReportAnalysisBlock)
        }
        blocks.extend(
            ReportChartBlock(chart_id=c.chart_id, summary=c.title)
            for c in findings.charts
            if c.chart_id not in chart_ids
        )
        blocks.extend(
            ReportAnalysisBlock(
                analysis_id=a.analysis_id, title="Analysis", summary=a.answer
            )
            for a in findings.analyses
            if a.analysis_id and a.analysis_id not in analysis_ids
        )
        spec = spec.model_copy(update={"blocks": blocks})
    evidence = EvidenceResolver(
        thread_id=thread_id,
        source_id=source_id,
        results=result_store,
        analyses=analysis_store,
        runs=run_store,
    )
    results, charts = evidence.results, evidence.charts
    analyses = {}
    include = evidence.result
    for block in spec.blocks:
        if isinstance(block, ReportTableBlock):
            include(block.result_id)
        elif isinstance(block, ReportMetricsBlock):
            for metric in block.metrics:
                include(metric.result_id)
        elif isinstance(block, ReportChartBlock):
            evidence.chart(block.chart_id)
        elif isinstance(block, ReportAnalysisBlock):
            saved = evidence.analysis(block.analysis_id)
            outputs = []
            forecast_scores = []
            if saved.forecast_evaluation:
                forecast = saved.forecast_evaluation
                scores = include(forecast.scores_result_id)
                forecast_scores = scores.preview
            for execution in saved.executions:
                if execution.error:
                    continue
                for output in execution.outputs:
                    value = output.model_dump(mode="json", exclude_none=True)
                    if output.image_path:
                        value["image_base64"] = base64.b64encode(
                            Path(output.image_path).read_bytes()
                        ).decode()
                    outputs.append(value)
            analyses[block.analysis_id] = ResolvedDataAnalysis(
                reference_id=block.analysis_id,
                input_result_ids=saved.input_result_ids,
                answer=saved.answer,
                method=saved.method,
                assumptions=saved.assumptions,
                warnings=saved.warnings + (saved.forecast_evaluation.warnings if saved.forecast_evaluation else []),
                outputs=outputs,
                forecast_evaluation=saved.forecast_evaluation,
                forecast_scores=forecast_scores,
            )
    if findings:
        from data_analytics_agent.reporting.schemas import ReportCalloutBlock

        extra = []
        for reference in findings.results:
            if reference.result_id not in results:
                include(reference.result_id)
                extra.append(
                    ReportTableBlock(
                        result_id=reference.result_id,
                        title=reference.short_label or "Supporting evidence",
                        row_limit=10,
                    )
                )
        if findings.partial:
            extra.insert(
                0,
                ReportCalloutBlock(
                    title="Partial investigation",
                    body="These findings are supported by saved evidence, but the investigation is unfinished. "
                    + " ".join(findings.unresolved_questions),
                    variant="warning",
                ),
            )
        spec = spec.model_copy(update={"blocks": [*spec.blocks, *extra]})
    if spec.previous_report_id:
        report_store.get(spec.previous_report_id, thread_id, source_id=source_id)
    html = render_report(
        spec,
        results=results,
        analyses=analyses,
        charts=charts,
        generated_at=datetime.now(timezone.utc),
    )
    return report_store.save(
        thread_id=thread_id,
        source_id=source_id,
        spec=spec,
        html=html,
        input_result_ids=list(results),
        input_analysis_ids=list(analyses),
    )


def create_create_report_tool(
    result_store,
    analysis_store,
    run_store,
    report_store,
    *,
    source_id,
    semantic_catalog=None,
):
    @tool
    def create_report(report_json: str, runtime: ToolRuntime) -> dict:
        """Render the required HTML report from ReportSpec JSON with saved chart/analysis IDs.

        Publish findings first. Use chart blocks with chart_id, table blocks
        with result_id, and data_analysis blocks with analysis_id. Report metric
        values must reference a dataset column and row_index. Period change cards use
        comparison bindings (metric_ref, population, grain, period_column,
        current_period, baseline_period, baseline_row_index); application code
        calculates changes. No free-text change field. Do not write HTML.
        """
        context = _runtime_context(runtime)
        if saved := run_store.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        try:
            spec = ReportSpec.model_validate_json(report_json)
            previous = run_store.get(context.run_id).previous_report_id
            if previous:
                spec = spec.model_copy(update={"previous_report_id": previous})
            if semantic_catalog is not None:
                for block in spec.blocks:
                    if isinstance(block, ReportMetricsBlock):
                        for metric in block.metrics:
                            if (
                                metric.comparison
                                and metric.comparison.metric_ref
                                not in semantic_catalog.metrics
                            ):
                                raise ValueError(
                                    "Comparison metric_ref must be an exact catalog metric; inspect semantic definitions before retrying."
                                )
            if run_store.get(context.run_id).findings is None:
                raise ValueError("Call publish_findings before creating the report.")
            run_store.save_report_spec(context.run_id, spec.model_dump(mode="json"))
            run_store.set_phase(context.run_id, "preparing_report")
            artifact = generate_report(
                spec,
                thread_id=context.thread_id,
                source_id=source_id,
                result_store=result_store,
                analysis_store=analysis_store,
                run_store=run_store,
                report_store=report_store,
                findings=run_store.get(context.run_id).findings,
            )
            run_store.attach_report(context.run_id, artifact.reference())
            response = {
                "ok": True,
                "report": artifact.reference().model_dump(mode="json"),
            }
            run_store.storage.commit(
                context.run_id, runtime.tool_call_id, json.dumps(response)
            )
            return response
        except (ValueError, KeyError, IndexError, OSError) as exc:
            return {"ok": False, "error": str(exc), "retryable": True}

    return create_report


def create_list_conversation_analyses_tool(analysis_store, *, source_id):
    @tool
    def list_conversation_analyses(runtime: ToolRuntime) -> dict:
        """Discover saved analytical findings and their execution IDs."""
        context = _runtime_context(runtime)
        return {
            "analyses": [
                {
                    "analysis_id": saved.analysis_id,
                    "answer": saved.analysis.answer,
                    "outcome": saved.analysis.outcome,
                    "input_result_ids": saved.analysis.input_result_ids,
                    "execution_ids": [
                        e.execution_id for e in saved.analysis.executions
                    ],
                }
                for saved in analysis_store.list_for_conversation(
                    context.thread_id, source_id=source_id
                )
            ]
        }

    return list_conversation_analyses


def create_inspect_conversation_analysis_tool(analysis_store, *, source_id):
    @tool
    def inspect_conversation_analysis(analysis_id: str, runtime: ToolRuntime) -> dict:
        """Inspect an analysis without returning binary figures or complete datasets."""
        context = _runtime_context(runtime)
        try:
            return analysis_store.get(
                analysis_id, context.thread_id, source_id=source_id
            ).analysis.model_facing()
        except KeyError:
            return {
                "ok": False,
                "error": f"Unknown or out-of-scope analysis {analysis_id}. Use list_conversation_analyses and retry with a valid reference.",
            }

    return inspect_conversation_analysis


def create_revise_report_title_tool(
    results, analyses, runs, reports, conversations, *, source_id
):
    @tool
    def revise_report_title(title: str, runtime: ToolRuntime) -> dict:
        """Change only the latest saved report title; preserve findings, charts and every report block.

        Use for title-only requests instead of publish_findings/create_report.
        The application selects the exact prior report; no artifact ID is needed.
        """
        from data_analytics_agent.presentation_edits import (
            ReportTitleEdit,
            revise_report_title as render_title,
        )

        context = _runtime_context(runtime)
        if saved := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        try:
            previous = next(
                (
                    t.answer
                    for t in reversed(conversations.get(context.thread_id).turns)
                    if t.answer and t.answer.report
                ),
                None,
            )
            if previous is None:
                return {"ok": False, "error": "No saved report to rename."}
            edit = ReportTitleEdit(report_id=previous.report.report_id, title=title)
            report = reports.get(edit.report_id, context.thread_id, source_id=source_id)
            existing = runs.get(context.run_id).findings
            if existing and existing.model_dump(
                exclude={"report"}
            ) != previous.model_dump(exclude={"report"}):
                return {
                    "ok": False,
                    "error": "Rewritten findings are already published. Title-only changes must preserve findings and run before publication.",
                }
            runs.save_report_spec(
                context.run_id,
                {
                    **report.spec.model_dump(mode="json"),
                    "title": edit.title,
                    "previous_report_id": report.report_id,
                },
            )
            runs.publish(context.run_id, previous.model_copy(update={"report": None}))
            artifact = render_title(
                report,
                edit.title,
                results=results,
                analyses=analyses,
                runs=runs,
                reports=reports,
            )
            runs.attach_report(context.run_id, artifact.reference())
            response = {
                "ok": True,
                "report": artifact.reference().model_dump(mode="json"),
            }
            runs.storage.commit(
                context.run_id, runtime.tool_call_id, json.dumps(response)
            )
            return response
        except (ValueError, KeyError, IndexError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    return revise_report_title
