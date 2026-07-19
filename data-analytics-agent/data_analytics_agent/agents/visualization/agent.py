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

Honor the user's explicitly requested chart type when the saved result can
support it. Otherwise choose the simplest chart that answers the question.
Use these encoding roles:
- bar: categorical or temporal x, with one or more numeric y measures;
- line or area: ordered categorical or temporal x, with numeric y measures;
- scatter: numeric x and numeric y, with optional nonnegative numeric size;
- pie: unique categorical x and one nonnegative numeric y;
- histogram: one numeric x containing row-level observations;
- box: optional categorical x and numeric y containing observations, not
  precomputed quartiles;
- heatmap: categorical or temporal x and y dimensions, plus one numeric value;
  each populated x/y cell must be unique and the two-dimensional grid must be
  preserved;
- map: a supported geographic location role and optional numeric value, or
  numeric latitude and longitude for coordinate markers.

Use no more than five y series. Keep categorical charts readable. Prefer clear
business titles and axis or legend labels derived from the actual columns.
For horizontal bars, keep x as the category and y as the numeric measure; set
orientation rather than swapping their semantic roles. Do not use color, size,
or multiple series decoratively when they do not add meaning. ZIP and US
city/state maps use centroid markers; US-state and ISO-country choropleths use
built-in geometry; coordinate maps require latitude and longitude. Never
request a ZIP-boundary choropleth.

Construct a strict ChartSpec whose result_id is the assigned result. Call
validate_chart before create_chart. If validation fails, inspect the error,
correct only the chart mappings or permitted presentation settings, and
validate again. Never fabricate data, bypass validation, or reinterpret a
categorical dimension as a numeric measure. The create_chart call runs
automatically after validating the constrained specification. After
create_chart succeeds, return VisualizationResult with the exact chart and
success message returned by the tool. The coordinator owns the final user
response.
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
