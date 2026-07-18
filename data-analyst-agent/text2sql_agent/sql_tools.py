"""Read-only SQLite execution and model-facing result tools."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from text2sql_agent.schemas import QueryResult, ResultPage
from text2sql_agent.stores import ResultStore, StoreNotFound

MAX_RESULT_ROWS = 500
MODEL_SAMPLE_ROWS = 10


class SQLValidationError(ValueError):
    """Raised when SQL is not one safe, read-only SQLite query."""


@dataclass(frozen=True)
class AgentContext:
    thread_id: str
    run_id: str


def validate_readonly_sql(query: str) -> exp.Query:
    """Parse and validate one SELECT/CTE/set-operation query."""

    if not query or not query.strip():
        raise SQLValidationError("SQL cannot be empty.")
    try:
        statements = parse(query, read="sqlite")
    except ParseError as exc:
        raise SQLValidationError(f"Invalid SQLite SQL: {exc}") from exc
    statements = [statement for statement in statements if statement is not None]
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is required.")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise SQLValidationError(
            "Only read-only SELECT, CTE, and set-operation queries are allowed."
        )

    forbidden_names = {
        "Alter",
        "Analyze",
        "Attach",
        "Command",
        "Commit",
        "Copy",
        "Create",
        "Delete",
        "Detach",
        "Drop",
        "Execute",
        "Grant",
        "Insert",
        "LoadData",
        "Lock",
        "Merge",
        "Pragma",
        "Reindex",
        "Revoke",
        "Rollback",
        "Set",
        "Transaction",
        "TruncateTable",
        "Update",
        "Use",
        "Vacuum",
    }
    for node in statement.walk():
        if node.__class__.__name__ in forbidden_names:
            raise SQLValidationError(
                f"Unsafe SQL operation {node.__class__.__name__} is not allowed."
            )
    return statement


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _readonly_authorizer(
    action: int,
    _arg1: str | None,
    _arg2: str | None,
    _database: str | None,
    _trigger: str | None,
) -> int:
    denied_names = {
        "SQLITE_ALTER_TABLE",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DELETE",
        "SQLITE_DETACH",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_DROP_VTABLE",
        "SQLITE_INSERT",
        "SQLITE_PRAGMA",
        "SQLITE_REINDEX",
        "SQLITE_SAVEPOINT",
        "SQLITE_TRANSACTION",
        "SQLITE_UPDATE",
    }
    denied_codes = {
        getattr(sqlite3, name)
        for name in denied_names
        if hasattr(sqlite3, name)
    }
    return sqlite3.SQLITE_DENY if action in denied_codes else sqlite3.SQLITE_OK


def execute_query(
    *,
    database_path: Path,
    query: str,
    thread_id: str,
    result_store: ResultStore,
    timeout_seconds: float,
) -> QueryResult:
    """Execute the exact validated SQL using a read-only SQLite connection."""

    validate_readonly_sql(query)
    resolved = database_path.resolve(strict=True)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    started = time.monotonic()
    deadline = started + timeout_seconds

    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    try:
        connection.set_authorizer(_readonly_authorizer)
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() >= deadline else 0, 1_000
        )
        cursor = connection.execute(query)
        columns = [column[0] for column in cursor.description or []]
        raw_rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
        truncated = len(raw_rows) > MAX_RESULT_ROWS
        capped_rows = raw_rows[:MAX_RESULT_ROWS]
        rows = [
            {
                column: _json_value(value)
                for column, value in zip(columns, raw_row, strict=True)
            }
            for raw_row in capped_rows
        ]
    except sqlite3.DatabaseError as exc:
        if "interrupted" in str(exc).lower():
            raise TimeoutError(
                f"SQL execution exceeded {timeout_seconds:g} seconds."
            ) from exc
        raise
    finally:
        connection.close()

    elapsed_ms = (time.monotonic() - started) * 1_000
    stored = result_store.save(
        thread_id=thread_id,
        executed_sql=query,
        columns=columns,
        rows=rows,
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )
    return QueryResult(
        result_id=stored.result_id,
        executed_sql=query,
        columns=columns,
        sample_rows=rows[:MODEL_SAMPLE_ROWS],
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


def create_execute_sql_tool(
    database_path: Path, result_store: ResultStore, timeout_seconds: float
):
    @tool
    def execute_sql(query: str, runtime: ToolRuntime) -> dict[str, Any]:
        """Execute one human-reviewed read-only SQLite query.

        The complete capped result is stored as an application artifact. Only ten
        sample rows and the result ID are returned to the model.
        """

        result = execute_query(
            database_path=database_path,
            query=query,
            thread_id=runtime.context.thread_id,
            result_store=result_store,
            timeout_seconds=timeout_seconds,
        )
        return result.model_dump(mode="json")

    return execute_sql


def create_get_saved_result_tool(result_store: ResultStore):
    @tool
    def get_saved_result(
        result_id: str,
        runtime: ToolRuntime,
        offset: int = 0,
        limit: int = MODEL_SAMPLE_ROWS,
    ) -> dict[str, Any]:
        """Read up to ten rows from a prior result in the current conversation."""

        safe_limit = min(max(limit, 1), MODEL_SAMPLE_ROWS)
        try:
            page = result_store.page(
                result_id,
                runtime.context.thread_id,
                offset=offset,
                limit=safe_limit,
            )
        except StoreNotFound as exc:
            raise ValueError(
                "That result does not exist in this conversation."
            ) from exc
        model_page = ResultPage(
            **page.model_dump(exclude={"limit"}), limit=safe_limit
        )
        return model_page.model_dump(mode="json")

    return get_saved_result
