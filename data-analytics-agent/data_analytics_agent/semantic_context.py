"""Bounded, source-versioned semantic definitions; never accesses source values."""

from __future__ import annotations

from collections import OrderedDict
from itertools import combinations
import json
from threading import RLock
from typing import Any
import sqlglot
from sqlglot import exp
from langchain_core.tools import ToolException
from data_analytics_agent.semantic import (
    SemanticCatalog,
    SemanticDataset,
    SemanticField,
    SemanticMetric,
    SemanticRelationship,
    render_semantic_overview,
)

CONTEXT_BUDGET = 12_000
MAX_AVAILABLE_FIELD_NAMES = 25
_CACHE: OrderedDict[tuple, str] = OrderedDict()
_COMPACT_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_LOCK = RLock()


def _field_payload(
    field: SemanticField,
    *,
    include_physical: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": field.name,
        "description": field.description,
        "synonyms": list(field.synonyms),
        "instructions": field.instructions,
        "is_time": field.is_time,
        "data_type": field.data_type,
    }
    if include_physical:
        payload.update(
            expression=field.expression,
            physical_data_type=field.physical_data_type,
        )
    return payload


def _dataset_payload(
    dataset: SemanticDataset,
    *,
    selected_fields: list[str] | None,
    include_physical: bool,
) -> dict[str, Any]:
    fields = dataset.fields.values()
    if selected_fields is not None:
        missing = [name for name in selected_fields if name not in dataset.fields]
        if missing:
            available = list(dataset.fields)[:MAX_AVAILABLE_FIELD_NAMES]
            omitted = len(dataset.fields) - len(available)
            available_text = repr(available)
            if omitted:
                available_text += f" ({omitted} additional names omitted)"
            raise ToolException(
                f"Unknown fields for dataset {dataset.name!r}: {missing!r}. "
                "field_names accepts logical names, not physical column names. "
                f"Available logical field names: {available_text}."
            )
        fields = (dataset.fields[name] for name in selected_fields)
    payload: dict[str, Any] = {
        "name": dataset.name,
        "description": dataset.description,
        "synonyms": list(dataset.synonyms),
        "instructions": dataset.instructions,
        "primary_key": list(dataset.primary_key),
        "grain": list(dataset.primary_key),
        "field_count": len(dataset.fields),
        "fields": [
            _field_payload(field, include_physical=include_physical) for field in fields
        ],
    }
    if include_physical:
        payload["source"] = dataset.source
    return payload


def _metric_payload(
    metric: SemanticMetric,
    *,
    include_physical: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": metric.name,
        "description": metric.description,
        "synonyms": list(metric.synonyms),
        "instructions": metric.instructions,
        "data_type": metric.data_type,
    }
    if include_physical:
        payload["expression"] = metric.expression
    return payload


def _relationship_payload(
    relationship: SemanticRelationship,
) -> dict[str, Any]:
    return {
        "name": relationship.name,
        "from_dataset": relationship.from_dataset,
        "to_dataset": relationship.to_dataset,
        "from_columns": list(relationship.from_columns),
        "to_columns": list(relationship.to_columns),
        "instructions": relationship.instructions,
    }


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _compact_catalog(catalog, *, source_id, dialect, include_physical):
    key = (source_id, catalog.content_hash, dialect, include_physical)
    with _LOCK:
        if key in _COMPACT_CACHE:
            _COMPACT_CACHE.move_to_end(key)
            return _COMPACT_CACHE[key]
    payload = {
        "datasets": {
            name: _dataset_payload(
                dataset, selected_fields=None, include_physical=include_physical
            )
            for name, dataset in catalog.datasets.items()
        },
        "metrics": {
            name: _metric_payload(metric, include_physical=include_physical)
            for name, metric in catalog.metrics.items()
        },
    }
    # Cache only bounded metadata representations, never observations.
    if len(_serialize(payload)) <= 1_000_000:
        with _LOCK:
            _COMPACT_CACHE[key] = payload
            while len(_COMPACT_CACHE) > 16:
                _COMPACT_CACHE.popitem(last=False)
    return payload


