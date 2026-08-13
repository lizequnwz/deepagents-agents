from __future__ import annotations

from advisor_match.config import Settings


def test_service_hosts_are_deployment_configurable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")

    settings = Settings(project_root=tmp_path, model_name="test:model")

    assert settings.api_host == "0.0.0.0"
    assert settings.app_host == "0.0.0.0"
    assert settings.readiness_errors() == []


def test_upload_limit_exposes_exact_memory_bound(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "7")

    settings = Settings(project_root=tmp_path, model_name="test:model")

    assert settings.max_upload_bytes == 7 * 1024 * 1024


def test_default_upload_limit_is_50_mb(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    settings = Settings(project_root=tmp_path, model_name="test:model")

    assert settings.max_upload_mb == 50


def test_model_is_the_only_required_readiness_setting(tmp_path) -> None:
    assert Settings(project_root=tmp_path, model_name="").readiness_errors() == [
        "MODEL_NAME is required."
    ]
