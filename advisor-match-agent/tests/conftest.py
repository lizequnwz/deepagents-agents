from __future__ import annotations

from pathlib import Path

import pytest

from general_agent.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    configured = Settings(
        project_root=tmp_path,
        model_name="test:model",
        run_timeout_seconds=5,
        max_inspect_pages=2,
        max_inspect_sheets=2,
        max_inspect_rows=3,
        max_inspect_columns=3,
        max_inspect_chars=500,
    )
    configured.prepare_directories()
    return configured
