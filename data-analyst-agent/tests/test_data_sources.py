from __future__ import annotations

from text2sql_agent.api import Services
from text2sql_agent.config import Settings


def test_registry_resolves_source_semantic_target_and_limits(
    test_settings: Settings,
) -> None:
    catalog = test_settings.load_catalog()

    assert catalog.default_source_id == "test"
    assert set(catalog.sources) == {"test", "test_alt"}
    source = catalog.get("test")
    assert source.semantic_model_path.is_file()
    assert source.semantic_virtual_path == "/project/semantic/test.osi.yaml"
    assert source.backend_type == "sqlite"
    assert source.dialect == "sqlite"
    assert source.target["path"] == "db/test.sqlite"
    assert source.limits.max_result_rows == 500


def test_clear_semantic_schema_mismatch_blocks_source(
    test_settings: Settings,
) -> None:
    semantic_path = (
        test_settings.project_root / "semantic" / "test.osi.yaml"
    )
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
    (
        test_settings.project_root / "semantic" / "test.osi.yaml"
    ).unlink()

    summaries = Services(settings=test_settings).source_summaries()

    assert all(not summary.ready for summary in summaries)
    assert all(
        any("not found" in error for error in summary.errors)
        for summary in summaries
    )
