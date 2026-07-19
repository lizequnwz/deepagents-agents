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
ID {source.source_id!r}. Produce one terminal visualization outcome for the
single saved result assigned by the coordinator.

Read the `chart-design` skill with `limit=1000`, then call
`inspect_result_for_chart` for the assigned result. Its profile covers every
stored row; its sample contains at most the first 10. Use only that result and
its existing columns. Do not write SQL, query the database, switch results,
generate code, or reconstruct business logic.

Honor an explicitly requested chart type. Build a strict `ChartSpec` with the
assigned `result_id`, then call `validate_chart`.

- If valid, call `create_chart` exactly once.
- If only the field mapping or a supported presentation option is wrong,
  revise against the same result and validate again.
- If different columns, aggregation, binning, or grain are required, call
  `finish_visualization` once with `needs_sql_reshape`.
- If the requested chart is impossible even after SQL reshaping, call
  `finish_visualization` once with `cannot_create`.

`create_chart` and `finish_visualization` are terminal. Do not emit another
model response or call another tool afterward; the coordinator owns the final
user response.
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
            "result and returns one terminal outcome: a validated declarative "
            "chart, a SQL-reshape request, or a clear impossibility."
        ),
        "system_prompt": _visualization_prompt(source),
        "tools": [
            inspect_result,
            validate_chart,
            create_chart,
            finish_visualization,
        ],
        "model": model,
        "skills": ["/project/skills/data-visualization/"],
        "permissions": permissions,
    }
