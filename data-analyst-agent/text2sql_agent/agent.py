"""Source-bound Data Analytics Agent construction."""

from __future__ import annotations

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
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from text2sql_agent.backends import SQLBackend
from text2sql_agent.config import Settings
from text2sql_agent.data_sources import DataSource
from text2sql_agent.schemas import FinalAnswer, SQLAnalysisResult
from text2sql_agent.sql_tools import (
    AgentContext,
    create_execute_sql_tool,
    create_get_saved_result_tool,
    create_get_table_schema_tool,
    create_list_tables_tool,
    create_validate_sql_tool,
)
from text2sql_agent.stores import ResultStore

SQL_OUTPUT_RETRY_MESSAGE = """\
A SQL analysis can finish only after execute_sql succeeds. If a query was
rejected, apply the human feedback, revise and validate the SQL, call execute_sql
again, and wait for review. Return SQLAnalysisResult only with sql, result_id,
and row_count copied from the successful QueryResult.
"""


def _coordinator_prompt(source: DataSource) -> str:
    return f"""\
You coordinate a conversational data analyst for the selected data source
{source.name!r} (source ID {source.source_id!r}). Delegate every request that
needs database facts or SQL to the `text-to-sql` subagent using the task tool.
You may use get_saved_result for follow-ups about an existing result. Do not
invent database facts, switch data sources, or execute SQL yourself.

Return a FinalAnswer with a direct answer, the exact executed SQL and result ID
when present, material assumptions, and a concise interpretation. Do not expose
private chain of thought, tool payloads, or more than
{source.limits.model_sample_rows} database rows.

Human review inside the SQL subagent may change the requested limit, filters,
grouping, or other scope. In that case, the reviewed execution and the
subagent's structured result are authoritative. Describe what actually ran and
what it returned; do not repeat stale scope from the original user message.
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
{source.dialect} dialect. Default ranked or list results to five rows unless the
user requests another size. Call validate_sql before execute_sql. Validation is
structural and does not submit SQL to the database. The execute_sql call pauses
for human approval and may be edited or rejected. Rejection is never terminal:
apply the feedback, revise and validate the SQL, call execute_sql again, and wait
for another review.

Return SQLAnalysisResult only after execute_sql succeeds. Its sql, result_id,
and row_count must come from that QueryResult, and sql must be the exact
executed_sql value. Do not return a rejection, proposed query, or missing result
as a completed analysis. If human feedback changed the requested scope, reflect
that revised scope in the answer and interpretation. Keep assumptions and
interpretation concise. Never expose private reasoning or more than
{source.limits.model_sample_rows} rows.
"""


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
    source: DataSource,
    backend: SQLBackend,
    model: Any | None = None,
    checkpointer: InMemorySaver | None = None,
):
    """Build one cached coordinator graph bound to one registered source."""

    if not source.semantic_model_path.is_file():
        raise FileNotFoundError(
            f"OSI semantic model not found at {source.semantic_model_path}"
        )
    backend_errors = backend.readiness_errors()
    if backend_errors:
        raise RuntimeError(" ".join(backend_errors))

    register_harness_profile(
        f"openai:{settings.model}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
        ),
    )
    chat_model = model or ChatOpenAI(model=settings.model)

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
            f"Use for every {source.name} database question. It reads the "
            "selected OSI model, writes and validates SQL, requests human "
            "review, executes, and interprets results."
        ),
        "system_prompt": _sql_subagent_prompt(source),
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
        name="data-analytics-agent",
        model=chat_model,
        tools=[get_saved_result],
        system_prompt=_coordinator_prompt(source),
        memory=["/project/AGENTS.md"],
        subagents=[sql_subagent],
        backend=_project_backend(settings.project_root),
        permissions=permissions,
        response_format=ProviderStrategy(FinalAnswer, strict=True),
        context_schema=AgentContext,
        checkpointer=checkpointer or InMemorySaver(),
    )
