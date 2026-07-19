"""Data-visualization specialist definition."""

from __future__ import annotations

from typing import Any

from data_analytics_agent.agents.visualization.tools import (
    create_create_chart_tool,
    create_inspect_result_for_chart_tool,
    create_validate_chart_tool,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore


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
Honor an explicitly requested chart type when the saved result supports it.
For line and area charts, use an ordered categorical or temporal x axis and
numeric y measures. Use no more than five y series. Keep categorical charts
readable. ZIP and US
city/state maps use centroid markers; US-state and ISO-country choropleths use
built-in geometry; coordinate maps require latitude and longitude. Never
request a ZIP-boundary choropleth.

Construct a strict ChartSpec whose result_id is the assigned result. Call
validate_chart before create_chart. The create_chart call runs automatically
after validating the constrained specification and completes your assignment
directly. Call create_chart exactly once after validation; do not call it again
and do not make another model response after it succeeds. The coordinator owns
the final user response.
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
    }
