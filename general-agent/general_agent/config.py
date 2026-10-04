"""Environment-backed application settings and readiness validation."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import SecretStr


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}.")
    return value


def _model_kwargs(name: str = "MODEL_KWARGS_JSON") -> dict[str, Any]:
    raw = os.getenv(name, "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must decode to an object.")
    return value


def _github_tokens() -> dict[str, SecretStr]:
    from general_agent.workspace import validate_corp_id

    try:
        value = json.loads(os.getenv("GITHUB_TOKENS_JSON", "{}"))
        if not isinstance(value, dict):
            raise ValueError
        result = {}
        for corp_id, token in value.items():
            validate_corp_id(corp_id)
            if not isinstance(token, str) or not token or len(token) > 1024 or any(ord(char) < 33 or ord(char) > 126 for char in token):
                raise ValueError
            result[corp_id] = SecretStr(token)
        return result
    except (ValueError, TypeError):
        raise ValueError("GITHUB_TOKENS_JSON must map corporation IDs to bounded tokens without whitespace.") from None


def _snowflake_connections() -> dict[str, Any]:
    from general_agent.coding.snowflake import SnowflakeConnection
    from general_agent.workspace import validate_corp_id

    try:
        value = json.loads(os.getenv("SNOWFLAKE_CONNECTIONS_JSON", "{}"))
        if not isinstance(value, dict) or len(value) > 20:
            raise ValueError
        return {validate_corp_id(corp): SnowflakeConnection.model_validate(record) for corp, record in value.items()}
    except (ValueError, TypeError):
        raise ValueError("SNOWFLAKE_CONNECTIONS_JSON must map at most twenty corporation IDs to explicit bounded read profiles.") from None


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
    command_timeout_seconds: int = field(
        default_factory=lambda: _positive_int("COMMAND_TIMEOUT_SECONDS", 120)
    )
    run_timeout_seconds: int = field(
        default_factory=lambda: _positive_int("RUN_TIMEOUT_SECONDS", 900)
    )
    max_command_output_bytes: int = field(
        default_factory=lambda: _positive_int("MAX_COMMAND_OUTPUT_BYTES", 100_000)
    )
    max_model_calls: int = field(
        default_factory=lambda: _positive_int("MAX_MODEL_CALLS", 32)
    )
    max_tool_calls: int = field(
        default_factory=lambda: _positive_int("MAX_TOOL_CALLS", 64)
    )
    max_task_calls: int = field(
        default_factory=lambda: _positive_int("MAX_TASK_CALLS", 12)
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
    coding_runtime: str = field(
        default_factory=lambda: os.getenv("CODING_RUNTIME", "local").strip()
    )
    coding_typescript_sdk: Path | None = field(
        default_factory=lambda: Path(os.environ["CODING_TYPESCRIPT_SDK"]).expanduser()
        if os.getenv("CODING_TYPESCRIPT_SDK", "").strip() else None
    )
    coding_image: str = field(
        default_factory=lambda: os.getenv("CODING_IMAGE", "general-agent-coding:local").strip()
    )
    coding_browser_image: str = field(
        default_factory=lambda: os.getenv("CODING_BROWSER_IMAGE", "general-agent-coding-browser:local").strip()
    )
    brave_search_api_key: SecretStr = field(
        default_factory=lambda: SecretStr(os.getenv("BRAVE_SEARCH_API_KEY", "")), repr=False
    )
    github_tokens: dict[str, SecretStr] = field(default_factory=_github_tokens, repr=False)
    inline_model_name: str = field(default_factory=lambda: os.getenv("INLINE_MODEL_NAME", "").strip())
    inline_model_kwargs: dict[str, Any] = field(default_factory=lambda: _model_kwargs("INLINE_MODEL_KWARGS_JSON"))
    snowflake_connections: dict[str, Any] = field(default_factory=_snowflake_connections, repr=False)
    coding_memory_mb: int = field(
        default_factory=lambda: _positive_int("CODING_MEMORY_MB", 1024)
    )
    coding_pids: int = field(default_factory=lambda: _positive_int("CODING_PIDS", 128))
    coding_storage_mb: int = field(
        default_factory=lambda: _positive_int("CODING_STORAGE_MB", 512)
    )
    max_repository_mb: int = field(
        default_factory=lambda: _positive_int("MAX_REPOSITORY_MB", 50)
    )
    max_repository_files: int = field(
        default_factory=lambda: _positive_int("MAX_REPOSITORY_FILES", 5000)
    )
    max_coding_workers: int = field(
        default_factory=lambda: _positive_int("MAX_CODING_WORKERS", 2)
    )
    max_corp_coding_workers: int = field(
        default_factory=lambda: _positive_int("MAX_CORP_CODING_WORKERS", 1)
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
    def coding_db(self) -> Path:
        return self.data_root / "coding.sqlite3"

    @property
    def coding_root(self) -> Path:
        return self.data_root / "coding"

    @property
    def package_root(self) -> Path:
        return self.workspace_root / ".packages"

    @property
    def temp_root(self) -> Path:
        return self.workspace_root / ".tmp"

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
            self.package_root,
            self.temp_root,
            self.workspace_root / "users",
            self.app_root,
            self.installed_skills_root,
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
            shutil.copytree(self.skills_source_root, self.installed_skills_root)

    def readiness_errors(self, *, require_model: bool = True) -> list[str]:
        errors: list[str] = []
        if require_model and not self.model_name:
            errors.append("MODEL_NAME is required.")
        if self.api_host not in {"127.0.0.1", "localhost", "::1"}:
            errors.append("API_HOST must remain loopback-only for trusted execution.")
        if self.app_host not in {"127.0.0.1", "localhost", "::1"}:
            errors.append("APP_HOST must remain loopback-only for trusted execution.")
        if not self.default_corp_id:
            errors.append("DEFAULT_CORP_ID must not be empty.")
        if self.coding_runtime not in {"local", "docker"}:
            errors.append("CODING_RUNTIME must be local or docker.")
        if self.coding_typescript_sdk is not None and not self.coding_typescript_sdk.is_absolute():
            errors.append("CODING_TYPESCRIPT_SDK must be an absolute path to lib/typescript.js.")
        if self.coding_runtime == "docker" and (not self.coding_image or any(char.isspace() for char in self.coding_image)):
            errors.append("CODING_IMAGE must be a nonempty image name without whitespace.")
        if self.coding_runtime == "docker" and (not self.coding_browser_image or any(char.isspace() for char in self.coding_browser_image)):
            errors.append("CODING_BROWSER_IMAGE must be a nonempty image name without whitespace.")
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
