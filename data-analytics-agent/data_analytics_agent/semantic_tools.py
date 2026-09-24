"""Read-only model-facing tools over one source-bound semantic catalog."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import ToolException
from pydantic import Field

from data_analytics_agent.semantic_context import (
    _field_payload,
    _metric_payload,
    _relationship_payload,
    _serialize,
    build_semantic_context,
)


def create_semantic_context_tool(catalog, *, source_id, dialect, include_physical):
    @tool
    def get_semantic_context(
        question: Annotated[
            str,
            Field(
                max_length=4000,
                description="Business question; may be empty when refining exact selections.",
            ),
        ],
        dataset_names: Annotated[
            list[str] | None,
            Field(
                max_length=10,
                description="Exact logical dataset names, never physical table names.",
            ),
        ] = None,
        metric_names: Annotated[
            list[str] | None,
            Field(max_length=10, description="Exact logical metric names."),
        ] = None,
        relationship_names: Annotated[
            list[str] | None,
            Field(
                max_length=20,
                description="Exact declared relationships for the chosen route, including self joins. Empty means no joins requested.",
            ),
        ] = None,
        field_names: Annotated[
            dict[str, list[str]] | None,
            Field(
                max_length=20,
                description="Dataset to exact logical field selections. Metric dependencies, primary keys and join keys are included automatically.",
            ),
        ] = None,
    ) -> dict:
        """Discover candidates or resolve exact definitions and declared join paths.

        Provide the business question; optionally refine with exact logical dataset,
        metric, field and relationship names (never physical names). Question-only
        calls return candidates, not SQL context. Exact calls return only selected
        fields, keys and metric dependencies. Check definitions_complete and
        blocking_issues; question coverage always requires your review. Browse for
        unknown vocabulary. This reads metadata only, never source values.
        """
        return build_semantic_context(
            catalog,
            source_id=source_id,
            dialect=dialect,
            include_physical=include_physical,
            question=question,
            dataset_names=dataset_names,
            metric_names=metric_names,
            field_names=field_names,
            relationship_names=relationship_names,
        )

    get_semantic_context.handle_tool_error = True
    return get_semantic_context


def create_browse_semantic_tool(catalog, *, include_physical=False):
    @tool
    def browse_semantic_model(
        entity_kind: Literal[
            "dataset", "field", "metric", "relationship", "example"
        ] = "dataset",
        dataset_name: str | None = None,
        query: str = "",
        time_only: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> dict:
        """Browse/search one semantic role by page, with a 6,000-character response budget.

        Search measures as metrics; grouping/filter concepts as fields; dates as
        fields with time_only. Dataset filters narrow fields and relationships.
        Examples are curated question/context examples, NOT verified SQL.
        Use separate searches for each part of a business question, then request
        exact definitions with get_semantic_context. No source values are read.
        """
        if dataset_name and dataset_name not in catalog.datasets:
            raise ToolException("Unknown logical dataset; browse datasets first.")
        offset, limit = max(0, offset), max(1, min(limit, 50))
        if entity_kind == "field":
            items = [
                dict(
                    dataset=d.name,
                    **_field_payload(f, include_physical=include_physical),
                )
                for d in catalog.datasets.values()
                if not dataset_name or d.name == dataset_name
                for f in d.fields.values()
                if not time_only or f.is_time
            ]
        elif entity_kind == "metric":
            items = [
                _metric_payload(m, include_physical=include_physical)
                for m in catalog.metrics.values()
            ]
        elif entity_kind == "relationship":
            items = [
                _relationship_payload(r, catalog)
                for r in catalog.relationships
                if not dataset_name or dataset_name in (r.from_dataset, r.to_dataset)
            ]
        elif entity_kind == "example":
            items = (
                [{"name": catalog.name, "example": e} for e in catalog.examples]
                if not dataset_name
                else []
            )
            for d in catalog.datasets.values():
                if dataset_name and d.name != dataset_name:
                    continue
                items.extend({"name": d.name, "example": e} for e in d.examples)
                items.extend(
                    {"name": f"{d.name}.{f.name}", "example": e}
                    for f in d.fields.values()
                    for e in f.examples
                )
            if not dataset_name:
                items.extend(
                    {"name": m.name, "example": e}
                    for m in catalog.metrics.values()
                    for e in m.examples
                )
                items.extend(
                    {"name": r.name, "example": e}
                    for r in catalog.relationships
                    for e in r.examples
                )
        else:
            items = [
                {
                    "name": d.name,
                    "description": d.description,
                    "field_count": len(d.fields),
                }
                for d in catalog.datasets.values()
                if not dataset_name or d.name == dataset_name
            ]
        if query.strip() and entity_kind in {"dataset", "field", "metric"}:
            # Search all eligible entities so pagination is not limited to the first top-k.
            from data_analytics_agent.semantic import (
                _normalize_search_text,
                _score_entity,
            )

            scored = []
            for item in items:
                entity = (
                    catalog.datasets[item["dataset"]].fields[item["name"]]
                    if entity_kind == "field"
                    else (
                        catalog.metrics if entity_kind == "metric" else catalog.datasets
                    )[item["name"]]
                )
                match = _score_entity(
                    _normalize_search_text(query),
                    kind=entity_kind,
                    name=entity.name,
                    parent_dataset=item.get("dataset"),
                    description=entity.description,
                    synonyms=entity.synonyms,
                )
                if match:
                    scored.append(
                        (match.score, dict(item, match_reason=match.match_reason))
                    )
            items = [
                item
                for _, item in sorted(
                    scored,
                    key=lambda pair: (
                        -pair[0],
                        pair[1].get("dataset", ""),
                        pair[1]["name"],
                    ),
                )
            ]
        elif query.strip():
            terms = query.casefold().split()
            items = [
                item
                for item in items
                if any(t in _serialize(item).casefold() for t in terms)
            ]
        result = {
            "items": [],
            "total": len(items),
            "offset": offset,
            "next_offset": None,
            "omissions": [],
        }
        for index in range(offset, min(len(items), offset + limit)):
            result["items"].append(items[index])
            result["next_offset"] = index + 1 if index + 1 < len(items) else None
            if len(_serialize(result)) > 6000:
                result["items"].pop()
                if not result["items"]:
                    result["omissions"] = [
                        "One definition exceeds the page budget; narrow the model definition before using it."
                    ]
                else:
                    result["next_offset"] = index
                break
        return result

    browse_semantic_model.handle_tool_error = True
    return browse_semantic_model


def create_lookup_values_tool(
    catalog, source, backend, results, runs, *, require_approval=False
):
    from sqlglot import exp

    from data_analytics_agent.agents.text_to_sql.tools import (
        _runtime_context,
        execute_query,
    )

    @tool
    def lookup_values(
        dataset_name: str, field_name: str, runtime: ToolRuntime, search: str = ""
    ) -> dict:
        """Look up actual category values and counts for one exact semantic field.

        Source-value discovery for data-bearing assignments only. Uses a
        bounded generated query, not arbitrary identifiers or user SQL.
        """

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
