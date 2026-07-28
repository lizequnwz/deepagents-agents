"""Application configuration and source-registry defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
)
from data_analytics_agent.data_sources import (
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return value


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
        default_factory=lambda: int(os.getenv("SQL_MAX_RESULT_ROWS", "10000"))
    )
    model_sample_rows: int = field(
        default_factory=lambda: int(os.getenv("MODEL_SAMPLE_ROWS", "10"))
    )
    enable_data_visualization: bool = field(
        default_factory=lambda: _env_bool(
            "ENABLE_DATA_VISUALIZATION",
            True,
        )
    )
    enable_statistical_analysis: bool = field(
        default_factory=lambda: _env_bool(
            "ENABLE_STATISTICAL_ANALYSIS",
            True,
        )
    )
    enable_reporting: bool = field(
        default_factory=lambda: _env_bool("ENABLE_REPORTING", True)
    )
    statistical_python_timeout_seconds: float = field(
        default_factory=lambda: _env_positive_float(
            "STATISTICAL_PYTHON_TIMEOUT_SECONDS", 30
        )
    )
    statistical_max_stdout_chars: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_STDOUT_CHARS", 10_000
        )
    )
    statistical_max_output_items: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_OUTPUT_ITEMS", 10
        )
    )
    statistical_max_output_rows: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_OUTPUT_ROWS", 50
        )
    )
    statistical_max_output_columns: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_OUTPUT_COLUMNS", 20
        )
    )
    statistical_max_output_chars: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_OUTPUT_CHARS", 50_000
        )
    )
    statistical_max_figures: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_FIGURES", 4
        )
    )
    statistical_max_figure_bytes: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_FIGURE_BYTES", 1_048_576
        )
    )
    statistical_max_total_figure_bytes: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_TOTAL_FIGURE_BYTES", 3_145_728
        )
    )
    statistical_max_figure_width: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_FIGURE_WIDTH", 1_600
        )
    )
    statistical_max_figure_height: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_FIGURE_HEIGHT", 1_200
        )
    )
    statistical_max_execution_attempts: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_MAX_EXECUTION_ATTEMPTS", 3
        )
    )
    coordinator_model_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "COORDINATOR_MODEL_CALL_LIMIT", 12
        )
    )
    coordinator_tool_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "COORDINATOR_TOOL_CALL_LIMIT", 12
        )
    )
    coordinator_task_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "COORDINATOR_TASK_CALL_LIMIT", 4
        )
    )
    sql_agent_model_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "SQL_AGENT_MODEL_CALL_LIMIT", 24
        )
    )
    sql_agent_tool_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "SQL_AGENT_TOOL_CALL_LIMIT", 30
        )
    )
    sql_execute_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "SQL_EXECUTE_CALL_LIMIT", 3
        )
    )
    visualization_agent_model_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "VISUALIZATION_AGENT_MODEL_CALL_LIMIT", 12
        )
    )
    visualization_agent_tool_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "VISUALIZATION_AGENT_TOOL_CALL_LIMIT", 16
        )
    )
    statistical_agent_model_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_AGENT_MODEL_CALL_LIMIT", 24
        )
    )
    statistical_agent_tool_call_limit: int = field(
        default_factory=lambda: _env_positive_int(
            "STATISTICAL_AGENT_TOOL_CALL_LIMIT", 24
        )
    )
    agent_debug_details: bool = field(
        default_factory=lambda: _env_bool("AGENT_DEBUG_DETAILS", False)
    )

    def load_catalog(self) -> DataSourceCatalog:
        return load_data_source_catalog(
            self.project_root,
            config_path=self.data_sources_config_path,
            default_timeout_seconds=self.sql_timeout_seconds,
            default_max_result_rows=self.max_result_rows,
            default_model_sample_rows=self.model_sample_rows,
        )

    def statistical_execution_limits(self) -> PythonExecutionLimits:
        return PythonExecutionLimits(
            timeout_seconds=self.statistical_python_timeout_seconds,
            max_stdout_chars=self.statistical_max_stdout_chars,
            max_output_items=self.statistical_max_output_items,
            max_output_rows=self.statistical_max_output_rows,
            max_output_columns=self.statistical_max_output_columns,
            max_output_chars=self.statistical_max_output_chars,
            max_figures=self.statistical_max_figures,
            max_figure_bytes=self.statistical_max_figure_bytes,
            max_total_figure_bytes=(
                self.statistical_max_total_figure_bytes
            ),
            max_figure_width=self.statistical_max_figure_width,
            max_figure_height=self.statistical_max_figure_height,
            max_execution_attempts=(
                self.statistical_max_execution_attempts
            ),
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
        if not 1 <= self.model_sample_rows <= min(self.max_result_rows, 10):
            errors.append(
                "MODEL_SAMPLE_ROWS must be between 1 and the smaller of 10 "
                "and SQL_MAX_RESULT_ROWS."
            )
        if (
            self.statistical_max_total_figure_bytes
            < self.statistical_max_figure_bytes
        ):
            errors.append(
                "STATISTICAL_MAX_TOTAL_FIGURE_BYTES must be greater than or "
                "equal to STATISTICAL_MAX_FIGURE_BYTES."
            )
        try:
            self.load_catalog()
        except Exception as exc:
            errors.append(str(exc))
        return errors
