from typing import Any
from dataclasses import replace
import pytest
from data_analytics_agent import coordinator


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
    }


def test_harness_profile_key_tracks_the_actual_model_provider(
    test_settings,
) -> None:
    class BedrockModel:
        model_id = "us.anthropic.claude-sonnet-4-6"

        def _get_ls_params(self) -> dict[str, str]:
            return {"ls_provider": "amazon_bedrock"}

    assert (
        coordinator._model_harness_profile_key(BedrockModel(), test_settings)
        == "amazon_bedrock"
    )


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

    assert not any("OPENAI_API_KEY" in error for error in settings.readiness_errors())
