"""Data-visualization specialist definition."""

from __future__ import annotations

from typing import Any

from data_analytics_agent.agents.visualization.tools import (
    create_create_chart_tool,
    create_finish_visualization_tool,
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

First call inspect_result_for_chart. It returns an immutable profile computed
over every stored row plus at most the first 10 rows. The saved result must
already contain business grouping, filters, calculations, binning, unique
heatmap cells, and meaningful ordering. The chart layer may only sort display
rows, limit displayed categories, change bar orientation, and choose labels,
legend behavior, or a curated palette. Histograms may bin one numeric
observation column, and box plots may compute chart-native quartiles and
whiskers. No other aggregation, joins, formulas, pivots, grain changes, missing
value filling, or statistical transforms are allowed.

Choose among bar, line, area, scatter, pie, histogram, box, heatmap, and map.
An explicitly requested chart type is a strict constraint; never substitute
another type. Use this role matrix:
- bar: categorical, temporal, or discrete-numeric x; numeric y
- line/area: temporal, numeric, or ordered-categorical x; numeric y
- scatter: numeric x and y; optional nonnegative numeric size
- pie: categorical x; nonnegative numeric y
- histogram: numeric x observations
- box: optional categorical x; numeric y observations
- heatmap: categorical, temporal, or already-binned numeric x and y; numeric
  value; one unique row per x/y cell
- map: location roles appropriate to its mode and numeric value when required

Use no more than five y series. Keep categorical charts readable. A display
category limit is allowed only with an explicit meaningful sort, must remain in
ChartSpec, and must not be used when the user asks for all categories. When no
meaningful ordering exists, request SQL reshaping instead of choosing arbitrary
first categories. ZIP and US
city/state maps use centroid markers; US-state and ISO-country choropleths use
built-in geometry; coordinate maps require latitude and longitude. Never
request a ZIP-boundary choropleth.

Construct a strict ChartSpec whose result_id is the assigned result. Call
validate_chart before create_chart. If validation is successful, call
create_chart exactly once. If validation identifies a correctable field mapping
or presentation option, revise the spec against the same result and validate
again. If the result needs aggregation, binning, a grain change, or different
columns, call finish_visualization exactly once with
`needs_sql_reshape`. If the requested type is impossible even with SQL
reshaping, call finish_visualization with `cannot_create`. These terminal tools
complete the assignment directly; do not make another model response after
calling one. The coordinator owns the final user response.
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
        sample_rows=min(source.limits.model_sample_rows, 10),
    )
    validate_chart = create_validate_chart_tool(
        result_store,
        source_id=source.source_id,
    )
    create_chart = create_create_chart_tool(
        result_store,
        source_id=source.source_id,
    )
    finish_visualization = create_finish_visualization_tool(
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
        "tools": [
            inspect_result,
            validate_chart,
            create_chart,
            finish_visualization,
        ],
        "model": model,
        "permissions": permissions,
    }
