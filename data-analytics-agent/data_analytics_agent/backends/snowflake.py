"""Read-only Snowflake backend over an injected ``snowlib`` client."""

from __future__ import annotations

import pyarrow as pa
from datetime import datetime
from threading import Event
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from sqlglot import exp, parse_one
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from data_analytics_agent.backends.base import (
    ColumnInfo,
    SQLExecutionError,
    TableInfo,
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


def _metadata_value(column: Any, attribute: str, index: int) -> Any:
    value = getattr(column, attribute, None)
    if value is None and isinstance(column, Sequence) and len(column) > index:
        value = column[index]
    return value


def _result_schema(description: Sequence[Any] | None) -> pa.Schema:
    """Use documented connector metadata, never observed rows, to fix batch types.

    https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api#type-codes
    NUMBER stays decimal, including scale zero and values beyond int64. Native
    fetchmany datetimes have microsecond precision; timezone-aware timestamps
    normalize to UTC without changing their instants. The original Snowflake
    temporal type remains in field metadata. Semi-structured connector values
    use their JSON text representation rather than inferred Arrow structures.
    """
    if not description:
        raise ValueError("Snowflake SELECT returned no result column metadata.")
    fields = []
    types = {
        1: pa.float64(),
        2: pa.string(),
        3: pa.date32(),
        4: pa.timestamp("us", tz="UTC"),
        5: pa.string(),
        6: pa.timestamp("us", tz="UTC"),
        7: pa.timestamp("us", tz="UTC"),
        8: pa.timestamp("us"),
        9: pa.string(),
        10: pa.string(),
        11: pa.binary(),
        12: pa.time64("us"),
        13: pa.bool_(),
        14: pa.string(),
        15: pa.string(),
    }
    for name, column in zip(_column_names(description), description, strict=True):
        code = _metadata_value(column, "type_code", 1)
        if code is None:
            raise ValueError(f"Snowflake column {name!r} has no type metadata.")
        if code == 0:
            precision = _metadata_value(column, "precision", 4)
            scale = _metadata_value(column, "scale", 5)
            if not isinstance(precision, int) or not isinstance(scale, int):
                raise ValueError(
                    f"Snowflake NUMBER column {name!r} needs precision and scale metadata."
                )
            if not (1 <= precision <= 38 and 0 <= scale <= precision):
                raise ValueError(
                    f"Invalid Snowflake NUMBER precision/scale for {name!r}."
                )
            arrow_type = pa.decimal128(precision, scale)
        elif code in types:
            arrow_type = types[code]
        else:
            raise ValueError(
                f"Unsupported Snowflake type code {code!r} for {name!r}; project a supported scalar type explicitly."
            )
        nullable = _metadata_value(column, "is_nullable", 6)
        fields.append(
            pa.field(
                name,
                arrow_type,
                nullable=True if nullable is None else bool(nullable),
                metadata={b"snowflake_type_code": str(code).encode()},
            )
        )
    return pa.schema(fields)


def _typed_array(values: list[Any], field: pa.Field) -> pa.Array:
    if pa.types.is_timestamp(field.type):
        aware = field.type.tz is not None
        for value in values:
            if (
                value is not None
                and isinstance(value, datetime)
                and (value.utcoffset() is not None) != aware
            ):
                raise ValueError(
                    f"Timestamp timezone for {field.name!r} disagrees with declared Snowflake metadata."
                )
    return pa.array(values, type=field.type)


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

    def execute_batches(
        self, query: str, *, timeout_seconds: float, cancel: Event | None = None
    ):
        validate_readonly_sql(query, dialect=self.dialect)
        cursor = None
        try:
            cursor = self.client.run_query(query, timeout_seconds=timeout_seconds)
            schema = _result_schema(cursor.description)
            emitted = False
            while True:
                if cancel and cancel.is_set():
                    raise InterruptedError("SQL stopped.")
                rows = list(cursor.fetchmany(8192))
                if not rows:
                    break
                emitted = True
                yield pa.RecordBatch.from_arrays(
                    [
                        _typed_array(
                            [_row_value(row, index, field.name) for row in rows], field
                        )
                        for index, field in enumerate(schema)
                    ],
                    schema=schema,
                )
            if not emitted:
                yield pa.RecordBatch.from_arrays(
                    [pa.array([], type=field.type) for field in schema], schema=schema
                )
        except InterruptedError:
            raise
        except Exception as exc:
            if _is_query_timeout(exc):
                raise TimeoutError(
                    f"SQL execution exceeded {timeout_seconds:g} seconds."
                ) from exc
            raise SQLExecutionError(_provider_error_message(exc)) from exc
        finally:
            if cursor is not None:
                cursor.close()

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        if not table_names:
            return []
        # Resolve only configured source identities; never enumerate other schemas.
        requested = []
        by_scope = {}
        for name in table_names:
            table = normalize_identifiers(
                parse_one(name, read=self.dialect, into=exp.Table), dialect=self.dialect
            )
            if not all(
                isinstance(part, exp.Identifier) and part.name for part in table.parts
            ) or (
                table.args.get("catalog")
                and not isinstance(table.args.get("db"), exp.Identifier)
            ):
                raise ValueError(
                    "Use a table, schema.table or database.schema.table identity with explicit identifiers."
                )
            requested.append((name, table))
            by_scope.setdefault((table.catalog or None, table.db or None), []).append(
                (name, table)
            )
        found: dict[str, list[ColumnInfo]] = {}
        for (database, schema), entries in by_scope.items():
            metadata_table = exp.Table(
                this=exp.to_identifier("COLUMNS"),
                db=exp.to_identifier("INFORMATION_SCHEMA"),
                catalog=exp.to_identifier(database, quoted=True) if database else None,
            )
            schema_sql = _sql_string_literal(schema) if schema else "CURRENT_SCHEMA()"
            names_sql = ", ".join(
                _sql_string_literal(table.name) for _, table in entries
            )
            query = f"""
                SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM {metadata_table.sql(dialect=self.dialect)}
                WHERE TABLE_SCHEMA = {schema_sql} AND TABLE_NAME IN ({names_sql})
                ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
            columns, rows = self._fetch_all_metadata(query)
            positions = {name: index for index, name in enumerate(columns)}
            for row in rows:
                values = {
                    key: _row_value(row, positions[key], key) for key in positions
                }
                for original, table in entries:
                    if (
                        values["TABLE_NAME"] != table.name
                        or (table.db and values["TABLE_SCHEMA"] != table.db)
                        or (table.catalog and values["TABLE_CATALOG"] != table.catalog)
                    ):
                        continue
                    found.setdefault(original, []).append(
                        ColumnInfo(
                            name=str(values["COLUMN_NAME"]),
                            data_type=str(values["DATA_TYPE"]),
                            nullable=str(values["IS_NULLABLE"]).upper() == "YES",
                        )
                    )
        unknown = [name for name in table_names if name not in found]
        if unknown:
            raise ValueError("Unknown table(s): " + ", ".join(sorted(unknown)))
        return [
            TableInfo(name=table.sql(dialect=self.dialect), columns=tuple(found[name]))
            for name, table in requested
        ]
