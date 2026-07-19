"""Source- and thread-scoped tools for the visualization specialist."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    VisualizationOutcome,
    VisualizationResult,
)
from data_analytics_agent.agents.visualization.validation import (
    validate_chart_spec,
)
from data_analytics_agent.schemas import SavedResult
from data_analytics_agent.stores import ResultStore, StoreNotFound


def _get_result(
    result_store: ResultStore,
    result_id: str,
    runtime: ToolRuntime,
    *,
    source_id: str,
):
    try:
        context = _runtime_context(runtime)
        return result_store.get(
            result_id,
            context.thread_id,
            source_id=source_id,
        )
    except StoreNotFound as exc:
        raise ValueError(
            "That result does not exist in this data-source conversation."
        ) from exc


def chart_success_message(spec: ChartSpec) -> str:
    """Return the canonical success message shared with the coordinator."""

    return (
        f"Chart generated successfully: {spec.chart_type.value} chart "
        f"{spec.title!r}."
    )


def create_chart_result(
    spec: ChartSpec,
    result: SavedResult,
) -> VisualizationResult:
    """Validate one chart spec and return its authoritative tool result."""

    validate_chart_spec(spec, result)
    return VisualizationResult(
        outcome=VisualizationOutcome.CHART_CREATED,
        result_id=spec.result_id,
        answer=chart_success_message(spec),
        chart=spec,
    )


def create_inspect_result_for_chart_tool(
    result_store: ResultStore,
    *,
    source_id: str,
    sample_rows: int,
):
    @tool
    def inspect_result_for_chart(
        result_id: str,
        runtime: ToolRuntime,
    ) -> dict[str, Any]:
        """Inspect columns and a bounded sample before designing one chart."""

        result = _get_result(
            result_store,
            result_id,
            runtime,
            source_id=source_id,
        )
        sample = result.rows[:sample_rows]
        return {
            "result_id": result.result_id,
            "columns": result.columns,
            "profile": result.profile.model_dump(mode="json"),
            "row_count": result.row_count,
            "sample_rows": sample,
            "truncated": result.truncated,
        }

    return inspect_result_for_chart


def create_validate_chart_tool(
    result_store: ResultStore,
    *,
    source_id: str,
):
    @tool
    def validate_chart(
        spec: ChartSpec,
        runtime: ToolRuntime,
    ) -> dict[str, Any]:
        """Check a chart spec; return diagnostics without finishing the task."""

        result = _get_result(
            result_store,
            spec.result_id,
            runtime,
            source_id=source_id,
        )
        try:
            validate_chart_spec(spec, result)
        except ValueError as exc:
            return {
                "valid": False,
                "result_id": result.result_id,
                "message": str(exc),
            }
        return {
            "valid": True,
            "outcome": VisualizationOutcome.CHART_CREATED,
            "result_id": result.result_id,
            "chart_type": spec.chart_type,
            "message": "The chart specification is valid and chart-ready.",
        }

    return validate_chart


def create_create_chart_tool(
    result_store: ResultStore,
    *,
    source_id: str,
):
    @tool(return_direct=True)
    def create_chart(
        spec: ChartSpec,
        runtime: ToolRuntime,
    ) -> Command:
        """Generate one validated chart spec and finish the visualization."""

        result = _get_result(
            result_store,
            spec.result_id,
            runtime,
            source_id=source_id,
        )
        visualization = create_chart_result(spec, result)
        if not runtime.tool_call_id:
            raise RuntimeError("The chart tool call ID is unavailable.")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=visualization.model_dump_json(),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "structured_response": visualization,
            }
        )

    return create_chart


def create_finish_visualization_tool(
    result_store: ResultStore,
    *,
    source_id: str,
):
    @tool(return_direct=True)
    def finish_visualization(
        result_id: str,
        outcome: Literal["needs_sql_reshape", "cannot_create"],
        message: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Finish without a chart when reshaping is needed or impossible."""

        _get_result(
            result_store,
            result_id,
            runtime,
            source_id=source_id,
        )
        visualization = VisualizationResult(
            outcome=VisualizationOutcome(outcome),
            result_id=result_id,
            answer=message,
        )
        if not runtime.tool_call_id:
            raise RuntimeError("The visualization tool call ID is unavailable.")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=visualization.model_dump_json(),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "structured_response": visualization,
            }
        )

    return finish_visualization
