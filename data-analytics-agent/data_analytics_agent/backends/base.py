"""Backend-neutral SQL typed batch execution contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from collections.abc import Iterator
from threading import Event
import pyarrow as pa


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


class SQLExecutionError(RuntimeError):
    """Expected database rejection of an otherwise read-only SQL query."""


@runtime_checkable
class SQLBackend(Protocol):
    """Minimal contract required by the data analytics agent."""

    dialect: str
    backend_type: str

    def execute_batches(
        self, query: str, *, timeout_seconds: float, cancel: Event | None = None
    ) -> Iterator[pa.RecordBatch]:
        """Validate and stream typed batches; close the iterator to release resources."""

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        """Return live metadata for the requested OSI-declared tables."""
