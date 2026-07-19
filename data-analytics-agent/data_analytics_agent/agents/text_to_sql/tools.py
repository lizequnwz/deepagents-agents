"""Backend-neutral model-facing SQL and saved-result tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from deepagents.graph import DeepAgentState
from langchain.tools import ToolRuntime, tool
from sqlglot import exp

from data_analytics_agent.backends import SQLBackend, SQLValidationError
from data_analytics_agent.backends.validation import (
    validate_readonly_sql as _validate_readonly_sql,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.schemas import QueryResult, ResultPage
from data_analytics_agent.stores import ResultStore, StoreNotFound

MAX_RESULT_ROWS = 500
MODEL_SAMPLE_ROWS = 10


@dataclass(frozen=True)
class AgentContext:
    thread_id: str
    run_id: str
    source_id: str


class AnalyticsAgentState(DeepAgentState):
    """Run scope shared by the coordinator and its inline subagents."""

    thread_id: str
    run_id: str
    source_id: str


def _runtime_context(runtime: ToolRuntime) -> AgentContext:
    """Read run scope from graph state inherited by inline subagents."""

    state = runtime.state
    try:
        return AgentContext(
            thread_id=str(state["thread_id"]),
            run_id=str(state["run_id"]),
            source_id=str(state["source_id"]),
        )
    except KeyError as exc:
        raise RuntimeError("The agent run scope is unavailable.") from exc


def validate_readonly_sql(
    query: str,
    dialect: str = "sqlite",
) -> exp.Query:
    """Compatibility wrapper around the backend-neutral structural validator."""

    return _validate_readonly_sql(query, dialect=dialect)


def execute_query(
    *,
    backend: SQLBackend,
    source: DataSource,
    query: str,
    thread_id: str,
    result_store: ResultStore,
) -> QueryResult:
    """Execute exact validated SQL and persist its capped normalized artifact."""

    backend.validate_sql(query)
    execution = backend.execute(
        query,
        timeout_seconds=source.limits.timeout_seconds,
        max_rows=source.limits.max_result_rows,
    )
    stored = result_store.save(
        thread_id=thread_id,
        source_id=source.source_id,
        executed_sql=query,
        columns=execution.columns,
        rows=execution.rows,
        truncated=execution.truncated,
        elapsed_ms=execution.elapsed_ms,
    )
    return QueryResult(
        result_id=stored.result_id,
        executed_sql=query,
        columns=execution.columns,
        sample_rows=execution.rows[: source.limits.model_sample_rows],
        row_count=len(execution.rows),
        truncated=execution.truncated,
        elapsed_ms=execution.elapsed_ms,
    )


def create_list_tables_tool(backend: SQLBackend):
    @tool
    def list_tables() -> dict[str, Any]:
        """List live database tables and views as a schema-drift fallback."""

        return {"tables": backend.list_tables()}

    return list_tables


def create_get_table_schema_tool(backend: SQLBackend):
    @tool
    def get_table_schema(table_names: list[str]) -> dict[str, Any]:
        """Inspect live columns for named tables as a schema-drift fallback."""

        tables = backend.get_table_schema(table_names)
        return {"tables": [asdict(table) for table in tables]}

    return get_table_schema


def create_validate_sql_tool(backend: SQLBackend):
    @tool
    def validate_sql(query: str) -> dict[str, Any]:
        """Validate one query structurally without submitting it to the database."""

        backend.validate_sql(query)
        return {
            "valid": True,
            "dialect": backend.dialect,
            "message": "The query is one structurally read-only statement.",
        }

    return validate_sql


def create_execute_sql_tool(
    source: DataSource,
    backend: SQLBackend,
    result_store: ResultStore,
):
    @tool
    def execute_sql(query: str, runtime: ToolRuntime) -> dict[str, Any]:
        """Execute one human-reviewed, source-bound, read-only query.

        The complete capped result is stored as an application artifact. Only a
        small sample and an opaque result ID are returned to the model.
        """

        context = _runtime_context(runtime)
        if context.source_id != source.source_id:
            raise ValueError(
                "The conversation source does not match this SQL backend."
            )
        result = execute_query(
            backend=backend,
            source=source,
            query=query,
            thread_id=context.thread_id,
            result_store=result_store,
        )
        return result.model_dump(mode="json")

    return execute_sql


def create_get_saved_result_tool(
    result_store: ResultStore,
    *,
    source_id: str,
    model_sample_rows: int,
):
    @tool
    def get_saved_result(
        result_id: str,
        runtime: ToolRuntime,
        offset: int = 0,
        limit: int = MODEL_SAMPLE_ROWS,
    ) -> dict[str, Any]:
        """Read a small page from a prior result in this source conversation."""

        context = _runtime_context(runtime)
        safe_limit = min(max(limit, 1), model_sample_rows)
        try:
            page = result_store.page(
                result_id,
                context.thread_id,
                source_id=source_id,
                offset=offset,
                limit=safe_limit,
            )
        except StoreNotFound as exc:
            raise ValueError(
                "That result does not exist in this data-source conversation."
            ) from exc
        model_page = ResultPage(
            **page.model_dump(exclude={"limit"}), limit=safe_limit
        )
        return model_page.model_dump(mode="json")

    return get_saved_result
