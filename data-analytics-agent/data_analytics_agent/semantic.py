"""Immutable OSI catalog loading, validation, and semantic discovery."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Literal
import unicodedata

import yaml

from data_analytics_agent.backends import SQLBackend

SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
SEARCH_STOP_WORDS = frozenset(
    {"a", "an", "and", "by", "for", "in", "of", "or", "the", "to", "with"}
)
SEMANTIC_OVERVIEW_MAX_CHARS = 12_000

EntityKind = Literal["dataset", "field", "metric"]


@dataclass(frozen=True)
class SemanticDiagnostics:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticField:
    name: str
    description: str
    expression: str
    synonyms: tuple[str, ...] = ()
    instructions: str = ""
    is_time: bool = False
    data_type: str | None = None
    physical_data_type: str | None = None


@dataclass(frozen=True)
class SemanticDataset:
    name: str
    source: str
    description: str
    primary_key: tuple[str, ...]
    fields: Mapping[str, SemanticField]
    synonyms: tuple[str, ...] = ()
    instructions: str = ""


@dataclass(frozen=True)
class SemanticMetric:
    name: str
    description: str
    expression: str
    synonyms: tuple[str, ...] = ()
    instructions: str = ""
    data_type: str | None = None


@dataclass(frozen=True)
class SemanticRelationship:
    name: str
    from_dataset: str
    to_dataset: str
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    instructions: str = ""


@dataclass(frozen=True)
class SemanticMatch:
    kind: EntityKind
    name: str
    parent_dataset: str | None
    description: str
    matched_text: str
    match_reason: str
    score: int


@dataclass(frozen=True)
class SemanticCatalog:
    version: str
    name: str
    description: str
    instructions: str
    examples: tuple[str, ...]
    datasets: Mapping[str, SemanticDataset]
    metrics: Mapping[str, SemanticMetric]
    relationships: tuple[SemanticRelationship, ...]
    adjacency: Mapping[str, tuple[SemanticRelationship, ...]]
    content_hash: str

    @property
    def field_count(self) -> int:
        return sum(len(dataset.fields) for dataset in self.datasets.values())

    def search(
        self,
        query: str,
        *,
        entity_kinds: Iterable[EntityKind] | None = None,
        limit: int = 10,
    ) -> tuple[SemanticMatch, ...]:
        normalized_query = _normalize_search_text(query)
        if not normalized_query:
            raise ValueError("Semantic search query cannot be empty.")
        if not 1 <= limit <= 25:
            raise ValueError("Semantic search limit must be between 1 and 25.")
        kinds = set(entity_kinds or ("dataset", "field", "metric"))
        if not kinds <= {"dataset", "field", "metric"}:
            raise ValueError("Unknown semantic entity kind.")

        matches: list[SemanticMatch] = []
        if "dataset" in kinds:
            for dataset in self.datasets.values():
                match = _score_entity(
                    normalized_query,
                    kind="dataset",
                    name=dataset.name,
                    parent_dataset=None,
                    description=dataset.description,
                    synonyms=dataset.synonyms,
                )
                if match:
                    matches.append(match)
        if "field" in kinds:
            for dataset in self.datasets.values():
                for field in dataset.fields.values():
                    match = _score_entity(
                        normalized_query,
                        kind="field",
                        name=field.name,
                        parent_dataset=dataset.name,
                        description=field.description,
                        synonyms=field.synonyms,
                    )
                    if match:
                        matches.append(match)
        if "metric" in kinds:
            for metric in self.metrics.values():
                match = _score_entity(
                    normalized_query,
                    kind="metric",
                    name=metric.name,
                    parent_dataset=None,
                    description=metric.description,
                    synonyms=metric.synonyms,
                )
                if match:
                    matches.append(match)

        matches.sort(
            key=lambda item: (
                -item.score,
                item.kind,
                item.parent_dataset or "",
                item.name,
            )
        )
        return tuple(matches[:limit])

    def adjacent_relationships(
        self, dataset_names: Iterable[str]
    ) -> tuple[SemanticRelationship, ...]:
        selected = set(dataset_names)
        include_adjacent = len(selected) == 1
        return tuple(
            relationship
            for relationship in sorted(
                self.relationships, key=lambda item: item.name
            )
            if (
                relationship.from_dataset in selected
                and relationship.to_dataset in selected
            )
            or (
                include_adjacent
                and (
                    relationship.from_dataset in selected
                    or relationship.to_dataset in selected
                )
            )
        )

    def shortest_path(
        self,
        dataset_names: Iterable[str],
        target_dataset: str,
    ) -> tuple[SemanticRelationship, ...] | None:
        starts = sorted(set(dataset_names))
        if target_dataset in starts:
            return ()
        queue: deque[tuple[str, tuple[SemanticRelationship, ...]]] = deque(
            (name, ()) for name in starts
        )
        visited = set(starts)
        while queue:
            current, path = queue.popleft()
            neighbors: list[tuple[str, SemanticRelationship]] = []
            for relationship in self.adjacency.get(current, ()):
                other = (
                    relationship.to_dataset
                    if relationship.from_dataset == current
                    else relationship.from_dataset
                )
                neighbors.append((other, relationship))
            for other, relationship in sorted(
                neighbors, key=lambda item: (item[0], item[1].name)
            ):
                if other in visited:
                    continue
                next_path = (*path, relationship)
                if other == target_dataset:
                    return next_path
                visited.add(other)
                queue.append((other, next_path))
        return None


@dataclass(frozen=True)
class SemanticLoadResult:
    catalog: SemanticCatalog | None
    diagnostics: SemanticDiagnostics


def _mapping(values: dict[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(values)


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _ai_context(
    item: Mapping[str, Any],
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    context = item.get("ai_context")
    if not isinstance(context, dict):
        return (), "", ()
    synonyms = context.get("synonyms")
    examples = context.get("examples")
    return (
        tuple(str(value) for value in synonyms)
        if isinstance(synonyms, list)
        else (),
        _compact_text(context.get("instructions")),
        tuple(str(value) for value in examples)
        if isinstance(examples, list)
        else (),
    )


def _dialect_expression(item: Mapping[str, Any], dialect: str) -> str | None:
    expression = item.get("expression")
    if not isinstance(expression, dict):
        return None
    dialects = expression.get("dialects")
    if not isinstance(dialects, list):
        return None
    fallback: str | None = None
    for candidate in dialects:
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("expression")
        if not isinstance(value, str) or not value:
            continue
        declared = str(candidate.get("dialect") or "")
        if declared.casefold() == dialect.casefold():
            return value
        if declared.casefold() == "ansi_sql":
            fallback = value
    return fallback


def _read_model(
    path: Path,
) -> tuple[bytes | None, dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, None, [f"OSI semantic model not found at {path}."]
    try:
        raw = path.read_bytes()
        document = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        return None, None, [f"Could not read OSI semantic model at {path}: {exc}"]
    if not isinstance(document, dict):
        return raw, None, [f"OSI semantic model at {path} must be a YAML mapping."]
    if document.get("version") != "0.1.1":
        return raw, None, [
            f'OSI semantic model at {path} must declare version "0.1.1".'
        ]
    models = document.get("semantic_model")
    if not isinstance(models, list) or len(models) != 1:
        return raw, None, [
            f"OSI semantic model at {path} must contain exactly one model."
        ]
    model = models[0]
    if not isinstance(model, dict):
        return raw, None, [f"OSI semantic model entry at {path} is invalid."]
    return raw, model, []


def load_semantic_catalog(
    path: Path,
    *,
    dialect: str,
    backend: SQLBackend | None = None,
) -> SemanticLoadResult:
    """Load one validated OSI document into the application catalog."""

    raw, model, errors = _read_model(path)
    warnings: list[str] = []
    if model is None or raw is None:
        return SemanticLoadResult(
            catalog=None,
            diagnostics=SemanticDiagnostics(errors=tuple(errors)),
        )

    datasets_value = model.get("datasets")
    if not isinstance(datasets_value, list) or not datasets_value:
        errors.append("The OSI model must define at least one dataset.")
        return SemanticLoadResult(
            catalog=None,
            diagnostics=SemanticDiagnostics(errors=tuple(errors)),
        )

    datasets: dict[str, SemanticDataset] = {}
    for dataset_value in datasets_value:
        if not isinstance(dataset_value, dict):
            errors.append("Every OSI dataset must be a mapping.")
            continue
        name = dataset_value.get("name")
        source = dataset_value.get("source")
        fields_value = dataset_value.get("fields")
        if not isinstance(name, str) or not name:
            errors.append("Every OSI dataset must have a non-empty name.")
            continue
        if name in datasets:
            errors.append(f"Duplicate OSI dataset name {name!r}.")
            continue
        if not isinstance(source, str) or not source:
            errors.append(f"Dataset {name!r} has no physical source.")
            continue
        if not isinstance(fields_value, list) or not fields_value:
            errors.append(f"Dataset {name!r} has no fields.")
            continue

        fields: dict[str, SemanticField] = {}
        for field_value in fields_value:
            if not isinstance(field_value, dict):
                errors.append(f"Dataset {name!r} contains an invalid field.")
                continue
            field_name = field_value.get("name")
            if not isinstance(field_name, str) or not field_name:
                errors.append(f"Dataset {name!r} contains an invalid field.")
                continue
            if field_name in fields:
                errors.append(
                    f"Dataset {name!r} repeats field {field_name!r}."
                )
                continue
            expression = _dialect_expression(field_value, dialect)
            if expression is None:
                errors.append(
                    f"Field {name}.{field_name} has no {dialect} or "
                    "ANSI_SQL expression."
                )
                continue
            synonyms, instructions, _ = _ai_context(field_value)
            dimension = field_value.get("dimension")
            data_type = field_value.get("data_type")
            fields[field_name] = SemanticField(
                name=field_name,
                description=_compact_text(field_value.get("description")),
                expression=expression,
                synonyms=synonyms,
                instructions=instructions,
                is_time=isinstance(dimension, dict)
                and dimension.get("is_time") is True,
                data_type=str(data_type) if data_type is not None else None,
            )

        primary_key_value = dataset_value.get("primary_key") or []
        if not isinstance(primary_key_value, list) or not set(
            primary_key_value
        ) <= set(fields):
            errors.append(f"Dataset {name!r} has an invalid primary key.")
            primary_key: tuple[str, ...] = ()
        else:
            primary_key = tuple(str(value) for value in primary_key_value)
        synonyms, instructions, _ = _ai_context(dataset_value)
        datasets[name] = SemanticDataset(
            name=name,
            source=source,
            description=_compact_text(dataset_value.get("description")),
            primary_key=primary_key,
            fields=_mapping(fields),
            synonyms=synonyms,
            instructions=instructions,
        )

    relationships: list[SemanticRelationship] = []
    relationship_names: set[str] = set()
    relationships_value = model.get("relationships") or []
    if not isinstance(relationships_value, list):
        errors.append("OSI relationships must be a list.")
    else:
        for value in relationships_value:
            if not isinstance(value, dict):
                errors.append("Every OSI relationship must be a mapping.")
                continue
            name = value.get("name")
            from_name = value.get("from")
            to_name = value.get("to")
            if not isinstance(name, str) or not name:
                errors.append(
                    "Every OSI relationship must have a non-empty name."
                )
                continue
            if name in relationship_names:
                errors.append(f"Duplicate OSI relationship name {name!r}.")
                continue
            relationship_names.add(name)
            if from_name not in datasets or to_name not in datasets:
                errors.append(
                    f"Relationship {name!r} references an unknown dataset."
                )
                continue
            from_columns = value.get("from_columns") or []
            to_columns = value.get("to_columns") or []
            if (
                not isinstance(from_columns, list)
                or not isinstance(to_columns, list)
                or len(from_columns) != len(to_columns)
                or not from_columns
            ):
                errors.append(
                    f"Relationship {name!r} has invalid column mappings."
                )
                continue
            if not set(from_columns) <= set(
                datasets[str(from_name)].fields
            ) or not set(to_columns) <= set(datasets[str(to_name)].fields):
                errors.append(
                    f"Relationship {name!r} references an unknown field."
                )
                continue
            _, instructions, _ = _ai_context(value)
            relationships.append(
                SemanticRelationship(
                    name=name,
                    from_dataset=str(from_name),
                    to_dataset=str(to_name),
                    from_columns=tuple(str(column) for column in from_columns),
                    to_columns=tuple(str(column) for column in to_columns),
                    instructions=instructions,
                )
            )

    metrics: dict[str, SemanticMetric] = {}
    metrics_value = model.get("metrics") or []
    if not metrics_value:
        warnings.append("The OSI model defines no canonical metrics.")
    elif not isinstance(metrics_value, list):
        errors.append("OSI metrics must be a list.")
    else:
        for value in metrics_value:
            if not isinstance(value, dict):
                errors.append("Every OSI metric must be a mapping.")
                continue
            name = value.get("name")
            if not isinstance(name, str) or not name:
                errors.append("Every OSI metric must have a non-empty name.")
                continue
            if name in metrics:
                errors.append(f"Duplicate OSI metric name {name!r}.")
                continue
            expression = _dialect_expression(value, dialect)
            if expression is None:
                errors.append(
                    f"Metric {name!r} has no {dialect} or ANSI_SQL expression."
                )
                continue
            synonyms, instructions, _ = _ai_context(value)
            data_type = value.get("data_type")
            metrics[name] = SemanticMetric(
                name=name,
                description=_compact_text(value.get("description")),
                expression=expression,
                synonyms=synonyms,
                instructions=instructions,
                data_type=str(data_type) if data_type is not None else None,
            )

    if backend is not None and not errors:
        sources = sorted({dataset.source for dataset in datasets.values()})
        try:
            inspected_tables = backend.get_table_schema(sources)
        except Exception as exc:
            errors.append(f"Could not inspect live table schemas: {exc}")
        else:
            schema_by_name = {
                table.name.casefold(): table for table in inspected_tables
            }
            annotated: dict[str, SemanticDataset] = {}
            for name, dataset in datasets.items():
                table = schema_by_name.get(dataset.source.casefold())
                if table is None:
                    errors.append(f"Could not inspect table {dataset.source!r}.")
                    annotated[name] = dataset
                    continue
                columns = {
                    column.name.casefold(): column for column in table.columns
                }
                fields: dict[str, SemanticField] = {}
                for field_name, field in dataset.fields.items():
                    column = (
                        columns.get(field.expression.casefold())
                        if SIMPLE_IDENTIFIER.fullmatch(field.expression)
                        else None
                    )
                    if (
                        SIMPLE_IDENTIFIER.fullmatch(field.expression)
                        and column is None
                    ):
                        errors.append(
                            f"OSI field {dataset.name}.{field.name} references "
                            f"missing column {dataset.source}.{field.expression}."
                        )
                    fields[field_name] = replace(
                        field,
                        physical_data_type=(column.data_type if column else None),
                    )
                annotated[name] = replace(dataset, fields=_mapping(fields))
            datasets = annotated

    if errors:
        return SemanticLoadResult(
            catalog=None,
            diagnostics=SemanticDiagnostics(
                errors=tuple(errors), warnings=tuple(warnings)
            ),
        )

    adjacency: dict[str, list[SemanticRelationship]] = {
        name: [] for name in datasets
    }
    for relationship in relationships:
        adjacency[relationship.from_dataset].append(relationship)
        if relationship.to_dataset != relationship.from_dataset:
            adjacency[relationship.to_dataset].append(relationship)
    _, instructions, examples = _ai_context(model)
    catalog = SemanticCatalog(
        version="0.1.1",
        name=str(model.get("name") or ""),
        description=_compact_text(model.get("description")),
        instructions=instructions,
        examples=examples,
        datasets=_mapping(datasets),
        metrics=_mapping(metrics),
        relationships=tuple(relationships),
        adjacency=_mapping(
            {
                name: tuple(sorted(values, key=lambda item: item.name))
                for name, values in adjacency.items()
            }
        ),
        content_hash=sha256(raw).hexdigest(),
    )
    return SemanticLoadResult(
        catalog=catalog,
        diagnostics=SemanticDiagnostics(warnings=tuple(warnings)),
    )


def render_semantic_overview(
    catalog: SemanticCatalog,
    *,
    max_chars: int = SEMANTIC_OVERVIEW_MAX_CHARS,
) -> str:
    """Render bounded, deterministic business-facing model orientation."""

    entity_budget = max_chars - 200
    lines = [
        f"Model: {catalog.name} (OSI {catalog.version})",
        (
            "Description: "
            + (catalog.description[:2_000] or "No model description provided.")
        ),
        (
            "Instructions: "
            + (catalog.instructions[:4_000] or "No global instructions provided.")
        ),
        (
            f"Counts: {len(catalog.datasets)} datasets, {catalog.field_count} "
            f"fields, {len(catalog.metrics)} metrics, "
            f"{len(catalog.relationships)} relationships"
        ),
        f"Model hash: {catalog.content_hash}",
        "Datasets:",
    ]
    omitted_datasets = 0
    for dataset in sorted(catalog.datasets.values(), key=lambda item: item.name):
        line = f"- {dataset.name}: {dataset.description}"
        if len("\n".join((*lines, line))) > entity_budget:
            omitted_datasets += 1
        else:
            lines.append(line)
    if omitted_datasets:
        lines.append(
            f"- … {omitted_datasets} additional datasets omitted; "
            "use semantic search."
        )
    lines.append("Metrics:")
    omitted_metrics = 0
    for metric in sorted(catalog.metrics.values(), key=lambda item: item.name):
        line = f"- {metric.name}: {metric.description}"
        if len("\n".join((*lines, line))) > entity_budget:
            omitted_metrics += 1
        else:
            lines.append(line)
    if omitted_metrics:
        lines.append(
            f"- … {omitted_metrics} additional metrics omitted; "
            "use semantic search."
        )
    return "\n".join(lines)


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(TOKEN_PATTERN.findall(normalized))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_search_text(value).split()
        if token not in SEARCH_STOP_WORDS
    }


def _score_entity(
    query: str,
    *,
    kind: EntityKind,
    name: str,
    parent_dataset: str | None,
    description: str,
    synonyms: tuple[str, ...],
) -> SemanticMatch | None:
    normalized_name = _normalize_search_text(name)
    normalized_synonyms = tuple(
        _normalize_search_text(value) for value in synonyms
    )
    if query == normalized_name:
        return SemanticMatch(
            kind, name, parent_dataset, description, name, "exact_name", 500
        )
    for raw, normalized in zip(synonyms, normalized_synonyms, strict=True):
        if query == normalized:
            return SemanticMatch(
                kind,
                name,
                parent_dataset,
                description,
                raw,
                "exact_synonym",
                400,
            )

    query_tokens = _tokens(query)
    if not query_tokens:
        return None
    searchable = [(name, _tokens(name))]
    if parent_dataset:
        searchable.append(
            (
                f"{parent_dataset}.{name}",
                _tokens(f"{parent_dataset} {name}"),
            )
        )
    searchable.extend((value, _tokens(value)) for value in synonyms)
    full_matches = [item for item in searchable if query_tokens <= item[1]]
    if full_matches:
        matched = sorted(
            full_matches, key=lambda item: (len(item[1]), item[0])
        )[0]
        return SemanticMatch(
            kind,
            name,
            parent_dataset,
            description,
            matched[0],
            "all_tokens_in_name_or_synonym",
            300,
        )
    overlaps = [(len(query_tokens & tokens), raw) for raw, tokens in searchable]
    best_overlap, matched_text = max(overlaps, default=(0, ""))
    if best_overlap:
        score = 200 + round(100 * best_overlap / len(query_tokens))
        return SemanticMatch(
            kind,
            name,
            parent_dataset,
            description,
            matched_text,
            "name_or_synonym_token_overlap",
            score,
        )
    description_overlap = len(query_tokens & _tokens(description))
    if description_overlap:
        score = 100 + round(100 * description_overlap / len(query_tokens))
        return SemanticMatch(
            kind,
            name,
            parent_dataset,
            description,
            description,
            "description_token_overlap",
            score,
        )
    return None
