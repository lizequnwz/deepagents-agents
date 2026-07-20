"""Built-in backend construction from trusted registry entries."""

from __future__ import annotations

from pathlib import Path

from data_analytics_agent.backends.base import SQLBackend
from data_analytics_agent.backends.snowflake import (
    SnowflakeBackend,
    SnowflakeClient,
)
from data_analytics_agent.backends.sqlite import SQLiteBackend
from data_analytics_agent.data_sources import DataSource


def create_backend(
    source: DataSource,
    project_root: Path,
    *,
    snowflake_client: SnowflakeClient | None = None,
) -> SQLBackend:
    """Create one source-bound backend using a registered backend type."""

    if source.backend_type == "sqlite":
        raw_path = source.target.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(
                f"SQLite source {source.source_id!r} requires target.path."
            )
        configured = Path(raw_path).expanduser()
        database_path = (
            configured
            if configured.is_absolute()
            else project_root / configured
        )
        backend = SQLiteBackend(database_path)
    elif source.backend_type == "snowflake":
        if source.target:
            raise ValueError(
                f"Snowflake source {source.source_id!r} must use the default "
                "snowlib context and declare an empty target."
            )
        if snowflake_client is None:
            raise ValueError(
                f"Snowflake source {source.source_id!r} requires a snowlib "
                "client."
            )
        backend = SnowflakeBackend(snowflake_client)
    else:
        raise ValueError(
            f"Unsupported backend type {source.backend_type!r} for source "
            f"{source.source_id!r}."
        )

    if backend.dialect != source.dialect:
        raise ValueError(
            f"Source {source.source_id!r} declares dialect "
            f"{source.dialect!r}, but backend {source.backend_type!r} uses "
            f"{backend.dialect!r}."
        )
    return backend
