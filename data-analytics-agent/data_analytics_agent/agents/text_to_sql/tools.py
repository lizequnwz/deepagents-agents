"""Source SQL, saved-data SQL, and bounded artifact discovery."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import json
import time
import duckdb
from deepagents.graph import DeepAgentState
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import ToolException
from data_analytics_agent.backends import SQLValidationError, SQLExecutionError
from data_analytics_agent.backends.validation import validate_readonly_sql
from data_analytics_agent.schemas import QueryResult
from data_analytics_agent.execution import cancellable_query


@dataclass(frozen=True)
class AgentContext:
    thread_id: str
    run_id: str
    source_id: str
    question: str


class AnalyticsAgentState(DeepAgentState):
    thread_id: str
    run_id: str
    source_id: str
    question: str


def _runtime_context(runtime):
    state = runtime.state
    return AgentContext(
        thread_id=state["thread_id"],
        run_id=state["run_id"],
        source_id=state["source_id"],
        question=state.get("question", ""),
    )


def result_payload(result):
    return QueryResult(
        result_id=result.result_id,
        executed_sql=result.executed_sql,
        columns=result.columns,
        sample_rows=result.preview,
        profile=result.profile,
        row_count=result.row_count,
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
    ).model_dump(mode="json")


def execute_query(
    *,
    backend,
    source,
    query,
    thread_id,
    result_store,
    originating_question="",
    purpose="",
    cancel=None,
):
    started = time.monotonic()
    result = result_store.save_batches(
        backend.execute_batches(
            query, timeout_seconds=source.limits.timeout_seconds, cancel=cancel
        ),
        thread_id=thread_id,
        source_id=source.source_id,
        executed_sql=query,
        originating_question=originating_question,
        purpose=purpose,
        max_rows=source.limits.max_result_rows,
    )
    return QueryResult(
        **{**result_payload(result), "elapsed_ms": (time.monotonic() - started) * 1000}
    )


def create_execute_sql_tool(source, backend, result_store, run_store):
    @tool
    def execute_sql(query: str, purpose: str, runtime: ToolRuntime) -> dict:
        """Execute source SQL and save typed results. State this step's distinct business purpose."""
        context = _runtime_context(runtime)
        if context.source_id != source.source_id:
            raise ValueError("Source mismatch")
        if saved := run_store.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        if reason := run_store.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason}
        run_store.set_phase(context.run_id, "retrieving_data")
        with run_store.source_worker(context.run_id):
            try:
                result = execute_query(
                    backend=backend,
                    source=source,
                    query=query,
                    thread_id=context.thread_id,
                    result_store=result_store,
                    originating_question=context.question,
                    purpose=purpose,
                    cancel=run_store.cancel_event(context.run_id),
                )
            except (
                SQLValidationError,
                SQLExecutionError,
                TimeoutError,
                ValueError,
            ) as exc:
                raise ToolException(str(exc)) from exc
        payload = result.model_dump(mode="json")
        run_store.storage.commit(
            context.run_id, runtime.tool_call_id, json.dumps(payload)
        )
        return payload

    execute_sql.handle_tool_error = True
    return execute_sql


def create_query_saved_results_tool(results, runs, *, source_id):
    @tool
    def query_saved_results(
        query: str, bindings: dict[str, str], purpose: str, runtime: ToolRuntime
    ) -> dict:
        """Use DuckDB SQL to transform saved datasets. bindings maps SQL aliases to artifact IDs.

        IDs are application evidence handles, not source database tables. This
        queries the saved snapshot; ask execute_sql for fresh source values.
        """
        context = _runtime_context(runtime)
        if saved := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        if reason := runs.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason}
        parsed = validate_readonly_sql(query, dialect="duckdb")
        from sqlglot import exp

        ctes = {cte.alias_or_name for cte in parsed.find_all(exp.CTE)}
        if any(
            not isinstance(table.this, exp.Identifier)
            or table.db
            or table.catalog
            or table.name not in set(bindings) | ctes
            for table in parsed.find_all(exp.Table)
        ):
            raise ToolException(
                "Query only the explicitly bound saved datasets and your CTEs."
            )
        selected = {
            name: results.get(key, context.thread_id, source_id=source_id)
            for name, key in bindings.items()
        }
        if any(item.kind == "presentation" for item in selected.values()):
            raise ToolException(
                "Bind the complete parent dataset instead of a chart presentation artifact."
            )
        try:
            with (
                runs.worker(context.run_id),
                duckdb.connect(config={"enable_external_access": False}) as db,
                cancellable_query(db, runs.cancel_event(context.run_id), 120),
            ):
                import pyarrow.parquet as pq

                for name, result in selected.items():
                    db.register(name, pq.read_table(result.parquet_path))
                reader = db.execute(query).fetch_record_batch(8192)
                output = results.save_batches(
                    reader,
                    thread_id=context.thread_id,
                    source_id=source_id,
                    executed_sql=query,
                    originating_question=context.question,
                    purpose=purpose,
                    kind="saved_sql",
                    parent_result_ids=list(bindings.values()),
                    truncated=any(r.truncated for r in selected.values()),
                )
        except duckdb.Error as exc:
            if runs.cancel_event(context.run_id).is_set():
                raise InterruptedError("Saved-data query stopped.") from exc
            raise ToolException(str(exc)) from exc
        payload = result_payload(output)
        runs.storage.commit(context.run_id, runtime.tool_call_id, json.dumps(payload))
        return payload

    query_saved_results.handle_tool_error = True
    return query_saved_results


