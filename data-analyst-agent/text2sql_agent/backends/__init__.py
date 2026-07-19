"""SQL backend contracts and built-in adapters."""

from text2sql_agent.backends.base import (
    BackendExecutionResult,
    ColumnInfo,
    SQLBackend,
    TableInfo,
)
from text2sql_agent.backends.factory import create_backend
from text2sql_agent.backends.sqlite import SQLiteBackend
from text2sql_agent.backends.validation import (
    SQLValidationError,
    validate_readonly_sql,
)

__all__ = [
    "BackendExecutionResult",
    "ColumnInfo",
    "SQLBackend",
    "SQLValidationError",
    "SQLiteBackend",
    "TableInfo",
    "create_backend",
    "validate_readonly_sql",
]
