"""Text-to-SQL specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware
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
Finish only after `execute_sql` succeeds. After rejection, apply the feedback,
validate the revision, and submit it for review. Copy `sql`, `result_id`,
`columns`, `sample_rows`, `profile`, `row_count`, and `truncated` from the
successful `QueryResult`; use its `executed_sql` as `sql`.
"""


def _sql_subagent_prompt(source: DataSource) -> str:
    return f"""\
You are the isolated text-to-SQL specialist for {source.name!r}, permanently
bound to source ID {source.source_id!r}, SQL dialect {source.dialect!r}, and OSI
model `{source.semantic_virtual_path}`.

Before analysis, read the OSI file, the `schema-exploration` skill, and the
`query-writing` skill with `limit=1000`. Issue these three independent reads
in one tool-call batch when possible, and read each path at most once per
assignment. Re-read only if the earlier content was truncated or compacted,
or if needed content fell outside the returned range. Apply both skills to
produce one reviewed result that answers the assignment and is chart-ready
when requested. The OSI model is authoritative; use live schema tools only
for a concrete gap or suspected drift.

Hard boundaries:
- Submit exactly one read-only SELECT, CTE, or set-operation statement.
- Do not add `LIMIT` unless the user explicitly requests a row count. Ranking
  words require deterministic ordering but do not imply a row count.
- Call `validate_sql` before `execute_sql`. Validation does not query the
  database; execution pauses for human approval.
- A rejection requires revision and another review. A human-edited execution
  replaces stale scope from the assignment.

Finish only after `execute_sql` succeeds. Return `SQLAnalysisResult` using the
successful `QueryResult`: copy its exact `executed_sql` to `sql` and copy its
result ID, columns, sample rows, full-result profile, stored row count, and
truncation flag. Provide a direct business answer, material assumptions, and a
concise interpretation. Do not expose private reasoning or more than the
provided 10 sample rows.
"""


def build_text_to_sql_subagent(
    *,
    source: DataSource,
    backend: SQLBackend,
    result_store: ResultStore,
    model: Any,
    permissions: list[Any],
    middleware: list[Any] | None = None,
) -> dict[str, Any]:
    """Build the source-bound, human-reviewed SQL specialist."""

    execute_sql = create_execute_sql_tool(source, backend, result_store)
    review_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "execute_sql": {
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        }
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
        "tools": [*fallback_tools, execute_sql],
        "model": model,
        "skills": ["/project/skills/text-to-sql/"],
        "permissions": permissions,
        # after_model hooks run in reverse registration order. Keep HITL first
        # so execution-budget checks run before an approval is presented.
        "middleware": [review_middleware, *(middleware or [])],
        "response_format": ToolStrategy(
            SQLAnalysisResult,
            handle_errors=SQL_OUTPUT_RETRY_MESSAGE,
            tool_message_content=(
                "SQL analysis completed from a reviewed execution."
            ),
        ),
    }