def create_list_conversation_results_tool(result_store, *, source_id):
    @tool
    def list_conversation_results(
        runtime: ToolRuntime, offset: int = 0, limit: int = 20
    ) -> dict:
        """List saved datasets and step labels, without rows. Use pagination for older evidence."""
        context = _runtime_context(runtime)
        items = result_store.list_for_conversation(
            context.thread_id, source_id=source_id
        )
        offset = max(0, offset)
        limit = max(1, min(limit, 50))
        return {
            "total": len(items),
            "results": [
                {
                    "result_id": r.result_id,
                    "purpose": r.short_label,
                    "kind": r.kind,
                    "row_count": r.row_count,
                    "columns": r.columns,
                    "truncated": r.truncated,
                    "parent_result_ids": r.parent_result_ids,
                }
                for r in items[offset : offset + limit]
            ],
        }

    return list_conversation_results


def create_inspect_conversation_result_tool(
    result_store, *, source_id, model_sample_rows=10
):
    @tool
    def inspect_conversation_result(
        result_id: str,
        runtime: ToolRuntime,
        columns: list[str] | None = None,
        sample: str = "head",
        filters: dict[str, Any] | None = None,
    ) -> dict:
        """Inspect selected columns with head/random samples, equality filters and full-slice statistics.

        Returns at most ten rows, numeric quantiles, category frequencies,
        missingness and date coverage. Scope identifies the saved filtered slice.
        """
        context = _runtime_context(runtime)
        try:
            result = result_store.get(result_id, context.thread_id, source_id=source_id)
        except KeyError:
            return {
                "ok": False,
                "error": "Unknown saved result. Use list_conversation_results to recover the exact result ID.",
            }
        columns = columns or result.columns
        if not set(columns) <= set(result.columns) or not set(filters or {}) <= set(
            result.columns
        ):
            return {
                "ok": False,
                "error": "Unknown column. Choose from available_columns and retry inspection.",
                "result_id": result_id,
                "available_columns": result.columns,
            }
        if sample not in {"head", "random"}:
            return {"ok": False, "error": "sample must be head or random"}
        quote = lambda value: '"' + value.replace('"', '""') + '"'
        with duckdb.connect() as db:
            db.read_parquet(result.parquet_path).create_view("dataset")
            predicates = []
            values = []
            for name, value in (filters or {}).items():
                predicates.append(f"{quote(name)} IS NOT DISTINCT FROM ?")
                values.append(value)
            where = " WHERE " + " AND ".join(predicates) if predicates else ""
            selection = ", ".join(map(quote, columns))
            relation = db.sql(
                "SELECT " + selection + " FROM dataset" + where, params=values
            )
            count = relation.count("*").fetchone()[0]
            observations = (
                relation.order("random()") if sample == "random" else relation
            )
            rows = (
                observations.limit(min(model_sample_rows, 10))
                .to_arrow_table()
                .to_pylist()
            )
            summaries = {}
            for name, datatype in zip(columns, relation.types):
                field = quote(name)
                nonnull, distinct, minimum, maximum = relation.aggregate(
                    f"count({field}),count(distinct {field}),min({field}),max({field})"
                ).fetchone()
                summary = {
                    "null_count": count - nonnull,
                    "distinct_count": distinct,
                    "minimum": minimum,
                    "maximum": maximum,
                }
                if any(
                    t in str(datatype) for t in ["INT", "FLOAT", "DOUBLE", "DECIMAL"]
                ):
                    summary["quantiles"] = relation.aggregate(
                        f"quantile_cont({field}, [0.25,0.5,0.75])"
                    ).fetchone()[0]
                else:
                    summary["frequencies"] = (
                        relation.aggregate(f"{field},count(*) as frequency", field)
                        .order("frequency desc")
                        .limit(5)
                        .fetchall()
                    )
                summaries[name] = summary
        from pydantic_core import to_jsonable_python

        return to_jsonable_python(
            {
                "result_id": result_id,
                "purpose": result.short_label,
                "executed_sql": result.executed_sql,
                "parent_result_ids": result.parent_result_ids,
                "columns": columns,
                "sample_rows": rows,
                "sample_method": sample,
                "scope": "filtered saved snapshot" if filters else "saved snapshot",
                "filters": filters,
                "row_count": count,
                "truncated": result.truncated,
                "profile": summaries,
            }
        )

    return inspect_conversation_result
