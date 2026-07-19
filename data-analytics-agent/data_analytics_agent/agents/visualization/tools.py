"""Source- and thread-scoped tools for the visualization specialist."""

from __future__ import annotations

from numbers import Real
from typing import Any

from langchain_core.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    VisualizationResult,
)
from data_analytics_agent.agents.visualization.validation import (
    validate_chart_spec,
)
from data_analytics_agent.schemas import SavedResult
from data_analytics_agent.stores import ResultStore, StoreNotFound


def _column_kind(rows: list[dict[str, Any]], column: str) -> str:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    if not values:
        return "empty"
    if all(isinstance(value, Real) and not isinstance(value, bool) for value in values):
        return "number"
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    return "text"


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
            "column_kinds": {
                column: _column_kind(sample, column)
                for column in result.columns
            },
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
        """Validate a chart specification without rendering a chart."""

        result = _get_result(
            result_store,
            spec.result_id,
            runtime,
            source_id=source_id,
        )
        validate_chart_spec(spec, result)
        return {
            "valid": True,
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
