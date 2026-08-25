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


class SQLExecutionError(RuntimeError):
    """Expected database rejection of an otherwise read-only SQL query."""


@runtime_checkable
class SQLBackend(Protocol):
    """Minimal contract required by the data analytics agent."""

    dialect: str
    backend_type: str

    def execute(
        self,
        query: str,
        *,
        timeout_seconds: float,
        max_rows: int,
    ) -> BackendExecutionResult:
        """Validate and execute exact SQL or raise an execution error."""

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        """Return live metadata for the requested OSI-declared tables."""


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
