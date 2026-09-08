"""Read-only model-facing tools over one source-bound semantic catalog."""

from __future__ import annotations

from typing import Annotated
from pydantic import Field

from langchain.tools import tool, ToolRuntime
from langchain_core.tools import ToolException

from data_analytics_agent.semantic_context import (
    build_semantic_context,
    _field_payload,
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
        field_names: Annotated[
            dict[str, list[str]] | None,
            Field(
                max_length=20,
                description="Dataset to exact logical field selections. Metric dependencies, primary keys and join keys are included automatically.",
            ),
        ] = None,
    ) -> dict:
        """Get cohesive exact definitions, metric dependencies and declared join paths.

        Provide the business question; optionally refine with exact logical dataset,
        metric and field names (never physical names). Check complete, omissions,
        unresolved references and ambiguity before SQL. Use paginated browsing for
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
        )

    get_semantic_context.handle_tool_error = True
    return get_semantic_context


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
