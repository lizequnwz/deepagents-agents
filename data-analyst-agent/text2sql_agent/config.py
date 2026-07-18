"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _database_path() -> Path:
    configured = Path(os.getenv("DATABASE_PATH", "chinook.db")).expanduser()
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    project_root: Path = PROJECT_ROOT
    model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    )
    database_path: Path = field(default_factory=_database_path)
    api_base_url: str = field(
        default_factory=lambda: os.getenv(
            "API_BASE_URL", "http://127.0.0.1:8000"
        )
    )
    sql_timeout_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("SQL_TIMEOUT_SECONDS", "10")
        )
    )

    @property
    def semantic_model_path(self) -> Path:
        return self.project_root / "semantic" / "chinook.osi.yaml"

    def readiness_errors(self) -> list[str]:
        errors: list[str] = []
        if not os.getenv("OPENAI_API_KEY"):
            errors.append(
                "OPENAI_API_KEY is missing. Copy .env.example to .env and add a key."
            )
        if not self.database_path.is_file():
            errors.append(
                f"Chinook database not found at {self.database_path}. "
                "Follow the README setup command to download it."
            )
        if not self.semantic_model_path.is_file():
            errors.append(
                f"OSI semantic model not found at {self.semantic_model_path}."
            )
        return errors
