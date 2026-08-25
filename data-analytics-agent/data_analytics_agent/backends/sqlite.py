"""Read-only SQLite backend implementation."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from data_analytics_agent.backends.base import (
    BackendExecutionResult,
    ColumnInfo,
    SQLExecutionError,
    TableInfo,
    normalize_result_value,
)
from data_analytics_agent.backends.validation import validate_readonly_sql


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


class SQLiteBackend:
    dialect = "sqlite"
    backend_type = "sqlite"

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser()

    def _uri(self) -> str:
        resolved = self.database_path.resolve(strict=True)
        return f"file:{resolved.as_posix()}?mode=ro"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self._uri(),
            uri=True,
            check_same_thread=False,
        )

    def execute(
        self,
        query: str,
        *,
        timeout_seconds: float,
        max_rows: int,
    ) -> BackendExecutionResult:
        validate_readonly_sql(query, dialect=self.dialect)
        started = time.monotonic()
        deadline = started + timeout_seconds
        connection = self._connect()
        try:
            connection.set_authorizer(_readonly_authorizer)
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() >= deadline else 0,
                1_000,
            )
            cursor = connection.execute(query)
            columns = [column[0] for column in cursor.description or []]
            raw_rows = cursor.fetchmany(max_rows + 1)
            truncated = len(raw_rows) > max_rows
            rows = [
                {
                    column: normalize_result_value(value)
                    for column, value in zip(columns, raw_row, strict=True)
                }
                for raw_row in raw_rows[:max_rows]
            ]
        except sqlite3.DatabaseError as exc:
            if "interrupted" in str(exc).lower():
                raise TimeoutError(
                    f"SQL execution exceeded {timeout_seconds:g} seconds."
                ) from exc
            raise SQLExecutionError(str(exc)) from exc
        finally:
            connection.close()

        return BackendExecutionResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            elapsed_ms=(time.monotonic() - started) * 1_000,
        )

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        connection = self._connect()
        try:
            if not table_names:
                return []
            placeholders = ", ".join("?" for _ in table_names)
            rows = connection.execute(
                f"""
                SELECT name
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                  AND name COLLATE NOCASE IN ({placeholders})
                """,
                table_names,
            ).fetchall()
            available = {str(row[0]).casefold(): str(row[0]) for row in rows}
            unknown = [
                name for name in table_names if name.casefold() not in available
            ]
            if unknown:
                raise ValueError(
                    "Unknown table(s): " + ", ".join(sorted(unknown))
                )

            tables: list[TableInfo] = []
            for requested_name in table_names:
                physical_name = available[requested_name.casefold()]
                quoted_name = physical_name.replace('"', '""')
                rows = connection.execute(
                    f'PRAGMA table_info("{quoted_name}")'
                ).fetchall()
                columns = tuple(
                    ColumnInfo(
                        name=str(row[1]),
                        data_type=str(row[2] or ""),
                        nullable=not bool(row[3]),
                        primary_key=bool(row[5]),
                    )
                    for row in rows
                )
                tables.append(
                    TableInfo(name=physical_name, columns=columns)
                )
        finally:
            connection.close()
        return tables
