from __future__ import annotations

from pathlib import Path

import pytest

from advisor_match.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    configured = Settings(
        project_root=tmp_path,
        model_name="test:model",
        max_inspect_sheets=2,
        max_inspect_rows=3,
        max_inspect_columns=3,
    )
    return configured
