"""Application configuration and source-registry defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from text2sql_agent.data_sources import (
    DataSourceCatalog,
    load_data_source_catalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _data_sources_config_path() -> Path:
    configured = Path(
        os.getenv("DATA_SOURCES_CONFIG", "data_sources.yaml")
    ).expanduser()
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    project_root: Path = PROJECT_ROOT
    model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    )
    data_sources_config_path: Path = field(
        default_factory=_data_sources_config_path
    )
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
    max_result_rows: int = field(
        default_factory=lambda: int(os.getenv("SQL_MAX_RESULT_ROWS", "500"))
    )
    model_sample_rows: int = field(
        default_factory=lambda: int(os.getenv("MODEL_SAMPLE_ROWS", "10"))
    )

    def load_catalog(self) -> DataSourceCatalog:
        return load_data_source_catalog(
            self.project_root,
            config_path=self.data_sources_config_path,
            default_timeout_seconds=self.sql_timeout_seconds,
            default_max_result_rows=self.max_result_rows,
            default_model_sample_rows=self.model_sample_rows,
        )

    def readiness_errors(self) -> list[str]:
        errors: list[str] = []
        if not os.getenv("OPENAI_API_KEY"):
            errors.append(
                "OPENAI_API_KEY is missing. Copy .env.example to .env and add a key."
            )
        if self.sql_timeout_seconds <= 0:
            errors.append("SQL_TIMEOUT_SECONDS must be greater than zero.")
        if not 1 <= self.max_result_rows <= 10_000:
            errors.append(
                "SQL_MAX_RESULT_ROWS must be between 1 and 10000."
            )
        if not 1 <= self.model_sample_rows <= self.max_result_rows:
            errors.append(
                "MODEL_SAMPLE_ROWS must be between 1 and "
                "SQL_MAX_RESULT_ROWS."
            )
        try:
            self.load_catalog()
        except Exception as exc:
            errors.append(str(exc))
        return errors
