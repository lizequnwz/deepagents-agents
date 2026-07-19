"""Validated data-source registry and resolved runtime source definitions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExampleQuestionConfig(RegistryModel):
    label: str
    question: str


class ExecutionLimitOverrides(RegistryModel):
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_result_rows: int | None = Field(default=None, ge=1, le=10_000)
    model_sample_rows: int | None = Field(default=None, ge=1, le=10)


class BackendDefinition(RegistryModel):
    type: str
    options: dict[str, Any] = Field(default_factory=dict)


class SourceDefinition(RegistryModel):
    name: str
    description: str
    backend: str
    semantic_model: str
    dialect: str
    target: dict[str, Any] = Field(default_factory=dict)
    examples: list[ExampleQuestionConfig] = Field(default_factory=list)
    limits: ExecutionLimitOverrides = Field(
        default_factory=ExecutionLimitOverrides
    )


class RegistryDocument(RegistryModel):
    version: int = 1
    default_source: str
    backends: dict[str, BackendDefinition]
    sources: dict[str, SourceDefinition]


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float
    max_result_rows: int
    model_sample_rows: int


@dataclass(frozen=True)
class ExampleQuestion:
    label: str
    question: str


@dataclass(frozen=True)
class DataSource:
    source_id: str
    name: str
    description: str
    backend_id: str
    backend_type: str
    backend_options: dict[str, Any]
    semantic_model_path: Path
    semantic_virtual_path: str
    dialect: str
    target: dict[str, Any]
    examples: tuple[ExampleQuestion, ...]
    limits: ExecutionLimits


@dataclass(frozen=True)
class DataSourceCatalog:
    config_path: Path
    default_source_id: str
    sources: dict[str, DataSource]

    def get(self, source_id: str) -> DataSource:
        try:
            return self.sources[source_id]
        except KeyError as exc:
            raise KeyError(f"Unknown data source {source_id!r}.") from exc


def _configured_registry_path(project_root: Path) -> Path:
    raw_path = Path(os.getenv("DATA_SOURCES_CONFIG", "data_sources.yaml"))
    return raw_path if raw_path.is_absolute() else project_root / raw_path


def _resolve_semantic_path(project_root: Path, raw_path: str) -> Path:
    configured = Path(raw_path).expanduser()
    resolved = (
        configured if configured.is_absolute() else project_root / configured
    ).resolve()
    semantic_root = (project_root / "semantic").resolve()
    try:
        resolved.relative_to(semantic_root)
    except ValueError as exc:
        raise ValueError(
            f"Semantic model {raw_path!r} must be inside {semantic_root}."
        ) from exc
    return resolved


def load_data_source_catalog(
    project_root: Path,
    *,
    config_path: Path | None = None,
    default_timeout_seconds: float = 10,
    default_max_result_rows: int = 500,
    default_model_sample_rows: int = 10,
) -> DataSourceCatalog:
    """Load and resolve the trusted source registry."""

    registry_path = (
        config_path or _configured_registry_path(project_root)
    ).expanduser()
    if not registry_path.is_absolute():
        registry_path = project_root / registry_path
    registry_path = registry_path.resolve()
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Data-source registry not found at {registry_path}."
        )

    raw_document = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    document = RegistryDocument.model_validate(raw_document)
    if document.version != 1:
        raise ValueError(
            f"Unsupported data-source registry version {document.version}."
        )
    if not document.sources:
        raise ValueError("The data-source registry contains no sources.")
    if document.default_source not in document.sources:
        raise ValueError(
            f"Default source {document.default_source!r} is not registered."
        )

    resolved_sources: dict[str, DataSource] = {}
    for source_id, definition in document.sources.items():
        if not source_id.strip():
            raise ValueError("Data-source IDs cannot be empty.")
        try:
            backend = document.backends[definition.backend]
        except KeyError as exc:
            raise ValueError(
                f"Source {source_id!r} references unknown backend "
                f"{definition.backend!r}."
            ) from exc

        semantic_path = _resolve_semantic_path(
            project_root, definition.semantic_model
        )
        relative_semantic = semantic_path.relative_to(project_root.resolve())
        limits = ExecutionLimits(
            timeout_seconds=(
                definition.limits.timeout_seconds
                or default_timeout_seconds
            ),
            max_result_rows=(
                definition.limits.max_result_rows
                or default_max_result_rows
            ),
            model_sample_rows=(
                definition.limits.model_sample_rows
                or default_model_sample_rows
            ),
        )
        if limits.model_sample_rows > limits.max_result_rows:
            raise ValueError(
                f"Source {source_id!r} has model_sample_rows greater than "
                "max_result_rows."
            )
        if limits.model_sample_rows > 10:
            raise ValueError(
                f"Source {source_id!r} has model_sample_rows greater than "
                "the hard 10-row model boundary."
            )

        resolved_sources[source_id] = DataSource(
            source_id=source_id,
            name=definition.name,
            description=definition.description,
            backend_id=definition.backend,
            backend_type=backend.type,
            backend_options=dict(backend.options),
            semantic_model_path=semantic_path,
            semantic_virtual_path=f"/project/{relative_semantic.as_posix()}",
            dialect=definition.dialect,
            target=dict(definition.target),
            examples=tuple(
                ExampleQuestion(label=item.label, question=item.question)
                for item in definition.examples
            ),
            limits=limits,
        )

    return DataSourceCatalog(
        config_path=registry_path,
        default_source_id=document.default_source,
        sources=resolved_sources,
    )
