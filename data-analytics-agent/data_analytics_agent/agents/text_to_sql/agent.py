"""Text-to-SQL specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    TodoListMiddleware,
)
from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
)
from data_analytics_agent.backends import SQLBackend
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.schemas import SQLAnalysisResponse
from data_analytics_agent.stores import ResultStore


def _sql_output_retry_message(require_approval: bool) -> str:
    review_recovery = (
        "After rejection, apply the feedback and submit the revision for "
        "review. "
        if require_approval
        else "Repair validation or execution failures before retrying. "
    )
    return (
        "Finish only after `execute_sql` succeeds. "
        f"{review_recovery}"
        "Copy `result_id` and `executed_sql` from the successful "
        "`QueryResult`, using `executed_sql` as `sql`. The application owns "
        "the saved rows, columns, profile, count, and truncation state."
    )


SQL_OUTPUT_RETRY_MESSAGE = _sql_output_retry_message(True)


def _sql_subagent_prompt(
    source: DataSource,
    *,
    require_approval: bool,
) -> str:
    execution_mode = (
        "Execution pauses for human approve/edit/reject. After approval, the "
        "backend validates once and executes. A rejection requires revision "
        "and another review. A human-edited execution replaces stale scope "
        "from the assignment."
        if require_approval
        else "The backend validates once and executes immediately without a "
        "human interrupt. Repair validation or execution failures before "
        "retrying."
    )
    return f"""\
You are the isolated text-to-SQL specialist for {source.name!r}, permanently
bound to source ID {source.source_id!r}, SQL dialect {source.dialect!r}, and OSI
model `{source.semantic_virtual_path}`.

Before analysis, read the OSI file and the `query-writing` skill with
`limit=1000`. Issue these two independent reads in one tool-call batch when
possible, and read each path at most once per assignment. Re-read only if the
earlier content was truncated or compacted, or if needed content fell outside
the returned range. Apply the skill to produce one validated result that
answers the assignment and is chart-ready when requested. The OSI model is
authoritative and contains the complete queryable schema.

Hard boundaries:
- Submit exactly one read-only SELECT, CTE, or set-operation statement.
- Query only physical sources from the OSI model or CTEs defined inside the
  proposed query. Saved result IDs are opaque application evidence handles,
  never database table or view names. If an assignment mentions a prior result
  ID, use its stated findings only as context and write fresh source SQL for the
  requested business shape.
- Do not add `LIMIT` unless the user explicitly requests a row count. Ranking
  words require deterministic ordering but do not imply a row count.
- Call `execute_sql`. It validates the statement once immediately before
  execution. If it returns an error observation, revise the query while attempts
  remain. {execution_mode}

Finish only after `execute_sql` succeeds. Return `SQLAnalysisResponse` using the
successful `QueryResult`: copy its exact `executed_sql` to `sql` and its result
ID to `result_id`. The application already owns the exact rows, columns,
full-result profile, stored row count, and truncation flag; do not reproduce
them. Provide a direct business answer, material assumptions, and a concise
interpretation. Do not expose private reasoning or more than the provided 10
sample rows.
"""


def build_text_to_sql_subagent(
    *,
    source: DataSource,
    backend: SQLBackend,
    result_store: ResultStore,
    model: Any,
    permissions: list[Any],
    require_approval: bool,
    middleware: list[Any] | None = None,
) -> dict[str, Any]:
    """Build the source-bound SQL specialist."""

    execute_sql = create_execute_sql_tool(source, backend, result_store)
    agent_middleware: list[Any] = []
    if require_approval:
        agent_middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "execute_sql": {
                        "allowed_decisions": ["approve", "edit", "reject"]
                    }
                }
            )
        )
    agent_middleware.extend([TodoListMiddleware(), *(middleware or [])])
    return {
        "name": "text-to-sql",
        "description": (
            f"Use for every {source.name} database question and whenever a "
            "visualization needs a new chart-ready result. It reads the "
            "selected OSI model, writes and validates SQL, "
            + (
                "requests human review, "
                if require_approval
                else "executes automatically, "
            )
            + "and interprets results."
        ),
        "system_prompt": _sql_subagent_prompt(
            source,
            require_approval=require_approval,
        ),
        "tools": [execute_sql],
        "model": model,
        "skills": ["/project/skills/text-to-sql/"],
        "permissions": permissions,
        # after_model hooks run in reverse registration order. When present,
        # keep HITL first so budget checks run before approval is presented.
        "middleware": agent_middleware,
        "response_format": ToolStrategy(
            SQLAnalysisResponse,
            handle_errors=_sql_output_retry_message(require_approval),
            tool_message_content=(
                "SQL analysis completed from a validated execution."
            ),
        ),
    }
