"""SQL backend contracts and built-in adapters."""

from data_analytics_agent.backends.base import (
    ColumnInfo,
    SQLBackend,
    SQLExecutionError,
    TableInfo,
)
from data_analytics_agent.backends.factory import create_backend
from data_analytics_agent.backends.snowflake import (
    SnowflakeBackend,
    SnowflakeClient,
    SnowflakeCursor,
)
from data_analytics_agent.backends.sqlite import SQLiteBackend
from data_analytics_agent.backends.validation import (
    SQLValidationError,
    validate_readonly_sql,
)

__all__ = [
    "ColumnInfo",
    "SQLBackend",
    "SQLExecutionError",
    "SQLValidationError",
    "SnowflakeBackend",
    "SnowflakeClient",
    "SnowflakeCursor",
    "SQLiteBackend",
    "TableInfo",
    "create_backend",
    "validate_readonly_sql",
]
