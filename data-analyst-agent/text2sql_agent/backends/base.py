"""Backend-neutral SQL execution contracts and value normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool = False


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]


@dataclass(frozen=True)
class BackendExecutionResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: float


@runtime_checkable
class SQLBackend(Protocol):
    """Minimal contract required by the data analytics agent."""

    dialect: str
    backend_type: str

    def readiness_errors(self) -> list[str]:
        """Return actionable errors without raising for expected setup issues."""

    def validate_sql(self, query: str) -> None:
        """Raise when the query is not one safe read-only statement."""

    def execute(
        self,
        query: str,
        *,
        timeout_seconds: float,
        max_rows: int,
    ) -> BackendExecutionResult:
        """Execute exact validated SQL and normalize the result."""

    def list_tables(self) -> list[str]:
        """List queryable tables and views."""

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        """Return normalized schema metadata for the requested tables."""


def normalize_result_value(value: Any) -> Any:
    """Convert common database-native values to stable JSON-compatible values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Path):
        return str(value)
    return str(value)
