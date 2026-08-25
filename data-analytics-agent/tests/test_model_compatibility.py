from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent import coordinator
from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisResponse,
)
from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
)
from data_analytics_agent.agents.statistical_analysis.tools import (
    create_execute_statistical_python_tool,
    create_inspect_result_for_statistics_tool,
)
from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
    create_inspect_conversation_result_tool,
    create_list_conversation_results_tool,
)
from data_analytics_agent.agents.visualization.schemas import ChartSpec
from data_analytics_agent.agents.visualization.tools import (
    create_create_chart_tool,
    create_finish_visualization_tool,
    create_inspect_result_for_chart_tool,
    create_validate_chart_tool,
)
from data_analytics_agent.reporting.tools import (
    create_create_report_tool,
    create_inspect_conversation_analysis_tool,
    create_list_conversation_analyses_tool,
)
from data_analytics_agent.schemas import SQLAnalysisResponse
from data_analytics_agent.stores import (
    ReportStore,
    ResultStore,
    RunStore,
    StatisticalAnalysisStore,
)

UNSUPPORTED_BEDROCK_SCHEMA_KEYWORDS = {
    "maxItems",
    "minItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minProperties",
    "maxProperties",
}


def _unsupported_schema_paths(
    value: Any,
    *,
    path: str = "$",
    parent_key: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        if not value and parent_key != "properties":
            issues.append(f"{path} is an unconstrained schema")
        for key, nested in value.items():
            child_path = f"{path}.{key}"
            # A domain field may itself be named "minimum" or "maximum".
            if (
                parent_key != "properties"
                and key in UNSUPPORTED_BEDROCK_SCHEMA_KEYWORDS
            ):
                issues.append(child_path)
            if key == "additionalProperties" and nested is not False:
                issues.append(child_path)
            issues.extend(
                _unsupported_schema_paths(
                    nested,
                    path=child_path,
                    parent_key=key,
                )
            )
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            issues.extend(
                _unsupported_schema_paths(
                    nested,
                    path=f"{path}[{index}]",
                    parent_key=parent_key,
                )
            )
    return issues


def test_every_project_model_bound_schema_uses_bedrock_subset(
    test_settings,
) -> None:
    results = ResultStore()
    analyses = StatisticalAnalysisStore()
    runs = RunStore()
    source = test_settings.load_catalog().get("test")
    backend = object()
    tools = [
        create_execute_sql_tool(source, backend, results),
        create_list_conversation_results_tool(
            results,
            source_id=source.source_id,
        ),
        create_inspect_conversation_result_tool(
            results,
            source_id=source.source_id,
            model_sample_rows=10,
        ),
        create_inspect_result_for_statistics_tool(
            results,
            runs,
            source_id=source.source_id,
            sample_rows=10,
            maximum_attempts=2,
        ),
        create_execute_statistical_python_tool(
            results,
            runs,
            source_id=source.source_id,
            limits=PythonExecutionLimits(),
        ),
        create_inspect_result_for_chart_tool(
            results,
            source_id=source.source_id,
            sample_rows=10,
        ),
        create_validate_chart_tool(
            results,
            source_id=source.source_id,
        ),
        create_create_chart_tool(
            results,
            source_id=source.source_id,
        ),
        create_finish_visualization_tool(
            results,
            source_id=source.source_id,
        ),
        create_list_conversation_analyses_tool(
            analyses,
            source_id=source.source_id,
        ),
        create_inspect_conversation_analysis_tool(
            analyses,
            source_id=source.source_id,
        ),
        create_create_report_tool(
            results,
            analyses,
            runs,
            ReportStore(),
            source_id=source.source_id,
        ),
    ]
    schemas = {
        "coordinator": coordinator._final_answer_response_format()
        .to_model_kwargs()["response_format"]["json_schema"]["schema"],
        "sql structured output": ToolStrategy(
            SQLAnalysisResponse
        ).schema_specs[0].json_schema,
        "statistical structured output": ToolStrategy(
            StatisticalAnalysisResponse
        ).schema_specs[0].json_schema,
        **{
            tool.name: tool.tool_call_schema.model_json_schema()
            for tool in tools
        },
    }

    issues = {
        name: paths
        for name, schema in schemas.items()
        if (paths := _unsupported_schema_paths(schema))
    }

    assert issues == {}


@pytest.mark.parametrize(
    "updates",
    [
        {"result_id": ""},
        {"title": ""},
        {"title": "x" * 161},
        {"y": [f"series-{index}" for index in range(6)]},
        {"category_limit": 31},
        {"bin_count": 4},
        {"x_label": "x" * 81},
    ],
)
def test_chart_limits_remain_runtime_invariants(updates: dict[str, Any]) -> None:
    values = {
        "result_id": "result-1",
        "chart_type": "bar",
        "title": "Amount by category",
        "x": "category",
        "y": ["amount"],
    }
    values.update(updates)

    with pytest.raises(ValueError):
        ChartSpec.model_validate(values)


def test_bedrock_configuration_uses_injected_or_factory_model(
    test_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    injected = object()
    assert coordinator._build_chat_model(test_settings, injected) is injected

    settings = replace(
        test_settings,
        model_provider="bedrock_converse",
        model="us.anthropic.claude-sonnet-4-6",
    )
    built = object()
    captured: dict[str, Any] = {}

    def fake_init_chat_model(model: str, **kwargs: Any) -> object:
        captured.update(model=model, **kwargs)
        return built

    monkeypatch.setattr(coordinator, "init_chat_model", fake_init_chat_model)

    assert coordinator._build_chat_model(settings) is built
    assert captured == {
        "model": "us.anthropic.claude-sonnet-4-6",
        "model_provider": "bedrock_converse",
        "streaming": False,
        "reasoning_effort": "low",
    }


def test_harness_profile_key_tracks_the_actual_model_provider(
    test_settings,
) -> None:
    class BedrockModel:
        model_id = "us.anthropic.claude-sonnet-4-6"

        def _get_ls_params(self) -> dict[str, str]:
            return {"ls_provider": "amazon_bedrock"}

    assert coordinator._model_harness_profile_key(
        BedrockModel(), test_settings
    ) == "amazon_bedrock"


def test_bedrock_readiness_does_not_require_openai_key(
    test_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = replace(
        test_settings,
        model_provider="bedrock_converse",
        model="us.anthropic.claude-sonnet-4-6",
    )

    assert not any(
        "OPENAI_API_KEY" in error for error in settings.readiness_errors()
    )
