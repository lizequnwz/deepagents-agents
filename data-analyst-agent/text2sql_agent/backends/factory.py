"""Built-in backend construction from trusted registry entries."""

from __future__ import annotations

from pathlib import Path

from text2sql_agent.backends.base import SQLBackend
from text2sql_agent.backends.sqlite import SQLiteBackend
from text2sql_agent.data_sources import DataSource


def create_backend(source: DataSource, project_root: Path) -> SQLBackend:
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
