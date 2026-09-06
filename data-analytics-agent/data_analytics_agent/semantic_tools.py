"""Read-only model-facing tools over one source-bound semantic catalog."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain.tools import tool, ToolRuntime
from langchain_core.tools import ToolException
from pydantic import Field

from data_analytics_agent.semantic import (
    SemanticCatalog,
    SemanticDataset,
    SemanticField,
    SemanticMetric,
    SemanticRelationship,
)

MAX_ENTITY_DATASETS = 10
MAX_ENTITY_METRICS = 10
MAX_RELATIONSHIP_DATASETS = 10
MAX_AVAILABLE_FIELD_NAMES = 25
MAX_SEARCH_RESULTS = 10
MAX_DATASETS_WITH_ALL_FIELDS = 2


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


def create_semantic_tools(
    catalog: SemanticCatalog,
    *,
    include_physical: bool,
) -> list[Any]:
    """Create the three bounded tools for one fixed catalog projection."""

    @tool
    def search_semantic_model(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description="Business terms to match against logical metadata.",
            ),
        ],
        entity_kinds: Annotated[
            list[Literal["dataset", "field", "metric"]] | None,
            Field(
                max_length=3,
                description=(
                    "Optional result kinds. For initial selection, prefer "
                    "['dataset', 'metric']; include 'field' only when needed."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SEARCH_RESULTS,
                description="Maximum matches to return, from 1 through 10.",
            ),
        ] = 5,
    ) -> dict[str, Any]:
        """Find OSI datasets, fields, and metrics relevant to business terms.

        Results are compact candidates, not complete definitions. Use
        get_semantic_entities with exact returned names before analysis.
        """

        try:
            matches = catalog.search(
                query,
                entity_kinds=entity_kinds,
                limit=limit,
            )
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        return {
            "matches": [
                {
                    "kind": match.kind,
                    "name": match.name,
                    "parent_dataset": match.parent_dataset,
                    "description": match.description,
                    "matched_text": match.matched_text,
                    "match_reason": match.match_reason,
                    "score": match.score,
                }
                for match in matches
            ],
            "model_hash": catalog.content_hash,
        }

    @tool
    def get_semantic_entities(
        dataset_names: Annotated[
            list[str] | None,
            Field(
                max_length=MAX_ENTITY_DATASETS,
                description=(
                    "Up to 10 exact logical dataset names from the overview or "
                    "semantic search."
                ),
            ),
        ] = None,
        metric_names: Annotated[
            list[str] | None,
            Field(
                max_length=MAX_ENTITY_METRICS,
                description="Up to 10 exact logical metric names.",
            ),
        ] = None,
        field_names: Annotated[
            dict[str, list[str]] | None,
            Field(
                description=(
                    "Optional dataset-to-logical-field-name mapping. Use "
                    "snake_case logical names such as invoice_id, never "
                    "physical names such as InvoiceId. Required for every "
                    "dataset when more than two datasets are requested."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Fetch exact OSI definitions for selected datasets and metrics.

        Request at most 10 datasets and 10 metrics. For one or two datasets,
        omit field_names to receive every declared field. For more datasets,
        provide logical snake_case field names for every dataset, not physical
        column names.
        """

        selected_datasets = dataset_names or []
        selected_metrics = metric_names or []
        if not selected_datasets and not selected_metrics:
            raise ToolException("Provide at least one exact dataset or metric name.")
        if len(selected_datasets) > MAX_ENTITY_DATASETS:
            raise ToolException(
                f"Request at most {MAX_ENTITY_DATASETS} datasets per call."
            )
        if len(selected_metrics) > MAX_ENTITY_METRICS:
            raise ToolException(
                f"Request at most {MAX_ENTITY_METRICS} metrics per call."
            )
        if len(selected_datasets) > MAX_DATASETS_WITH_ALL_FIELDS:
            if field_names is None:
                raise ToolException(
                    "field_names is required when requesting more than "
                    f"{MAX_DATASETS_WITH_ALL_FIELDS} datasets. Include every "
                    "requested dataset and list only the logical fields needed; "
                    "use an empty list when only dataset metadata is needed."
                )
            missing_field_selections = [
                name for name in selected_datasets if name not in field_names
            ]
            if missing_field_selections:
                raise ToolException(
                    "field_names must include every requested dataset when more "
                    f"than {MAX_DATASETS_WITH_ALL_FIELDS} datasets are requested. "
                    f"Missing entries: {missing_field_selections!r}."
                )
        unknown_datasets = [
            name for name in selected_datasets if name not in catalog.datasets
        ]
        unknown_metrics = [
            name for name in selected_metrics if name not in catalog.metrics
        ]
        if unknown_datasets or unknown_metrics:
            raise ToolException(
                "Unknown exact semantic names: "
                f"datasets={unknown_datasets!r}, metrics={unknown_metrics!r}. "
                "Use search_semantic_model first."
            )
        unexpected_field_parents = sorted(
            set(field_names or {}) - set(selected_datasets)
        )
        if unexpected_field_parents:
            raise ToolException(
                "field_names contains datasets not requested in dataset_names: "
                f"{unexpected_field_parents!r}."
            )
        return {
            "datasets": [
                _dataset_payload(
                    catalog.datasets[name],
                    selected_fields=(
                        (field_names or {}).get(name)
                        if field_names is not None
                        else None
                    ),
                    include_physical=include_physical,
                )
                for name in selected_datasets
            ],
            "metrics": [
                _metric_payload(
                    catalog.metrics[name],
                    include_physical=include_physical,
                )
                for name in selected_metrics
            ],
            "model_hash": catalog.content_hash,
        }

    @tool
    def get_relationships(
        dataset_names: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=MAX_RELATIONSHIP_DATASETS,
                description="One to 10 exact logical dataset names.",
            ),
        ],
        target_dataset: Annotated[
            str | None,
            Field(
                description=(
                    "Optional exact logical target dataset for shortest-path discovery."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Inspect declared relationships and optionally find a join path.

        One selected dataset returns its adjacent relationships. Multiple
        selected datasets return only relationships whose endpoints are both
        selected. target_dataset additionally returns an exact shortest path.
        No relationship or join is inferred from names or descriptions.
        """

        if not dataset_names:
            raise ToolException("Provide at least one exact dataset name.")
        if len(dataset_names) > MAX_RELATIONSHIP_DATASETS:
            raise ToolException(
                f"Request at most {MAX_RELATIONSHIP_DATASETS} datasets per call."
            )
        requested = [*dataset_names]
        if target_dataset is not None:
            requested.append(target_dataset)
        unknown = [name for name in requested if name not in catalog.datasets]
        if unknown:
            raise ToolException(
                f"Unknown exact dataset names: {unknown!r}. "
                "Use search_semantic_model first."
            )
        adjacent = catalog.adjacent_relationships(dataset_names)
        path = (
            catalog.shortest_path(dataset_names, target_dataset)
            if target_dataset is not None
            else None
        )
        path_dataset_names = sorted(
            {
                dataset_name
                for relationship in path or ()
                for dataset_name in (
                    relationship.from_dataset,
                    relationship.to_dataset,
                )
            }
        )
        return {
            "relationships": [
                _relationship_payload(relationship) for relationship in adjacent
            ],
            "target_dataset": target_dataset,
            "path_found": target_dataset is None or path is not None,
            "path": (
                [_relationship_payload(relationship) for relationship in path]
                if path is not None
                else None
            ),
            "path_dataset_names": path_dataset_names,
            "model_hash": catalog.content_hash,
        }

    for semantic_tool in (
        search_semantic_model,
        get_semantic_entities,
        get_relationships,
    ):
        semantic_tool.handle_tool_error = True
    return [search_semantic_model, get_semantic_entities, get_relationships]


def create_browse_semantic_tool(catalog, *, include_physical=False):
    @tool
    def browse_semantic_model(
        dataset_name: str | None = None, offset: int = 0, limit: int = 25
    ) -> dict:
        """Browse datasets or fields by page when exact search terms are unknown."""
        offset = max(0, offset)
        limit = max(1, min(limit, 50))
        if dataset_name:
            dataset = catalog.datasets.get(dataset_name)
            if dataset is None:
                raise ToolException("Unknown dataset; browse datasets first.")
            items = [
                _field_payload(field, include_physical=include_physical)
                for field in dataset.fields.values()
            ]
        else:
            items = [
                {
                    "name": dataset.name,
                    "description": dataset.description,
                    "field_count": len(dataset.fields),
                }
                for dataset in catalog.datasets.values()
            ]
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(items) else None,
        }

    browse_semantic_model.handle_tool_error = True
    return browse_semantic_model


def create_lookup_values_tool(
    catalog, source, backend, results, runs, *, require_approval=False
):
    from data_analytics_agent.agents.text_to_sql.tools import (
        _runtime_context,
        execute_query,
    )
    from sqlglot import exp

    @tool
    def lookup_values(
        dataset_name: str, field_name: str, runtime: ToolRuntime, search: str = ""
    ) -> dict:
        """Look up actual category values and counts for one exact semantic field.

        Source-value discovery for data-bearing assignments only. Uses a
        bounded generated query, not arbitrary identifiers or user SQL.
        """
        import json

        context = _runtime_context(runtime)
        if committed := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(committed)
        if reason := runs.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason}
        dataset = catalog.datasets[dataset_name]
        field = dataset.fields[field_name]
        literal = exp.Literal.string("%" + search.lower() + "%").sql(
            dialect=source.dialect
        )
        table = exp.to_table(dataset.source).sql(dialect=source.dialect, identify=True)
        query = (
            f"SELECT {field.expression} AS value, COUNT(*) AS frequency FROM {table}"
        )
        if search:
            query += f" WHERE LOWER(CAST({field.expression} AS VARCHAR)) LIKE {literal}"
        query += f" GROUP BY {field.expression} ORDER BY frequency DESC, value LIMIT 10"
        if require_approval:
            return {
                "query": query,
                "requires_sql_execution": True,
                "instruction": "Execute this generated query with execute_sql so the configured SQL review applies.",
            }
        runs.set_phase(context.run_id, "retrieving_data")
        with runs.source_worker(context.run_id):
            result = execute_query(
                backend=backend,
                source=source,
                query=query,
                thread_id=context.thread_id,
                result_store=results,
                originating_question=context.question,
                purpose=f"Value lookup: {dataset_name}.{field_name}",
                cancel=runs.cancel_event(context.run_id),
            )
        response = result.model_dump(mode="json")
        runs.storage.commit(context.run_id, runtime.tool_call_id, json.dumps(response))
        return response

    return lookup_values
