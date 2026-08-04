"""Environment-backed application settings and readiness validation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}.")


def _log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"LOG_LEVEL must be one of {choices}, got {value!r}.")
    return value


def _model_kwargs() -> dict[str, Any]:
    raw = os.getenv("MODEL_KWARGS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MODEL_KWARGS_JSON must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("MODEL_KWARGS_JSON must decode to an object.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated configuration for the API, agent, and UI client."""

    project_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1]
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "").strip()
    )
    model_kwargs: dict[str, Any] = field(default_factory=_model_kwargs)
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: _positive_int("API_PORT", 8001))
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: _positive_int("APP_PORT", 8502))
    ui_debug_mode: bool = field(
        default_factory=lambda: _boolean("UI_DEBUG_MODE", False)
    )
    log_level: str = field(default_factory=_log_level)
    log_max_bytes: int = field(
        default_factory=lambda: _positive_int("LOG_MAX_BYTES", 10 * 1024 * 1024)
    )
    log_backup_count: int = field(
        default_factory=lambda: _positive_int("LOG_BACKUP_COUNT", 5)
    )
    run_timeout_seconds: int = field(
        default_factory=lambda: _positive_int("RUN_TIMEOUT_SECONDS", 900)
    )
    default_corp_id: str = field(
        default_factory=lambda: os.getenv("DEFAULT_CORP_ID", "A123456").strip()
        or "A123456"
    )
    max_upload_mb: int = field(
        default_factory=lambda: _positive_int("MAX_UPLOAD_MB", 100)
    )
    max_inspect_sheets: int = field(
        default_factory=lambda: _positive_int("MAX_INSPECT_SHEETS", 20)
    )
    max_inspect_rows: int = field(
        default_factory=lambda: _positive_int("MAX_INSPECT_ROWS", 50)
    )
    max_inspect_columns: int = field(
        default_factory=lambda: _positive_int("MAX_INSPECT_COLUMNS", 20)
    )
    advisor_max_input_rows: int = field(
        default_factory=lambda: _positive_int("ADVISOR_MAX_INPUT_ROWS", 50_000)
    )
    advisor_max_reference_rows: int = field(
        default_factory=lambda: _positive_int("ADVISOR_MAX_REFERENCE_ROWS", 1_000_000)
    )

    @property
    def data_root(self) -> Path:
        return self.project_root / ".data"

    @property
    def advisor_repository_db(self) -> Path:
        return self.data_root / "advisor_repository.sqlite3"

    @property
    def logs_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def api_log(self) -> Path:
        return self.logs_root / "api.log"

    def prepare_directories(self) -> None:
        for path in (
            self.data_root,
            self.logs_root,
            self.data_root / "users",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def readiness_errors(self, *, require_model: bool = True) -> list[str]:
        errors: list[str] = []
        if require_model and not self.model_name:
            errors.append("MODEL_NAME is required.")
        if self.api_host not in {"127.0.0.1", "localhost", "::1"}:
            errors.append("API_HOST must remain loopback-only for sensitive advisor data.")
        if self.app_host not in {"127.0.0.1", "localhost", "::1"}:
            errors.append("APP_HOST must remain loopback-only for sensitive advisor data.")
        if not self.default_corp_id:
            errors.append("DEFAULT_CORP_ID must not be empty.")
        return errors


def load_settings(*, require_model: bool = True) -> Settings:
    """Load `.env`, prepare local directories, and validate settings."""

    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    settings = Settings(project_root=project_root)
    errors = settings.readiness_errors(require_model=require_model)
    if errors:
        raise ValueError(" ".join(errors))
    settings.prepare_directories()
    return settings
