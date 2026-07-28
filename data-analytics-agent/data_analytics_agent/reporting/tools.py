"""Coordinator-owned, source-scoped report generation tool."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import ValidationError

from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisOutcome,
)
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.reporting.renderer import render_report
from data_analytics_agent.reporting.schemas import (
    ReportChartBlock,
    ReportSpec,
    ReportStatisticalBlock,
    ReportTableBlock,
    ReportToolFailure,
    ReportToolIssue,
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


def _report_failure(
    code: str,
    message: str,
    *,
    issues: list[ReportToolIssue] | None = None,
) -> str:
    """Return an expected, compact failure as a successful tool result."""

    return ReportToolFailure(
        code=code,
        message=message,
        issues=issues or [],
    ).model_dump_json()


def _strip_json_fence(value: str) -> str:
    """Accept an accidental Markdown JSON fence without weakening validation."""

    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _validation_issues(error: ValidationError) -> list[ReportToolIssue]:
    issues: list[ReportToolIssue] = []
    for item in error.errors(
        include_input=False,
        include_url=False,
    )[:8]:
        location = ".".join(str(part) for part in item.get("loc") or ())
        issues.append(
            ReportToolIssue(
                path=location or "report",
                message=str(item.get("msg") or "Invalid value."),
            )
        )
    return issues


def _parse_report_spec(report_json: str) -> ReportSpec | str:
    """Parse common transport variations, then apply the strict internal model."""

    candidate: Any = _strip_json_fence(report_json)
    try:
        candidate = json.loads(candidate)
        # Be tolerant of one accidental extra JSON encoding layer.
        if isinstance(candidate, str):
            candidate = json.loads(candidate)
    except (TypeError, json.JSONDecodeError) as exc:
        return _report_failure(
            "invalid_report_json",
            "The report was not valid JSON. Correct the JSON and retry once.",
            issues=[
                ReportToolIssue(
                    path="report_json",
                    message=f"{exc.msg} at line {exc.lineno}, column {exc.colno}.",
                )
            ]
            if isinstance(exc, json.JSONDecodeError)
            else None,
        )

    # Accept the obsolete {"spec": {...}} wrapper used by the first prototype.
    if (
        isinstance(candidate, dict)
        and "title" not in candidate
        and "blocks" not in candidate
        and isinstance(candidate.get("spec"), dict)
    ):
        candidate = candidate["spec"]

    try:
        return ReportSpec.model_validate(candidate)
    except ValidationError as exc:
        return _report_failure(
            "invalid_report_spec",
            "The report specification was invalid. Fix the listed fields "
            "and retry once.",
            issues=_validation_issues(exc),
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
    @tool
    def create_report(report_json: str, runtime: ToolRuntime) -> str:
        """Create one validated, self-contained HTML report artifact.

        Use only after loading the report-design skill and obtaining every
        required analysis artifact. Pass a JSON-encoded ReportSpec string in
        `report_json`; do not pass an object or HTML. Trusted application code
        validates the JSON, resolves scoped data, renders the HTML, and owns all
        JavaScript.
        """

        parsed = _parse_report_spec(report_json)
        if isinstance(parsed, str):
            return parsed
        spec = parsed
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
                    except StoreNotFound:
                        return _report_failure(
                            "artifact_not_found",
                            "That statistical analysis does not exist in this "
                            "data-source conversation.",
                            issues=[
                                ReportToolIssue(
                                    path="blocks.analysis_id",
                                    message=(
                                        "Use a listed analysis ID or run the "
                                        "required analysis first."
                                    ),
                                )
                            ],
                        )
                    if (
                        saved.analysis.outcome
                        is not StatisticalAnalysisOutcome.ANALYSIS_COMPLETED
                    ):
                        return _report_failure(
                            "artifact_not_ready",
                            "Only completed statistical analyses can be embedded.",
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
                        return _report_failure(
                            "artifact_not_ready",
                            "The current run has no completed reviewed "
                            "statistical execution to embed.",
                        )
                    if execution.parent_result_id != block.parent_result_id:
                        return _report_failure(
                            "artifact_not_found",
                            "The current statistical block references a "
                            "different parent result.",
                            issues=[
                                ReportToolIssue(
                                    path="blocks.parent_result_id",
                                    message=(
                                        "Use the exact result ID reviewed by "
                                        "the statistical analysis."
                                    ),
                                )
                            ],
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
                except StoreNotFound:
                    return _report_failure(
                        "artifact_not_found",
                        "A report block references a result outside this "
                        "data-source conversation.",
                        issues=[
                            ReportToolIssue(
                                path="blocks.result_id",
                                message=(
                                    "Use a listed result ID or obtain the "
                                    "required result first."
                                ),
                            )
                        ],
                    )

        if spec.previous_report_id:
            try:
                report_store.get(
                    spec.previous_report_id,
                    context.thread_id,
                    source_id=source_id,
                )
            except StoreNotFound:
                return _report_failure(
                    "artifact_not_found",
                    "The previous report does not exist in this conversation.",
                    issues=[
                        ReportToolIssue(
                            path="previous_report_id",
                            message=(
                                "Use the exact prior report ID or omit this "
                                "field for a new report."
                            ),
                        )
                    ],
                )

        generated_at = datetime.now(timezone.utc)
        try:
            html = render_report(
                spec,
                results=results,
                analyses=analyses,
                generated_at=generated_at,
            )
        except ValueError as exc:
            return _report_failure(
                "report_render_failed",
                "The report could not be rendered from the supplied "
                "specification. Correct it and retry once.",
                issues=[
                    ReportToolIssue(path="blocks", message=str(exc))
                ],
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
