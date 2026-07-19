"""OSI semantic-model loading and source-to-database readiness checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from text2sql_agent.backends import SQLBackend

SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class SemanticDiagnostics:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _field_expression(field: dict[str, Any], dialect: str) -> str | None:
    expression = field.get("expression")
    if not isinstance(expression, dict):
        return None
    dialects = expression.get("dialects")
    if not isinstance(dialects, list):
        return None
    fallback: str | None = None
    for item in dialects:
        if not isinstance(item, dict):
            continue
        value = item.get("expression")
        if not isinstance(value, str):
            continue
        declared_dialect = str(item.get("dialect") or "")
        if declared_dialect.casefold() == dialect.casefold():
            return value
        if declared_dialect.casefold() == "ansi_sql":
            fallback = value
    return fallback


def _load_model_document(
    path: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, [f"OSI semantic model not found at {path}."]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [f"Could not read OSI semantic model at {path}: {exc}"]
    if not isinstance(document, dict):
        return None, [f"OSI semantic model at {path} must be a YAML mapping."]
    if document.get("version") != "0.1.1":
        return None, [
            f"OSI semantic model at {path} must declare version \"0.1.1\"."
        ]
    models = document.get("semantic_model")
    if not isinstance(models, list) or len(models) != 1:
        return None, [
            f"OSI semantic model at {path} must contain exactly one model."
        ]
    model = models[0]
    if not isinstance(model, dict):
        return None, [f"OSI semantic model entry at {path} is invalid."]
    return model, []


def validate_semantic_model(
    path: Path,
    *,
    dialect: str,
    backend: SQLBackend | None = None,
) -> SemanticDiagnostics:
    """Validate OSI structure and clear physical schema mismatches."""

    model, errors = _load_model_document(path)
    warnings: list[str] = []
    if model is None:
        return SemanticDiagnostics(errors=tuple(errors))

    datasets_value = model.get("datasets")
    if not isinstance(datasets_value, list) or not datasets_value:
        errors.append("The OSI model must define at least one dataset.")
        return SemanticDiagnostics(errors=tuple(errors))

    datasets: dict[str, dict[str, Any]] = {}
    physical_sources: dict[str, dict[str, Any]] = {}
    for dataset in datasets_value:
        if not isinstance(dataset, dict):
            errors.append("Every OSI dataset must be a mapping.")
            continue
        logical_name = dataset.get("name")
        physical_source = dataset.get("source")
        fields = dataset.get("fields")
        if not isinstance(logical_name, str) or not logical_name:
            errors.append("Every OSI dataset must have a non-empty name.")
            continue
        if logical_name in datasets:
            errors.append(f"Duplicate OSI dataset name {logical_name!r}.")
            continue
        datasets[logical_name] = dataset
        if not isinstance(physical_source, str) or not physical_source:
            errors.append(f"Dataset {logical_name!r} has no physical source.")
        else:
            physical_sources[physical_source] = dataset
        if not isinstance(fields, list) or not fields:
            errors.append(f"Dataset {logical_name!r} has no fields.")
            continue
        logical_fields: set[str] = set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(
                field.get("name"), str
            ):
                errors.append(
                    f"Dataset {logical_name!r} contains an invalid field."
                )
                continue
            field_name = field["name"]
            if field_name in logical_fields:
                errors.append(
                    f"Dataset {logical_name!r} repeats field {field_name!r}."
                )
            logical_fields.add(field_name)
            if _field_expression(field, dialect) is None:
                errors.append(
                    f"Field {logical_name}.{field_name} has no {dialect} or "
                    "ANSI_SQL expression."
                )
        primary_key = dataset.get("primary_key") or []
        if not isinstance(primary_key, list) or not set(primary_key) <= logical_fields:
            errors.append(
                f"Dataset {logical_name!r} has an invalid primary key."
            )

    relationships = model.get("relationships") or []
    if not isinstance(relationships, list):
        errors.append("OSI relationships must be a list.")
    else:
        for relationship in relationships:
            if not isinstance(relationship, dict):
                errors.append("Every OSI relationship must be a mapping.")
                continue
            from_name = relationship.get("from")
            to_name = relationship.get("to")
            if from_name not in datasets or to_name not in datasets:
                errors.append(
                    f"Relationship {relationship.get('name')!r} references "
                    "an unknown dataset."
                )
                continue
            from_columns = relationship.get("from_columns") or []
            to_columns = relationship.get("to_columns") or []
            if (
                not isinstance(from_columns, list)
                or not isinstance(to_columns, list)
                or len(from_columns) != len(to_columns)
                or not from_columns
            ):
                errors.append(
                    f"Relationship {relationship.get('name')!r} has invalid "
                    "column mappings."
                )
                continue
            from_fields = {
                item.get("name")
                for item in datasets[from_name].get("fields", [])
                if isinstance(item, dict)
            }
            to_fields = {
                item.get("name")
                for item in datasets[to_name].get("fields", [])
                if isinstance(item, dict)
            }
            if not set(from_columns) <= from_fields or not set(
                to_columns
            ) <= to_fields:
                errors.append(
                    f"Relationship {relationship.get('name')!r} references "
                    "an unknown field."
                )

    if not model.get("metrics"):
        warnings.append("The OSI model defines no canonical metrics.")

    if backend is not None and not errors:
        try:
            available = {
                table.casefold(): table for table in backend.list_tables()
            }
        except Exception as exc:
            errors.append(f"Could not inspect live database tables: {exc}")
        else:
            matched_sources = {
                physical_source: available[physical_source.casefold()]
                for physical_source in physical_sources
                if physical_source.casefold() in available
            }
            for physical_source, dataset in physical_sources.items():
                if physical_source not in matched_sources:
                    errors.append(
                        f"OSI dataset {dataset['name']!r} references missing "
                        f"table {physical_source!r}."
                    )
            try:
                inspected_tables = backend.get_table_schema(
                    list(matched_sources.values())
                )
            except Exception as exc:
                errors.append(f"Could not inspect live table schemas: {exc}")
                inspected_tables = []
            schema_by_name = {
                table.name.casefold(): table for table in inspected_tables
            }
            for physical_source, dataset in physical_sources.items():
                matched_name = matched_sources.get(physical_source)
                if matched_name is None:
                    continue
                table = schema_by_name.get(matched_name.casefold())
                if table is None:
                    errors.append(
                        f"Could not inspect table {matched_name!r}."
                    )
                    continue
                columns = {
                    column.name.casefold(): column.name
                    for column in table.columns
                }
                for field in dataset.get("fields", []):
                    if not isinstance(field, dict):
                        continue
                    expression = _field_expression(field, dialect)
                    if (
                        expression
                        and SIMPLE_IDENTIFIER.fullmatch(expression)
                        and expression.casefold() not in columns
                    ):
                        errors.append(
                            f"OSI field {dataset['name']}.{field['name']} "
                            f"references missing column {physical_source}."
                            f"{expression}."
                        )

    return SemanticDiagnostics(
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
