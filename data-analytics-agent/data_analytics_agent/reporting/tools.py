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
from data_analytics_agent.visualization.schemas import ChartSpec


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
    results, analyses, charts = {}, {}, {}

    def include(key):
        if key in results:
            return
        item = result_store.get(key, thread_id, source_id=source_id)
        results[key] = item
        for parent in item.parent_result_ids:
            include(parent)

    stored_charts = run_store.storage.load("charts", dict)
    for block in spec.blocks:
        if isinstance(block, ReportTableBlock):
            include(block.result_id)
        elif isinstance(block, ReportMetricsBlock):
            for metric in block.metrics:
                include(metric.result_id)
        elif isinstance(block, ReportChartBlock):
            entry = stored_charts.get(block.chart_id)
            if (
                not entry
                or entry["thread_id"] != thread_id
                or entry["source_id"] != source_id
            ):
                raise ValueError("Chart is outside this conversation.")
            chart = ChartSpec.model_validate(entry["spec"])
            charts[chart.chart_id] = chart
            include(chart.result_id)
        elif isinstance(block, ReportAnalysisBlock):
            saved = analysis_store.get(
                block.analysis_id, thread_id, source_id=source_id
            ).analysis
            outputs = []
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
            for key in saved.input_result_ids:
                include(key)
            for execution in saved.executions:
                for key in [
                    *execution.inputs.values(),
                    *execution.output_datasets.values(),
                ]:
                    include(key)
            analyses[block.analysis_id] = ResolvedDataAnalysis(
                reference_id=block.analysis_id,
                input_result_ids=saved.input_result_ids,
                answer=saved.answer,
                method=saved.method,
                assumptions=saved.assumptions,
                interpretation=saved.interpretation,
                warnings=saved.warnings,
                outputs=outputs,
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
    result_store, analysis_store, run_store, report_store, *, source_id
):
    @tool
    def create_report(report_json: str, runtime: ToolRuntime) -> dict:
        """Render the required HTML report from ReportSpec JSON with saved chart/analysis IDs.

        Publish findings first. Use chart blocks with chart_id, table blocks
        with result_id, and data_analysis blocks with analysis_id. Report metric
        values must reference a dataset column and row_index. Do not write HTML.
        """
        context = _runtime_context(runtime)
        if saved := run_store.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        try:
            spec = ReportSpec.model_validate_json(report_json)
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
        return analysis_store.get(
            analysis_id, context.thread_id, source_id=source_id
        ).analysis.model_facing()

    return inspect_conversation_analysis
