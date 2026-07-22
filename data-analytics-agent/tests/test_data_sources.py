from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from data_analytics_agent.agents.text_to_sql.agent import _sql_subagent_prompt
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
from data_analytics_agent.stores import ResultStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    assert disabled.enable_data_visualization is False
    prompt = _coordinator_prompt(source, visualization_enabled=False)
    assert "visualization is disabled" in prompt.lower()
    assert "do not simulate one" in prompt.lower()

    enabled_prompt = _coordinator_prompt(
        source,
        visualization_enabled=True,
    )
    assert "only when the user explicitly asks" in enabled_prompt.lower()
    assert "follow the coordinator policy in agents.md" in (
        " ".join(enabled_prompt.lower().split())
    )

    sql_prompt = _sql_subagent_prompt(source)
    normalized_sql_prompt = " ".join(sql_prompt.lower().split())
    assert "do not add `limit` unless the user explicitly requests" in (
        normalized_sql_prompt
    )
    assert "do not imply a row count" in normalized_sql_prompt

    visualization_prompt = _visualization_prompt(source)
    assert "read the `chart-design` skill" in visualization_prompt.lower()
    assert "`create_chart` and `finish_visualization` are terminal" in (
        visualization_prompt.lower()
    )


def test_sql_context_reads_are_batched_and_unique(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    normalized = " ".join(_sql_subagent_prompt(source).split())

    assert (
        "Issue these three independent reads in one tool-call batch when "
        "possible"
    ) in normalized
    assert "read each path at most once per assignment" in normalized
    assert "Re-read only if the earlier content was truncated or compacted" in (
        normalized
    )


@pytest.mark.parametrize(
    "skill_path",
    [
        "skills/text-to-sql/schema-exploration/SKILL.md",
        "skills/text-to-sql/query-writing/SKILL.md",
    ],
)
def test_sql_skills_reuse_the_loaded_osi(skill_path: str) -> None:
    content = (PROJECT_ROOT / skill_path).read_text(encoding="utf-8")
    normalized = " ".join(content.split())

    assert "OSI semantic model already loaded for the assignment" in normalized
    assert "If it is absent from context, truncated, or compacted" in normalized
    assert "runtime prompt with `limit=1000`" in normalized
    assert "Read the exact OSI" not in content


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

    prompt = _coordinator_prompt(source, visualization_enabled=True)
    normalized = " ".join(prompt.split())

    assert source.description in prompt
    assert source.semantic_virtual_path in prompt
    assert f"SQL dialect: {source.dialect}" in prompt
    assert "Challenging comparison" in prompt
    assert "Which segments changed the most over time?" in prompt
    assert (
        "Handle greetings, help, capability or architecture questions"
        in normalized
    )
    assert "requests for example questions" in normalized
    assert "do not call `task`" in normalized
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

    prompt = _coordinator_prompt(source, visualization_enabled=False)

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


def test_sparse_chart_contract_does_not_request_openai_strict_schema() -> None:
    response_format = _final_answer_response_format().to_model_kwargs()[
        "response_format"
    ]["json_schema"]
    chart_schema = response_format["schema"]["$defs"]["ChartSpec"]

    assert "strict" not in response_format
    assert "x" in chart_schema["properties"]
    assert "x" not in chart_schema["required"]
