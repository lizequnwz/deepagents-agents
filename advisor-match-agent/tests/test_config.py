from __future__ import annotations

import pytest

from general_agent.config import Settings


def test_ui_debug_mode_defaults_off_and_accepts_true(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("UI_DEBUG_MODE", raising=False)
    assert Settings(project_root=tmp_path, model_name="test:model").ui_debug_mode is False

    monkeypatch.setenv("UI_DEBUG_MODE", "true")
    assert Settings(project_root=tmp_path, model_name="test:model").ui_debug_mode is True


def test_ui_debug_mode_rejects_invalid_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("UI_DEBUG_MODE", "sometimes")
    with pytest.raises(ValueError, match="UI_DEBUG_MODE must be a boolean"):
        Settings(project_root=tmp_path, model_name="test:model")


def test_logging_defaults_and_paths(monkeypatch, tmp_path) -> None:
    for name in ("LOG_LEVEL", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(project_root=tmp_path, model_name="test:model")
    assert settings.log_level == "INFO"
    assert settings.log_max_bytes == 10 * 1024 * 1024
    assert settings.log_backup_count == 5
    assert settings.api_log == tmp_path / ".data/logs/api.log"


def test_log_level_is_validated(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        Settings(project_root=tmp_path, model_name="test:model")
