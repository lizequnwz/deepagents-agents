"""Environment-backed application settings and readiness validation."""

from __future__ import annotations

import json
import os
import shutil
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
    run_timeout_seconds: int = field(
        default_factory=lambda: _positive_int("RUN_TIMEOUT_SECONDS", 900)
    )
    max_model_calls: int = field(
        default_factory=lambda: _positive_int("MAX_MODEL_CALLS", 32)
    )
    max_tool_calls: int = field(
        default_factory=lambda: _positive_int("MAX_TOOL_CALLS", 64)
    )
    max_run_tokens: int = field(
        default_factory=lambda: _positive_int("MAX_RUN_TOKENS", 1_000_000)
    )
    max_file_read_chars: int = field(
        default_factory=lambda: _positive_int("MAX_FILE_READ_CHARS", 20_000)
    )
    max_event_output_chars: int = field(
        default_factory=lambda: _positive_int("MAX_EVENT_OUTPUT_CHARS", 12_000)
    )
    default_corp_id: str = field(
        default_factory=lambda: os.getenv("DEFAULT_CORP_ID", "A123456").strip()
        or "A123456"
    )
    max_upload_files: int = field(
        default_factory=lambda: _positive_int("MAX_UPLOAD_FILES", 10)
    )
    max_upload_mb: int = field(
        default_factory=lambda: _positive_int("MAX_UPLOAD_MB", 100)
    )
    max_inspect_pages: int = field(
        default_factory=lambda: _positive_int("MAX_INSPECT_PAGES", 20)
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
    max_inspect_chars: int = field(
        default_factory=lambda: _positive_int("MAX_INSPECT_CHARS", 50_000)
    )
    advisor_max_input_rows: int = field(
        default_factory=lambda: _positive_int("ADVISOR_MAX_INPUT_ROWS", 50_000)
    )
    advisor_max_reference_rows: int = field(
        default_factory=lambda: _positive_int("ADVISOR_MAX_REFERENCE_ROWS", 1_000_000)
    )

    @property
    def workspace_root(self) -> Path:
        return self.project_root / "workspace"

    @property
    def data_root(self) -> Path:
        return self.project_root / ".data"

    @property
    def application_db(self) -> Path:
        return self.data_root / "application.sqlite3"

    @property
    def checkpoint_db(self) -> Path:
        return self.data_root / "checkpoints.sqlite3"

    @property
    def app_root(self) -> Path:
        return self.workspace_root / ".app"

    @property
    def installed_skills_root(self) -> Path:
        return self.app_root / "skills"

    @property
    def skills_source_root(self) -> Path:
        return self.project_root / "skills"

    def prepare_directories(self) -> None:
        for path in (
            self.workspace_root,
            self.data_root,
            self.workspace_root / "users",
            self.app_root,
            self.data_root / "attachments",
            self.data_root / "artifacts",
            self.data_root / "baselines",
            self.data_root / "users",
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self.skills_source_root.exists():
            # The installed tree is derived application state. Replace it rather
            # than merging so renamed or retired skills cannot remain discoverable
            # after an upgrade.
            shutil.rmtree(self.installed_skills_root, ignore_errors=True)
            self.installed_skills_root.mkdir(parents=True, exist_ok=True)
            advisor_skill = self.skills_source_root / "advisor-match"
            if advisor_skill.is_dir():
                shutil.copytree(advisor_skill, self.installed_skills_root / "advisor-match")

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
    settings.prepare_directories()
    errors = settings.readiness_errors(require_model=require_model)
    if errors:
        raise ValueError(" ".join(errors))
    return settings
