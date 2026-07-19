"""Text-to-SQL specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
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
columns, sample_rows, profile, row_count, and truncated copied from the
successful QueryResult.
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
{source.dialect} dialect. Do not add LIMIT unless the user explicitly requests
a row count. Words such as "top", "bottom", "highest", or "lowest" require
deterministic ordering but do not imply a row count by themselves. When the
result will be visualized, shape it for the requested chart: perform business
grouping, filtering, calculations, ordering, binning, and limiting requested
by the user in reviewed SQL rather than leaving them to the chart layer.
Preserve the complete observation, ordered time series, distribution,
relationship, or unique heatmap grid required by that chart. Call validate_sql
before execute_sql.
Validation is structural and does not submit SQL to the database. The
execute_sql call pauses for human approval and may be edited or rejected.
Rejection is never terminal: apply the feedback, revise and validate the SQL,
call execute_sql again, and wait for another review.

Return SQLAnalysisResult only after execute_sql succeeds. Its sql, result_id,
columns, sample_rows, profile, row_count, and truncated must come from that
QueryResult, and sql must be the exact executed_sql value. Do not return a
rejection, proposed query, or missing result as a completed analysis. If human
feedback changed the requested scope, reflect that revised scope in the answer
and interpretation. Keep assumptions and interpretation concise. Never expose
private reasoning or more than 10 rows.
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
        "tools": [*fallback_tools, execute_sql],
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
