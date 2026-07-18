"""Deep Agent construction."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from text2sql_agent.config import Settings
from text2sql_agent.schemas import FinalAnswer, SQLAnalysisResult
from text2sql_agent.sql_tools import (
    AgentContext,
    _readonly_authorizer,
    create_execute_sql_tool,
    create_get_saved_result_tool,
)
from text2sql_agent.stores import ResultStore

COORDINATOR_PROMPT = """\
You coordinate a conversational data analyst for the Chinook SQLite database.
Delegate every request that needs database facts or SQL to the `text-to-sql`
subagent using the task tool. You may use get_saved_result for follow-ups about
an existing result. Do not invent database facts or execute SQL yourself.

Return a FinalAnswer with a direct answer, the exact executed SQL and result ID
when present, material assumptions, and a concise interpretation. Do not expose
private chain of thought, tool payloads, or more than ten database rows.

Human review inside the SQL subagent may change the requested limit, filters,
grouping, or other scope. In that case, the reviewed execution and the
subagent's structured result are authoritative. Describe what actually ran and
what it returned; do not repeat stale scope from the original user message.
"""

SQL_SUBAGENT_PROMPT = """\
You are the isolated Chinook text-to-SQL analyst.

Before writing SQL, read `/project/semantic/chinook.osi.yaml` with a read limit
of at least 1000 lines, then load the relevant query-writing and
schema-exploration skills. The OSI model is authoritative. Use table/schema
tools only when it leaves a concrete ambiguity or appears inconsistent with the
live database. Use write_todos only for complex questions.

Semantic dataset and field names are conceptual identifiers, not SQL names.
Every SQL table must use the dataset's exact `source` value, and every SQL
column must use the field expression's exact physical value. For example, use
`InvoiceLine`, not `invoice_lines`, and `UnitPrice`, not `unit_price`.

Write exactly one read-only SQLite SELECT/CTE/set query and check it before
calling execute_sql. The execute_sql call pauses for human approval and may be
edited or rejected. Rejection is never a terminal outcome: apply the feedback,
revise and check the SQL, call execute_sql again, and wait for another review.
Default ranked or list results to five rows unless the user requests another
size. Never use the toolkit's direct query tool.

Return SQLAnalysisResult only after execute_sql succeeds. Its sql, result_id,
and row_count must come from that QueryResult, and sql must be the exact
executed_sql value. Do not return a rejection, proposed query, or missing result
as a completed analysis. If human feedback changed the requested scope, reflect
that revised scope in the answer and interpretation. Keep assumptions and
interpretation concise. Never expose private reasoning or more than ten rows.
"""

SQL_OUTPUT_RETRY_MESSAGE = """\
A SQL analysis can finish only after execute_sql succeeds. If a query was
rejected, apply the human feedback, revise and check the SQL, call execute_sql
again, and wait for review. Return SQLAnalysisResult only with sql, result_id,
and row_count copied from the successful QueryResult.
"""


def _readonly_sql_database(path: Path) -> SQLDatabase:
    resolved = path.resolve(strict=True)

    def introspection_authorizer(
        action: int,
        arg1: str | None,
        arg2: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        # SQLAlchemy and SQLite reflection require read-only PRAGMA calls.
        # The toolkit's direct query tool is not exposed, and mode=ro remains
        # the final write barrier for this introspection-only connection.
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_OK
        return _readonly_authorizer(
            action, arg1, arg2, database, trigger
        )

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{resolved.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        connection.set_authorizer(introspection_authorizer)
        return connection

    engine = create_engine(
        "sqlite://",
        creator=connect,
        poolclass=NullPool,
    )
    return SQLDatabase(engine, sample_rows_in_table_info=0)


def _project_backend(project_root: Path) -> CompositeBackend:
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/project/": FilesystemBackend(
                root_dir=project_root, virtual_mode=True
            )
        },
    )


def build_agent(
    settings: Settings,
    result_store: ResultStore,
    *,
    model: Any | None = None,
    checkpointer: InMemorySaver | None = None,
):
    """Build the coordinator and its one custom SQL subagent."""

    if not settings.database_path.is_file():
        raise FileNotFoundError(
            f"Chinook database not found at {settings.database_path}"
        )

    register_harness_profile(
        f"openai:{settings.model}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
        ),
    )
    chat_model = model or ChatOpenAI(model=settings.model)

    execute_sql = create_execute_sql_tool(
        settings.database_path,
        result_store,
        settings.sql_timeout_seconds,
    )
    get_saved_result = create_get_saved_result_tool(result_store)

    toolkit = SQLDatabaseToolkit(
        db=_readonly_sql_database(settings.database_path),
        llm=chat_model,
    )
    allowed_tool_names = {
        "sql_db_list_tables",
        "sql_db_schema",
        "sql_db_query_checker",
    }
    fallback_tools = [
        tool for tool in toolkit.get_tools() if tool.name in allowed_tool_names
    ]

    permissions = [
        FilesystemPermission(
            operations=["read"],
            paths=[
                "/project/AGENTS.md",
                "/project/semantic/**",
                "/project/skills/**",
            ],
            mode="allow",
        ),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/project/**"],
            mode="deny",
        ),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/**"],
            mode="deny",
        ),
    ]

    sql_subagent = {
        "name": "text-to-sql",
        "description": (
            "Use for every Chinook database question: it reads the OSI model, "
            "writes SQL, requests human review, executes, and interprets results."
        ),
        "system_prompt": SQL_SUBAGENT_PROMPT,
        "tools": [*fallback_tools, execute_sql, get_saved_result],
        "model": chat_model,
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

    return create_deep_agent(
        name="chinook-data-analyst",
        model=chat_model,
        tools=[get_saved_result],
        system_prompt=COORDINATOR_PROMPT,
        memory=["/project/AGENTS.md"],
        subagents=[sql_subagent],
        backend=_project_backend(settings.project_root),
        permissions=permissions,
        response_format=ProviderStrategy(FinalAnswer, strict=True),
        context_schema=AgentContext,
        checkpointer=checkpointer or InMemorySaver(),
    )
