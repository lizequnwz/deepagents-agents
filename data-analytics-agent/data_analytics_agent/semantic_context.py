"""Bounded, source-versioned semantic definitions; never accesses source values."""

from __future__ import annotations

import json
from collections import OrderedDict, deque
from itertools import combinations
from threading import RLock
from typing import Any

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
        "grain_basis": "declared primary key; aggregation grain must follow the business definition",
        "field_count": len(dataset.fields),
        "omitted_field_count": len(dataset.fields)
        - (
            len(selected_fields) if selected_fields is not None else len(dataset.fields)
        ),
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
    catalog: SemanticCatalog,
) -> dict[str, Any]:
    return {
        "name": relationship.name,
        "from_dataset": relationship.from_dataset,
        "to_dataset": relationship.to_dataset,
        "from_columns": list(relationship.from_columns),
        "to_columns": list(relationship.to_columns),
        "instructions": relationship.instructions,
        "from_key_unique": bool(catalog.datasets[relationship.from_dataset].primary_key)
        and set(catalog.datasets[relationship.from_dataset].primary_key)
        <= set(relationship.from_columns),
        "to_key_unique": bool(catalog.datasets[relationship.to_dataset].primary_key)
        and set(catalog.datasets[relationship.to_dataset].primary_key)
        <= set(relationship.to_columns),
        "uniqueness_basis": "declared primary keys only; false means unknown, not verified nonunique",
    }


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _paths(catalog, start, target):
    """Breadth-first bounded alternatives, without expanding their definitions."""
    queue = deque([(start, (), frozenset([start]))])
    found, steps = [], 0
    while queue and len(found) < 2 and steps < 2000:
        node, path, seen = queue.popleft()
        steps += 1
        if node == target:
            found.append(path)
            continue
        for edge in sorted(catalog.adjacency.get(node, ()), key=lambda e: e.name):
            other = edge.to_dataset if edge.from_dataset == node else edge.from_dataset
            if other not in seen:
                queue.append((other, (*path, edge), seen | {other}))
    return found, bool(queue) and steps >= 2000


