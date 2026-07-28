"""Coordinator-owned, source-scoped report generation tool."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain.tools import ToolRuntime, tool

from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisOutcome,
)
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.reporting.renderer import render_report
from data_analytics_agent.reporting.schemas import (
    CreateReportToolInput,
    ReportChartBlock,
    ReportSpec,
    ReportStatisticalBlock,
    ReportTableBlock,
    ReportToolResult,
    ResolvedStatisticalAnalysis,
)
from data_analytics_agent.stores import (
    ReportStore,
    ResultStore,
    RunStore,
    StatisticalAnalysisStore,
    StoreNotFound,
)


def create_list_conversation_analyses_tool(
    analysis_store: StatisticalAnalysisStore,
    *,
    source_id: str,
):
    @tool
    def list_conversation_analyses(runtime: ToolRuntime) -> dict:
        """List reusable completed statistical analyses without binary figures."""

        context = _runtime_context(runtime)
        items = analysis_store.list_for_conversation(
            context.thread_id,
            source_id=source_id,
        )
        return {
            "analyses": [
                {
                    "analysis_id": item.analysis_id,
                    "parent_result_id": item.analysis.parent_result_id,
                    "answer": item.analysis.answer,
                    "method": item.analysis.method,
                    "interpretation": item.analysis.interpretation,
                    "output_names": [output.name for output in item.analysis.outputs],
                    "created_at": item.created_at.isoformat(),
                }
                for item in items
            ]
        }

    return list_conversation_analyses


def create_inspect_conversation_analysis_tool(
    analysis_store: StatisticalAnalysisStore,
    *,
    source_id: str,
):
    @tool
    def inspect_conversation_analysis(
        analysis_id: str,
        runtime: ToolRuntime,
    ) -> dict:
        """Inspect one reusable statistical analysis without binary figures."""

        context = _runtime_context(runtime)
        try:
            item = analysis_store.get(
                analysis_id,
                context.thread_id,
                source_id=source_id,
            )
        except StoreNotFound as exc:
            raise ValueError(
                "That statistical analysis does not exist in this data-source "
                "conversation."
            ) from exc
        payload = item.analysis.model_dump(mode="json", exclude_none=True)
        for output in payload.get("outputs") or []:
            if output.get("kind") == "figure":
                output.pop("image_base64", None)
                output["rendered"] = True
        return payload

    return inspect_conversation_analysis


def create_create_report_tool(
    result_store: ResultStore,
    analysis_store: StatisticalAnalysisStore,
    run_store: RunStore,
    report_store: ReportStore,
    *,
    source_id: str,
):
    @tool(args_schema=CreateReportToolInput)
    def create_report(spec: ReportSpec, runtime: ToolRuntime) -> str:
        """Create one validated, self-contained HTML report artifact.

        Use only after loading the report-design skill and obtaining every
        required analysis artifact. The model supplies declarative content and
        design choices; trusted application code resolves scoped data, renders
        the HTML, and owns all JavaScript.
        """

        context = _runtime_context(runtime)
        if context.source_id != source_id:
            raise ValueError(
                "The conversation source does not match this report renderer."
            )

        results = {}
        analyses = {}
        analysis_references: list[str] = []
        for block in spec.blocks:
            result_id: str | None = None
            if isinstance(block, ReportTableBlock):
                result_id = block.result_id
            elif isinstance(block, ReportChartBlock):
                result_id = block.chart.result_id
            elif isinstance(block, ReportStatisticalBlock):
                if block.analysis_id:
                    try:
                        saved = analysis_store.get(
                            block.analysis_id,
                            context.thread_id,
                            source_id=source_id,
                        )
                    except StoreNotFound as exc:
                        raise ValueError(
                            "That statistical analysis does not exist in this "
                            "data-source conversation."
                        ) from exc
                    if (
                        saved.analysis.outcome
                        is not StatisticalAnalysisOutcome.ANALYSIS_COMPLETED
                    ):
                        raise ValueError(
                            "Only completed statistical analyses can be embedded."
                        )
                    key = block.analysis_id
                    analyses[key] = ResolvedStatisticalAnalysis(
                        reference_id=key,
                        parent_result_id=saved.analysis.parent_result_id,
                        answer=saved.analysis.answer,
                        method=saved.analysis.method,
                        assumptions=saved.analysis.assumptions,
                        interpretation=saved.analysis.interpretation,
                        warnings=saved.analysis.warnings,
                        outputs=[
                            output.model_dump(mode="json", exclude_none=True)
                            for output in saved.analysis.outputs
                        ],
                    )
                    analysis_references.append(key)
                    result_id = saved.analysis.parent_result_id
                else:
                    execution = run_store.get_statistical_execution(context.run_id)
                    if execution is None:
                        raise ValueError(
                            "The current run has no completed reviewed statistical "
                            "execution to embed."
                        )
                    if execution.parent_result_id != block.parent_result_id:
                        raise ValueError(
                            "The current statistical block references a different "
                            "parent result."
                        )
                    key = f"current:{block.parent_result_id}"
                    analyses[key] = ResolvedStatisticalAnalysis(
                        reference_id=f"run:{context.run_id}",
                        parent_result_id=execution.parent_result_id,
                        answer=block.summary,
                        method=block.method,
                        assumptions=block.assumptions,
                        interpretation=block.interpretation,
                        warnings=execution.warnings,
                        outputs=[
                            output.model_dump(mode="json", exclude_none=True)
                            for output in execution.outputs
                        ],
                    )
                    analysis_references.append(f"run:{context.run_id}")
                    result_id = execution.parent_result_id
            if result_id and result_id not in results:
                try:
                    results[result_id] = result_store.get(
                        result_id,
                        context.thread_id,
                        source_id=source_id,
                    )
                except StoreNotFound as exc:
                    raise ValueError(
                        "A report block references a result outside this "
                        "data-source conversation."
                    ) from exc

        if spec.previous_report_id:
            try:
                report_store.get(
                    spec.previous_report_id,
                    context.thread_id,
                    source_id=source_id,
                )
            except StoreNotFound as exc:
                raise ValueError(
                    "The previous report does not exist in this conversation."
                ) from exc

        generated_at = datetime.now(timezone.utc)
        html = render_report(
            spec,
            results=results,
            analyses=analyses,
            generated_at=generated_at,
        )
        artifact = report_store.save(
            thread_id=context.thread_id,
            source_id=source_id,
            spec=spec,
            html=html,
            input_result_ids=list(results),
            input_analysis_ids=analysis_references,
        )
        result = ReportToolResult(
            report=artifact.reference(),
            message=(
                f"Self-contained HTML report {artifact.title!r} created "
                f"successfully as version {artifact.version}."
            ),
        )
        return result.model_dump_json()

    return create_report
