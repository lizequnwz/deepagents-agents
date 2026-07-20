"""Read-only Snowflake backend over an injected ``snowlib`` client."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from data_analytics_agent.backends.base import (
    BackendExecutionResult,
    ColumnInfo,
    TableInfo,
    normalize_result_value,
)
from data_analytics_agent.backends.validation import validate_readonly_sql


_METADATA_TIMEOUT_SECONDS = 10.0
_METADATA_BATCH_SIZE = 1_000
_SNOWFLAKE_QUERY_CANCELED_ERRNO = 604


class SnowflakeCursor(Protocol):
    """Cursor behavior used from ``snowlib`` query results."""

    description: Sequence[Any] | None

    def fetchmany(self, size: int) -> Sequence[Any]: ...

    def close(self) -> None: ...


class SnowflakeClient(Protocol):
    """Narrow ``snowlib`` client contract required by the adapter."""

    def run_query(
        self,
        query: str,
        *,
        timeout_seconds: float,
    ) -> SnowflakeCursor: ...


def _column_names(description: Sequence[Any] | None) -> list[str]:
    names: list[str] = []
    for column in description or ():
        name = getattr(column, "name", None)
        if name is None and isinstance(column, Sequence) and column:
            name = column[0]
        if name is None:
            raise ValueError("Snowflake cursor returned unnamed column metadata.")
        names.append(str(name))
    return names


def _mapping_value(row: Mapping[Any, Any], name: str) -> Any:
    if name in row:
        return row[name]
    folded = name.casefold()
    for key, value in row.items():
        if str(key).casefold() == folded:
            return value
    raise KeyError(name)


def _row_value(row: Any, index: int, name: str) -> Any:
    if isinstance(row, Mapping):
        return _mapping_value(row, name)
    return row[index]


def _normalized_row(columns: list[str], row: Any) -> dict[str, Any]:
    return {
        column: normalize_result_value(_row_value(row, index, column))
        for index, column in enumerate(columns)
    }


def _is_query_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or (
        getattr(exc, "errno", None) == _SNOWFLAKE_QUERY_CANCELED_ERRNO
    )


def _provider_error_message(exc: Exception) -> str:
    code = getattr(exc, "errno", None)
    message = getattr(exc, "msg", None) or str(exc)
    return f"[{code}] {message}" if code is not None else str(message)


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class SnowflakeBackend:
    """Implement ``SQLBackend`` using one long-lived ``snowlib`` client."""

    dialect = "snowflake"
    backend_type = "snowflake"

    def __init__(self, client: SnowflakeClient) -> None:
        self.client = client

    def _fetch_all_metadata(self, query: str) -> tuple[list[str], list[Any]]:
        cursor: SnowflakeCursor | None = None
        try:
            cursor = self.client.run_query(
                query,
                timeout_seconds=_METADATA_TIMEOUT_SECONDS,
            )
            columns = _column_names(cursor.description)
            rows: list[Any] = []
            while True:
                batch = list(cursor.fetchmany(_METADATA_BATCH_SIZE))
                if not batch:
                    break
                rows.extend(batch)
            return columns, rows
        except Exception as exc:
            if _is_query_timeout(exc):
                raise TimeoutError(
                    "Snowflake metadata query exceeded 10 seconds."
                ) from exc
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def readiness_errors(self) -> list[str]:
        query = """
            SELECT
                CURRENT_ROLE() AS ROLE_NAME,
                CURRENT_DATABASE() AS DATABASE_NAME,
                CURRENT_SCHEMA() AS SCHEMA_NAME
        """
        try:
            columns, rows = self._fetch_all_metadata(query)
        except Exception as exc:
            return [
                "Snowflake is not ready: " + _provider_error_message(exc)
            ]
        if not rows:
            return ["Snowflake readiness query returned no context."]

        context = {
            column: _row_value(rows[0], index, column)
            for index, column in enumerate(columns)
        }
        missing = [
            label
            for label, column in (
                ("role", "ROLE_NAME"),
                ("database", "DATABASE_NAME"),
                ("schema", "SCHEMA_NAME"),
            )
            if not context.get(column)
        ]
        if missing:
            return [
                "Snowflake has no active " + ", ".join(missing) + "."
            ]
        return []

    def validate_sql(self, query: str) -> None:
        validate_readonly_sql(query, dialect=self.dialect)

    def execute(
        self,
        query: str,
        *,
        timeout_seconds: float,
        max_rows: int,
    ) -> BackendExecutionResult:
        self.validate_sql(query)
        started = time.monotonic()
        cursor: SnowflakeCursor | None = None
        try:
            cursor = self.client.run_query(
                query,
                timeout_seconds=timeout_seconds,
            )
            columns = _column_names(cursor.description)
            raw_rows = list(cursor.fetchmany(max_rows + 1))
            truncated = len(raw_rows) > max_rows
            rows = [
                _normalized_row(columns, row)
                for row in raw_rows[:max_rows]
            ]
        except Exception as exc:
            if _is_query_timeout(exc):
                raise TimeoutError(
                    f"SQL execution exceeded {timeout_seconds:g} seconds."
                ) from exc
            raise
        finally:
            if cursor is not None:
                cursor.close()

        return BackendExecutionResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            elapsed_ms=(time.monotonic() - started) * 1_000,
        )

    def list_tables(self) -> list[str]:
        query = """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
              AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY TABLE_NAME
        """
        columns, rows = self._fetch_all_metadata(query)
        if not columns:
            return []
        return [str(_row_value(row, 0, columns[0])) for row in rows]

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        available = {name.casefold(): name for name in self.list_tables()}
        unknown = [
            name for name in table_names if name.casefold() not in available
        ]
        if unknown:
            raise ValueError(
                "Unknown table(s): " + ", ".join(sorted(unknown))
            )
        if not table_names:
            return []

        physical_names = [available[name.casefold()] for name in table_names]
        literals = ", ".join(
            _sql_string_literal(name) for name in physical_names
        )
        query = f"""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
              AND TABLE_NAME IN ({literals})
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        columns, rows = self._fetch_all_metadata(query)
        positions = {name: index for index, name in enumerate(columns)}
        by_table: dict[str, list[ColumnInfo]] = {
            name: [] for name in physical_names
        }
        table_lookup = {name.casefold(): name for name in physical_names}
        for row in rows:
            raw_table = str(
                _row_value(row, positions["TABLE_NAME"], "TABLE_NAME")
            )
            physical_name = table_lookup.get(raw_table.casefold())
            if physical_name is None:
                continue
            nullable = str(
                _row_value(
                    row,
                    positions["IS_NULLABLE"],
                    "IS_NULLABLE",
                )
            ).upper()
            by_table[physical_name].append(
                ColumnInfo(
                    name=str(
                        _row_value(
                            row,
                            positions["COLUMN_NAME"],
                            "COLUMN_NAME",
                        )
                    ),
                    data_type=str(
                        _row_value(
                            row,
                            positions["DATA_TYPE"],
                            "DATA_TYPE",
                        )
                    ),
                    nullable=nullable == "YES",
                )
            )

        return [
            TableInfo(name=name, columns=tuple(by_table[name]))
            for name in physical_names
        ]
