from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from data_analytics_agent.agents.text_to_sql.agent import (
    _sql_subagent_prompt,
    build_text_to_sql_subagent,
)
from data_analytics_agent.agents.visualization.agent import (
    _visualization_prompt,
    build_visualization_subagent,
)
from data_analytics_agent.api import Services
from data_analytics_agent.config import Settings
from data_analytics_agent.coordinator import (
    _coordinator_prompt,
    _final_answer_response_format,
)
from data_analytics_agent.data_sources import ExampleQuestion
from data_analytics_agent.semantic import (
    SemanticCatalog,
    load_semantic_catalog,
    render_semantic_overview,
)
from data_analytics_agent.stores import ResultStore


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


def test_visualization_feature_flag_is_global_and_defaults_enabled(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert test_settings.enable_data_visualization is True

    monkeypatch.setenv("ENABLE_DATA_VISUALIZATION", "false")
    disabled = Settings(
        project_root=test_settings.project_root,
        data_sources_config_path=test_settings.data_sources_config_path,
    )
    source = disabled.load_catalog().get("test")
    _, overview = _semantic_context(source)

    assert disabled.enable_data_visualization is False
    prompt = _coordinator_prompt(
        source, overview, visualization_enabled=False
    )
    assert "visualization is disabled" in prompt.lower()
    assert "do not simulate one" in prompt.lower()

    enabled_prompt = _coordinator_prompt(
        source,
        overview,
        visualization_enabled=True,
    )
    normalized_enabled_prompt = " ".join(enabled_prompt.lower().split())
    assert "automatically attempt one useful chart" in normalized_enabled_prompt
    assert "follow the coordinator policy in agents.md" in (
        " ".join(enabled_prompt.lower().split())
    )

    sql_prompt = _sql_subagent_prompt(
        source, overview, require_approval=True
    )
    normalized_sql_prompt = " ".join(sql_prompt.lower().split())
    assert "do not add `limit` unless the user explicitly requests" in (
        normalized_sql_prompt
    )
    assert "do not imply a row count" in normalized_sql_prompt
    assert "saved result ids are opaque application evidence handles" in (
        normalized_sql_prompt
    )
    assert "write fresh source sql" in normalized_sql_prompt
    assert "if it returns an error observation" in (
        normalized_sql_prompt
    )

    visualization_prompt = _visualization_prompt(source)
    normalized_visualization = " ".join(
        visualization_prompt.lower().split()
    )
    assert "read the `chart-design` skill" in normalized_visualization
    assert "prefer line or area for temporal trends" in (
        normalized_visualization
    )
    assert "bar for categorical comparisons" in normalized_visualization
    assert "scalar-only" in normalized_visualization
    assert "`create_chart` and `finish_visualization` are terminal" in (
        normalized_visualization
    )
    assert "do not chart intermediate investigation results" in (
        normalized_enabled_prompt
    )
    assert "it is not a table that sql can query" in (
        normalized_enabled_prompt
    )
    assert "explicit report turns use charts inside `reportspec`" in (
        normalized_enabled_prompt
    )
    assert "keep the successful top-level chart" in normalized_enabled_prompt
    assert "after every successful data-bearing analysis" in (
        normalized_enabled_prompt
    )
    assert "compact automatic-report default" in normalized_enabled_prompt
    assert "any answer with no final evidence" in normalized_enabled_prompt


def test_text_to_sql_exposes_semantic_discovery_and_execution(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    semantic_catalog, _ = _semantic_context(source)
    subagent = build_text_to_sql_subagent(
        source=source,
        semantic_catalog=semantic_catalog,
        backend=object(),
        result_store=ResultStore(),
        model=object(),
        permissions=[],
        require_approval=False,
    )

    assert [tool.name for tool in subagent["tools"]] == [
        "search_semantic_model",
        "get_semantic_entities",
        "get_relationships",
        "execute_sql",
    ]


def test_reporting_feature_flag_controls_automatic_reports(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = test_settings.load_catalog().get("test")
    _, overview = _semantic_context(source)
    enabled = _coordinator_prompt(
        source,
        overview,
        visualization_enabled=True,
        reporting_enabled=True,
    )
    normalized = " ".join(enabled.lower().split())

    assert "create one downloadable html report" in normalized
    assert "after final evidence, statistics" in normalized
    assert "skip the ordinary top-level visualization" in normalized

    monkeypatch.setenv("ENABLE_REPORTING", "false")
    disabled = Settings(
        project_root=test_settings.project_root,
        data_sources_config_path=test_settings.data_sources_config_path,
    )
    prompt = _coordinator_prompt(
        source,
        overview,
        visualization_enabled=True,
        reporting_enabled=disabled.enable_reporting,
    )

    assert disabled.enable_reporting is False
    assert "reporting is disabled" in prompt.lower()
    assert "complete data answers without calling `create_report`" in (
        " ".join(prompt.lower().split())
    )


def test_statistical_feature_flag_defaults_enabled_and_can_be_disabled(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = test_settings.load_catalog().get("test")
    _, overview = _semantic_context(source)
    assert test_settings.enable_statistical_analysis is True
    enabled = _coordinator_prompt(
        source,
        overview,
        visualization_enabled=True,
        statistical_analysis_enabled=True,
    )
    normalized_enabled = " ".join(enabled.lower().split())
    assert "uncertainty or modeling materially improves" in normalized_enabled
    assert "descriptive trend" in normalized_enabled
    assert "does not need statistical python" in normalized_enabled
    assert "at most once in a user turn" in normalized_enabled
    assert "do not make a second delegation after" in normalized_enabled
    assert "exactly one recovery cycle" in normalized_enabled
    assert "do not reconstruct those artifacts" in normalized_enabled
    assert "application resolves exact sql and metadata" in normalized_enabled
    assert "direct analysis: use one text-to-sql assignment" in (
        normalized_enabled
    )
    assert "investigation:" in normalized_enabled
    assert "use `write_todos`" in normalized_enabled
    assert "never issue more than one `task` call" in normalized_enabled
    assert "reconcile totals, populations, filters" in normalized_enabled
    assert "result ids are opaque application artifacts" in normalized_enabled
    assert "every new sql assignment must restate" in normalized_enabled
    assert (
        "do not reinterpret a categorical predictor versus numeric outcome"
        in normalized_enabled
    )

    monkeypatch.setenv("ENABLE_STATISTICAL_ANALYSIS", "false")
    disabled = Settings(
        project_root=test_settings.project_root,
        data_sources_config_path=test_settings.data_sources_config_path,
    )
    prompt = _coordinator_prompt(
        source,
        overview,
        visualization_enabled=True,
        statistical_analysis_enabled=disabled.enable_statistical_analysis,
    )
    assert disabled.enable_statistical_analysis is False
    assert "statistical analysis is disabled" in prompt.lower()
    assert "do not simulate execution" in " ".join(prompt.lower().split())


def test_sql_prompt_uses_semantic_tools_without_raw_file_reads(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    _, overview = _semantic_context(source)
    normalized = " ".join(
        _sql_subagent_prompt(
            source, overview, require_approval=True
        ).split()
    )

    assert "read the `query-writing` skill" in normalized
    assert "`search_semantic_model`" in normalized
    assert "`get_semantic_entities`" in normalized
    assert "`get_relationships`" in normalized
    assert "read the OSI file" not in normalized
    assert "/project/semantic/" not in normalized


def test_sql_skill_uses_semantic_discovery_for_schema_grounding() -> None:
    skill_root = PROJECT_ROOT / "skills/text-to-sql"
    content = (skill_root / "query-writing/SKILL.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(content.split())

    assert sorted(
        path.name for path in skill_root.iterdir() if path.is_dir()
    ) == ["query-writing"]
    assert "`search_semantic_model`" in normalized
    assert "`get_semantic_entities`" in normalized
    assert "`get_relationships`" in normalized
    assert "runtime OSI path" not in normalized
    assert "raw semantic" not in normalized
    assert "relevant logical datasets and fields" in normalized
    assert "physical sources and selected dialect expressions" in normalized
    assert "declared path and join fields" in normalized
    assert "requested business grain" in normalized
    assert "distinguish physical source or expression names" in normalized


def test_coordinator_owns_help_and_question_brainstorming(
    test_settings: Settings,
) -> None:
    source = replace(
        test_settings.load_catalog().get("test"),
        examples=(
            ExampleQuestion(
                label="Challenging comparison",
                question="Which segments changed the most over time?",
            ),
        ),
    )
    _, overview = _semantic_context(source)

    prompt = _coordinator_prompt(
        source, overview, visualization_enabled=True
    )
    normalized = " ".join(prompt.split())

    assert source.description in prompt
    assert "Model: test_model" in prompt
    assert f"SQL dialect: {source.dialect}" in prompt
    assert "Challenging comparison" in prompt
    assert "Which segments changed the most over time?" in prompt
    assert (
        "Handle greetings, help, capability or architecture questions"
        in normalized
    )
    assert "requests for example questions" in normalized
    assert "do not call `task`" in normalized
    assert "Own metadata-only Research directly" in normalized
    assert "supported opportunities" in normalized
    assert "Do not call `task`, execute SQL" in normalized
    assert (
        "A request about what could be analyzed is not itself a request"
        in normalized
    )
    assert (
        "Delegate to `text-to-sql` only when the user asks to retrieve"
        in normalized
    )


def test_coordinator_handles_sources_without_curated_examples(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    _, overview = _semantic_context(source)

    prompt = _coordinator_prompt(
        source, overview, visualization_enabled=False
    )

    assert "No curated example questions are configured." in prompt


def test_visualization_subagent_reuses_the_configured_model(
    test_settings: Settings,
) -> None:
    model = object()
    source = test_settings.load_catalog().get("test")

    subagent = build_visualization_subagent(
        source=source,
        result_store=ResultStore(),
        model=model,
        permissions=[],
    )

    assert subagent["model"] is model
    assert subagent["name"] == "data-visualization"
    assert subagent["skills"] == [
        "/project/skills/data-visualization/"
    ]
    assert "interrupt_on" not in subagent


def test_coordinator_uses_small_non_strict_provider_schema() -> None:
    response_format = _final_answer_response_format().to_model_kwargs()[
        "response_format"
    ]["json_schema"]

    assert "strict" not in response_format
    assert "$defs" not in response_format["schema"]
    assert set(response_format["schema"]["properties"]) == {
        "answer",
        "primary_result_id",
        "supporting_result_ids",
        "assumptions",
        "interpretation",
    }
