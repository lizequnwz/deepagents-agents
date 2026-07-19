"""Data-visualization specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.visualization.schemas import (
    VisualizationResult,
)
from data_analytics_agent.agents.visualization.tools import (
    create_create_chart_tool,
    create_inspect_result_for_chart_tool,
    create_validate_chart_tool,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore

VISUALIZATION_OUTPUT_RETRY_MESSAGE = """\
A visualization can finish only after create_chart succeeds. Fix any validation
error against the same saved result, then call create_chart again. Return
VisualizationResult only with the exact ChartSpec and success message returned
by create_chart.
"""


def _visualization_prompt(source: DataSource) -> str:
    return f"""\
You are the isolated data-visualization specialist for {source.name!r}, source
ID {source.source_id!r}. Create exactly one chart only from the saved result ID
assigned by the coordinator. Never write SQL, execute database queries, switch
results, generate Python code, or invent columns.

First call inspect_result_for_chart. The saved result must already contain
business grouping, filters, calculations, and ordering. The chart layer may
only sort rows, limit displayed categories, change bar orientation, and choose
labels or a curated palette. Histograms may bin one numeric column, and box
plots may compute their chart-native quartiles and whiskers. No other
aggregation, joins, formulas, pivots, or statistical transforms are allowed.

Choose among bar, line, area, scatter, pie, histogram, box, heatmap, and map.
Use no more than five y series. Keep categorical charts readable. ZIP and US
city/state maps use centroid markers; US-state and ISO-country choropleths use
built-in geometry; coordinate maps require latitude and longitude. Never
request a ZIP-boundary choropleth.

Construct a strict ChartSpec whose result_id is the assigned result. Call
validate_chart before create_chart. The create_chart call runs automatically
after validating the constrained specification. After create_chart succeeds,
return VisualizationResult with the exact chart and success message returned
by the tool. The coordinator owns the final user response.
"""


def build_visualization_subagent(
    *,
    source: DataSource,
    result_store: ResultStore,
    model: Any,
    permissions: list[Any],
) -> dict[str, Any]:
    """Build the optional constrained visualization specialist."""

    inspect_result = create_inspect_result_for_chart_tool(
        result_store,
        source_id=source.source_id,
        sample_rows=source.limits.model_sample_rows,
    )
    validate_chart = create_validate_chart_tool(
        result_store,
        source_id=source.source_id,
    )
    create_chart = create_create_chart_tool(
        result_store,
        source_id=source.source_id,
    )
    return {
        "name": "data-visualization",
        "description": (
            "Use only when the user explicitly asks to visualize, chart, "
            "plot, graph, or map a saved result. It inspects one chart-ready "
            "result, generates exactly one validated declarative chart, and "
            "returns the successful chart specification."
        ),
        "system_prompt": _visualization_prompt(source),
        "tools": [inspect_result, validate_chart, create_chart],
        "model": model,
        "permissions": permissions,
        "response_format": ToolStrategy(
            VisualizationResult,
            handle_errors=VISUALIZATION_OUTPUT_RETRY_MESSAGE,
            tool_message_content=(
                "Visualization completed from a validated chart specification."
            ),
        ),
    }