def _paths(catalog, start, target):
    """Find up to two declared routes; distinguish a search cap from disconnection."""
    shortest = catalog.shortest_path([start], target)
    if shortest is None:
        return [], False
    found, stack, steps = [tuple(shortest)], [(start, (), frozenset([start]))], 0
    while stack and len(found) < 2 and steps < 2000:
        node, path, seen = stack.pop()
        steps += 1
        if node == target:
            if path not in found:
                found.append(path)
            continue
        for edge in reversed(catalog.adjacency.get(node, ())):
            other = edge.to_dataset if edge.from_dataset == node else edge.from_dataset
            if other not in seen:
                stack.append((other, (*path, edge), seen | {other}))
    return found, bool(stack) and steps >= 2000


def build_semantic_context(
    catalog: SemanticCatalog,
    *,
    source_id: str,
    dialect: str,
    include_physical: bool,
    question: str = "",
    dataset_names=None,
    metric_names=None,
    field_names=None,
    budget: int = CONTEXT_BUDGET,
    full: bool = False,
):
    key = (
        source_id,
        catalog.content_hash,
        dialect,
        include_physical,
        " ".join(question.casefold().split()),
        tuple(dataset_names or ()),
        tuple(metric_names or ()),
        _serialize(field_names or {}),
        budget,
        full,
    )
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return json.loads(_CACHE[key])
    if budget < 512:
        raise ValueError("Semantic context budget must be at least 512 characters.")
    compact = _compact_catalog(
        catalog, source_id=source_id, dialect=dialect, include_physical=include_physical
    )
    datasets = list(dict.fromkeys(dataset_names or ()))
    metrics = list(dict.fromkeys(metric_names or ()))
    discovered_metrics = []
    if full:
        datasets, metrics = list(catalog.datasets), list(catalog.metrics)
    elif not datasets and not metrics:
        for match in catalog.search(question, limit=5):
            if match.kind == "metric":
                metrics.append(match.name)
                discovered_metrics.append(match.name)
            else:
                name = match.parent_dataset or match.name
                if name not in datasets:
                    datasets.append(name)
    unknown = [n for n in datasets if n not in catalog.datasets]
    unknown += [n for n in metrics if n not in catalog.metrics]
    if unknown:
        response = {
            "complete": False,
            "model_hash": catalog.content_hash,
            "error": "Unknown exact logical names",
            "unknown": [],
            "alternatives": {"datasets": [], "metrics": []},
            "refinement": "Use browse_semantic_model to page through valid names.",
        }
        for bucket, names in [
            (response["unknown"], unknown[:10]),
            (response["alternatives"]["datasets"], list(catalog.datasets)[:25]),
            (response["alternatives"]["metrics"], list(catalog.metrics)[:25]),
        ]:
            for name in names:
                bucket.append(name)
                if len(_serialize(response)) > budget:
                    bucket.pop()
                    break
        return response
    unresolved, ambiguities, disconnected = [], [], []
    if len(discovered_metrics) > 1:
        ambiguities.append(
            {
                "metrics": discovered_metrics,
                "message": "Several metric definitions match. Confirm which meanings the question requires.",
            }
        )
    required = {name: set() for name in datasets}
    for name in metrics:
        metric = catalog.metrics[name]
        try:
            expression = sqlglot.parse_one(metric.expression, read=dialect)
            for column in expression.find_all(exp.Column):
                candidates = []
                for dataset in catalog.datasets.values():
                    if column.table and column.table.casefold() not in {
                        dataset.name.casefold(),
                        dataset.source.casefold(),
                    }:
                        continue
                    for field in dataset.fields.values():
                        if column.name.casefold() in {
                            field.name.casefold(),
                            field.expression.casefold(),
                        }:
                            candidates.append((dataset.name, field.name))
                if len(candidates) != 1:
                    unresolved.append(
                        f"{name}: unresolved or ambiguous reference"
                        + (f" {column.sql()}" if include_physical else "")
                    )
                else:
                    parent, field = candidates[0]
                    if parent not in datasets:
                        datasets.append(parent)
                    required.setdefault(parent, set()).add(field)
        except (sqlglot.errors.SqlglotError, ValueError):
            unresolved.append(f"{name}: expression could not be reliably resolved")
    edges = {edge.name: edge for edge in catalog.relationships} if full else {}
    if not full:
        for start, target in combinations(datasets.copy(), 2):
            routes, capped = _paths(catalog, start, target)
            if len(routes) > 1:
                ambiguities.append(
                    {
                        "datasets": [start, target],
                        "routes": [[e.name for e in route] for route in routes],
                        "message": "Alternative declared routes; confirm business meaning.",
                    }
                )
            if capped:
                unresolved.append(f"Join path search incomplete: {start} to {target}")
            elif not routes:
                disconnected.append([start, target])
            for route in routes:
                for edge in route:
                    edges[edge.name] = edge
    for edge in edges.values():
        for parent, fields in (
            (edge.from_dataset, edge.from_columns),
            (edge.to_dataset, edge.to_columns),
        ):
            if parent not in datasets:
                datasets.append(parent)
            required.setdefault(parent, set()).update(fields)
    unexpected = set(field_names or {}) - set(datasets)
    if unexpected:
        unresolved.append(
            f"field_names includes unselected datasets: {sorted(unexpected)}"
        )
    definitions = []
    for name in datasets:
        dataset = catalog.datasets[name]
        fields = None
        if field_names is not None and name in field_names:
            fields = list(
                dict.fromkeys(
                    [
                        *field_names[name],
                        *sorted(required.get(name, set())),
                        *dataset.primary_key,
                    ]
                )
            )
        try:
            definitions.append(
                compact["datasets"][name]
                if fields is None
                else _dataset_payload(
                    dataset, selected_fields=fields, include_physical=include_physical
                )
            )
        except ToolException as exc:
            unresolved.append(str(exc))
    result = dict(
        model_hash=catalog.content_hash,
        source_id=source_id,
        dialect=dialect,
        projection="physical" if include_physical else "business",
        complete=not unresolved and bool(datasets or metrics),
        catalog_complete=full,
        instructions=catalog.instructions,
        datasets=definitions,
        metrics=[compact["metrics"][n] for n in metrics],
        relationships=[_relationship_payload(e) for e in edges.values()],
        ambiguities=ambiguities,
        disconnected=disconnected,
        unresolved_references=unresolved,
        omissions=[],
    )
    if len(_serialize(result)) > budget:
        # Never truncate a SQL expression, instruction or a join dependency.
        result = dict(
            model_hash=catalog.content_hash,
            complete=False,
            catalog_complete=False,
            datasets=[],
            metrics=[],
            relationships=[],
            omissions=[
                "Requested definitions and their dependencies exceed the serialized context budget."
            ],
            refinement="Select fewer exact datasets/metrics and field_names; browse_semantic_model provides paginated fields.",
        )
    serialized = _serialize(result)
    with _LOCK:
        _CACHE[key] = serialized
        _CACHE.move_to_end(key)
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return json.loads(serialized)


def render_sql_context(catalog, *, source_id, dialect):
    context = build_semantic_context(
        catalog, source_id=source_id, dialect=dialect, include_physical=True, full=True
    )
    if context["complete"]:
        return (
            "Complete exact catalog definitions (no discovery needed):\n"
            + _serialize(context)
        )
    return (
        render_semantic_overview(catalog)
        + "\nCatalog content hash: "
        + catalog.content_hash
        + "\nExact context is incomplete. Use get_semantic_context for relevant definitions."
    )
