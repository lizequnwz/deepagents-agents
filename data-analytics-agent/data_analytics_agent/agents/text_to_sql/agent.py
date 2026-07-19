"""Text-to-SQL specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
    create_get_saved_result_tool,
    create_get_table_schema_tool,
    create_list_tables_tool,
    create_validate_sql_tool,
)
from data_analytics_agent.backends import SQLBackend
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.schemas import SQLAnalysisResult
from data_analytics_agent.stores import ResultStore

SQL_OUTPUT_RETRY_MESSAGE = """\
A SQL analysis can finish only after execute_sql succeeds. If a query was
rejected, apply the human feedback, revise and validate the SQL, call execute_sql
again, and wait for review. Return SQLAnalysisResult only with sql, result_id,
and row_count copied from the successful QueryResult.
"""


def _sql_subagent_prompt(source: DataSource) -> str:
    return f"""\
You are the isolated text-to-SQL analyst for {source.name!r}. The conversation
is permanently bound to source ID {source.source_id!r}, SQL dialect
{source.dialect!r}, and OSI model {source.semantic_virtual_path!r}.

Before writing SQL, read `{source.semantic_virtual_path}` with a read limit of
at least 1000 lines, then load the relevant query-writing and schema-exploration
skills. The selected OSI model is authoritative. Use list_tables and
get_table_schema only when it leaves a concrete ambiguity or appears
inconsistent with the live database. Use write_todos only for complex questions.

Semantic dataset and field names are conceptual identifiers, not SQL names.
Every SQL table must use the dataset's exact `source` value, and every SQL
column must use the chosen dialect expression's exact physical value.

Write exactly one read-only SELECT/CTE/set-operation query in the
{source.dialect} dialect. Default ordinary ranked or list results to five rows
unless the user requests another size. Chart semantics override that generic
row limit. When the result will be visualized, shape chart-ready data in
reviewed SQL: perform business grouping, filtering, calculations, and business
ordering there rather than leaving them to the chart layer. Preserve the rows
the requested chart needs:
- bar and pie results should contain the intended category-level measures;
- line and area results should retain the complete ordered series in scope;
- scatter, histogram, and box results should retain the numeric observations
  needed to show the distribution or relationship;
- heatmap results should contain one row per populated x/y cell, with both
  dimensions and a numeric value.

Never apply a blind top-level LIMIT to heatmap cells or truncate a time series
merely because five rows is the normal list default. A heatmap may contain at
most 500 populated cells. If a chart needs reduction, select meaningful
dimension members in a CTE first (for example, the top genres by total sales),
then retain all cells for those selected members across the requested second
dimension. Return explicit, stable column names suited to the chart roles.

Call validate_sql before execute_sql. Validation is structural and does not
submit SQL to the database. The execute_sql call pauses for human approval and
may be edited or rejected. Rejection is never terminal: apply the feedback,
revise and validate the SQL, call execute_sql again, and wait for another
review.

Return SQLAnalysisResult only after execute_sql succeeds. Its sql, result_id,
and row_count must come from that QueryResult, and sql must be the exact
executed_sql value. Do not return a rejection, proposed query, or missing result
as a completed analysis. If human feedback changed the requested scope, reflect
that revised scope in the answer and interpretation. Keep assumptions and
interpretation concise. Never expose private reasoning or more than
{source.limits.model_sample_rows} rows.
"""


def build_text_to_sql_subagent(
    *,
    source: DataSource,
    backend: SQLBackend,
    result_store: ResultStore,
    model: Any,
    permissions: list[Any],
) -> dict[str, Any]:
    """Build the source-bound, human-reviewed SQL specialist."""

    execute_sql = create_execute_sql_tool(source, backend, result_store)
    get_saved_result = create_get_saved_result_tool(
        result_store,
        source_id=source.source_id,
        model_sample_rows=source.limits.model_sample_rows,
    )
    fallback_tools = [
        create_list_tables_tool(backend),
        create_get_table_schema_tool(backend),
        create_validate_sql_tool(backend),
    ]
    return {
        "name": "text-to-sql",
        "description": (
            f"Use for every {source.name} database question and whenever a "
            "visualization needs a new chart-ready result. It reads the "
            "selected OSI model, writes and validates SQL, requests human "
            "review, executes, and interprets results."
        ),
        "system_prompt": _sql_subagent_prompt(source),
        "tools": [*fallback_tools, execute_sql, get_saved_result],
        "model": model,
        "skills": [
            "/project/skills/query-writing/",
            "/project/skills/schema-exploration/",
        ],
        "permissions": permissions,
        "interrupt_on": {
            "execute_sql": {
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        },
        "response_format": ToolStrategy(
            SQLAnalysisResult,
            handle_errors=SQL_OUTPUT_RETRY_MESSAGE,
            tool_message_content=(
                "SQL analysis completed from a reviewed execution."
            ),
        ),
    }
