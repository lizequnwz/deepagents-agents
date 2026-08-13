"""Environment-backed settings for the stateless Advisor Match service."""

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


def _model_kwargs() -> dict[str, Any]:
    raw = os.getenv("MODEL_KWARGS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MODEL_KWARGS_JSON must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("MODEL_KWARGS_JSON must decode to an object.")
    return value


def _log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"LOG_LEVEL is invalid: {value!r}.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1]
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "").strip()
    )
    model_kwargs: dict[str, Any] = field(default_factory=_model_kwargs)
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: _positive_int("API_PORT", 8001))
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    app_port: int = field(default_factory=lambda: _positive_int("APP_PORT", 8502))
    api_base_url: str = field(
        default_factory=lambda: os.getenv("API_BASE_URL", "http://127.0.0.1:8001")
    )
    log_level: str = field(default_factory=_log_level)
    max_upload_mb: int = field(
        default_factory=lambda: _positive_int("MAX_UPLOAD_MB", 50)
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
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def synthetic_reference_path(self) -> Path:
        return (
            self.project_root
            / "advisor_match/advisor_matching/data/master_advisors.csv"
        )

    def readiness_errors(self, *, require_model: bool = True) -> list[str]:
        if require_model and not self.model_name:
            return ["MODEL_NAME is required."]
        return []


def load_settings(*, require_model: bool = True) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    settings = Settings(project_root=project_root)
    errors = settings.readiness_errors(require_model=require_model)
    if errors:
        raise ValueError(" ".join(errors))
    return settings