def discovery_candidates(catalog, question):
    """Independent quotas prevent fields from starving measures and time roles."""
    candidates = {}
    from data_analytics_agent.semantic import _normalize_search_text

    if not _normalize_search_text(question):
        return candidates
    for kind in ("metric", "dataset", "field", "time"):
        matches = catalog.search(
            question,
            entity_kinds=["field" if kind == "time" else kind],
            limit=6,
            time_only=kind == "time",
            per_dataset_limit=2,
        )
        candidates[kind] = [
            {
                "name": m.name,
                "dataset": m.parent_dataset,
                "description": m.description[:240],
                "reason": m.match_reason,
                "score": m.score,
            }
            for m in matches
        ]
    return candidates


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
    relationship_names=None,
    budget: int = CONTEXT_BUDGET,
    full: bool = False,
):
    if budget < 512:
        raise ValueError("Semantic context budget must be at least 512 characters.")
    key = (
        source_id,
        catalog.content_hash,
        dialect,
        include_physical,
        question,
        tuple(dataset_names or ()),
        tuple(metric_names or ()),
        _serialize(field_names),
        _serialize(relationship_names),
        budget,
        full,
    )
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return json.loads(_CACHE[key])
    datasets = list(dict.fromkeys([*(dataset_names or ()), *(field_names or {})]))
    metrics = list(dict.fromkeys(metric_names or ()))
    relationships = {e.name: e for e in catalog.relationships}
    result = {
        "model_hash": catalog.content_hash,
        "source_id": source_id,
        "dialect": dialect,
        "projection": "physical" if include_physical else "business",
        "mode": "definitions",
        "definitions_complete": False,
        "catalog_complete": False,
        "question_coverage": "not_assessed",
        "blocking_issues": [],
        "omissions": [],
        "datasets": [],
        "metrics": [],
        "relationships": [],
        "ambiguities": [],
        "disconnected": [],
    }
    if not full and not (datasets or metrics or relationship_names):
        result.update(mode="discovery", question_coverage="requires_selection")
        result["candidates"] = (
            discovery_candidates(catalog, question) if question.strip() else {}
        )
        result["refinement"] = (
            "Search each measure, dimension, filter and time role separately with browse_semantic_model. "
            "Choose exact metric/field/relationship names, then request definitions. "
            "Candidates are not resolved definitions or proof of question coverage."
        )
        if not any(result["candidates"].values()):
            result["blocking_issues"].append(
                "No candidates; reformulate or browse the catalog."
            )
    else:
        if full:
            datasets, metrics = list(catalog.datasets), list(catalog.metrics)
        unknown = [f"dataset:{n}" for n in datasets if n not in catalog.datasets]
        unknown += [f"metric:{n}" for n in metrics if n not in catalog.metrics]
        unknown += [
            f"relationship:{n}"
            for n in relationship_names or ()
            if n not in relationships
        ]
        if unknown:
            result["blocking_issues"].append(
                "Unknown exact logical names: " + ", ".join(unknown)
            )
            result["refinement"] = (
                "Browse the corresponding entity kind for valid logical names."
            )
        else:
            try:
                bindings = catalog.bindings
            except ValueError as exc:
                result["blocking_issues"].append(
                    str(exc)
                    if include_physical
                    else "Catalog expression binding failed; correct the semantic model."
                )
                bindings = None
            required = {n: set((field_names or {}).get(n, ())) for n in datasets}
            if bindings:
                for name in metrics:
                    for parent, field in bindings.metrics[name].dependencies:
                        if parent not in datasets:
                            datasets.append(parent)
                        required.setdefault(parent, set()).add(field)
            edges = {n: relationships[n] for n in relationship_names or ()}
            if full:
                edges = relationships.copy()
            elif relationship_names is None:
                # A self relationship cannot be found by pairing distinct datasets.
                edges.update(
                    {
                        e.name: e
                        for e in catalog.relationships
                        if e.from_dataset == e.to_dataset and e.from_dataset in datasets
                    }
                )
                for start, target in combinations(datasets.copy(), 2):
                    routes, capped = _paths(catalog, start, target)
                    if capped:
                        result["blocking_issues"].append(
                            f"Join path search incomplete: {start} to {target}"
                        )
                    if len(routes) > 1:
                        result["ambiguities"].append(
                            {
                                "datasets": [start, target],
                                "routes": [[e.name for e in r] for r in routes],
                            }
                        )
                        result["blocking_issues"].append(
                            f"Select relationship_names for {start} to {target}."
                        )
                    elif routes and not capped:
                        edges.update({e.name: e for e in routes[0]})
                    elif not capped:
                        result["disconnected"].append([start, target])
            for edge in edges.values():
                for parent, fields in (
                    (edge.from_dataset, edge.from_columns),
                    (edge.to_dataset, edge.to_columns),
                ):
                    if parent not in datasets:
                        datasets.append(parent)
                    required.setdefault(parent, set()).update(fields)
            # Disconnection is informational: separate scalar populations need not join.
            # Exact selected routes are validated with the actual SQL at execution.
            for name in datasets:
                dataset = catalog.datasets[name]
                if bindings:
                    for field in tuple(required.get(name, ())):
                        required[name].update(
                            bindings.field_dependencies.get((name, field), ())
                        )
                selected = sorted(required.get(name, set()) | set(dataset.primary_key))
                try:
                    result["datasets"].append(
                        _dataset_payload(
                            dataset,
                            selected_fields=None if full else selected,
                            include_physical=include_physical,
                        )
                    )
                except ToolException as exc:
                    result["blocking_issues"].append(str(exc))
            for name in metrics:
                payload = _metric_payload(
                    catalog.metrics[name], include_physical=include_physical
                )
                if bindings:
                    payload["dependencies"] = [
                        {"dataset": d, "field": f}
                        for d, f in bindings.metrics[name].dependencies
                    ]
                    if include_physical:
                        payload["expression"] = bindings.metrics[name].expression
                        payload["expression_aliases"] = {
                            d: catalog.datasets[d].source
                            for d, _ in bindings.metrics[name].dependencies
                        }
                result["metrics"].append(payload)
            result["relationships"] = [
                _relationship_payload(e, catalog) for e in edges.values()
            ]
            result["instructions"] = catalog.instructions
            result["definitions_complete"] = not result["blocking_issues"]
            result["catalog_complete"] = full and result["definitions_complete"]
            result["refinement"] = (
                "Definitions cover only the explicit selections. Check every requested business role before SQL. Browse for additional fields or relationships."
            )
    if len(_serialize(result)) > budget:
        # Required definitions are indivisible. Preserve repair diagnostics, never
        # silently drop dependencies while declaring the remainder complete.
        result.update(
            definitions_complete=False,
            catalog_complete=False,
            datasets=[],
            metrics=[],
            relationships=[],
        )
        result.pop("instructions", None)
        result.pop("candidates", None)
        result["omissions"] = [
            "Requested content exceeds the serialized context budget."
        ]
        result["refinement"] = (
            "Request fewer exact definitions; browse by entity kind, dataset and query."
        )
        # Diagnostic lists themselves may be large on disconnected or huge models.
        for name in ("ambiguities", "disconnected", "blocking_issues"):
            while result[name] and len(_serialize(result)) > budget:
                result[name].pop()
        if len(_serialize(result)) > budget:
            result = {
                "mode": "definitions",
                "definitions_complete": False,
                "model_hash": catalog.content_hash,
                "omissions": ["Context budget exceeded, including diagnostics."],
                "refinement": "Request fewer exact names or browse a smaller page.",
            }
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
    if context["definitions_complete"]:
        return (
            "Complete exact catalog definitions (no discovery needed):\n"
            + _serialize(context)
        )
    return (
        render_semantic_overview(catalog)
        + "\nCatalog content hash: "
        + catalog.content_hash
        + "\nUse get_semantic_context for candidates, then exact selected definitions."
    )
