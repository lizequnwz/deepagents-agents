from __future__ import annotations

from pathlib import Path

import pytest

from data_analytics_agent.api import Services
from data_analytics_agent.config import Settings
from data_analytics_agent.semantic import (
    SemanticCatalog,
    load_semantic_catalog,
    render_semantic_overview,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _semantic_context(source) -> tuple[SemanticCatalog, str]:
    loaded = load_semantic_catalog(
        source.semantic_model_path,
        dialect=source.dialect,
    )
    assert loaded.catalog is not None
    return loaded.catalog, render_semantic_overview(loaded.catalog)


def test_registry_resolves_source_semantic_target_and_limits(
    test_settings: Settings,
) -> None:
    catalog = test_settings.load_catalog()

    assert catalog.default_source_id == "test"
    assert set(catalog.sources) == {"test", "test_alt"}
    source = catalog.get("test")
    assert source.semantic_model_path.is_file()
    assert source.semantic_model_path.name == "test.osi.yaml"
    assert source.backend_type == "sqlite"
    assert source.dialect == "sqlite"
    assert source.target["path"] == "db/test.sqlite"
    assert source.limits.max_result_rows == 10_000


def test_sql_result_limit_can_be_configured_from_env(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQL_MAX_RESULT_ROWS", "25000")
    settings = Settings(
        project_root=test_settings.project_root,
        data_sources_config_path=test_settings.data_sources_config_path,
    )

    assert settings.load_catalog().get("test").limits.max_result_rows == 25_000


def test_clear_semantic_schema_mismatch_blocks_source(
    test_settings: Settings,
) -> None:
    semantic_path = test_settings.project_root / "semantic" / "test.osi.yaml"
    semantic_path.write_text(
        semantic_path.read_text(encoding="utf-8").replace(
            "expression: Name",
            "expression: MissingColumn",
        ),
        encoding="utf-8",
    )

    summaries = Services(settings=test_settings).source_summaries()

    assert all(not summary.ready for summary in summaries)
    assert all(
        any("MissingColumn" in error for error in summary.errors)
        for summary in summaries
    )


def test_missing_osi_file_blocks_source(test_settings: Settings) -> None:
    (test_settings.project_root / "semantic" / "test.osi.yaml").unlink()

    summaries = Services(settings=test_settings).source_summaries()

    assert all(not summary.ready for summary in summaries)
    assert all(
        any("not found" in error for error in summary.errors) for summary in summaries
    )
