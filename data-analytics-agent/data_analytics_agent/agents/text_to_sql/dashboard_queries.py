"""SQL-owned, parameter-bound calculations over complete named populations.

Definitions are explicit analytical choices. The application compiles their SQL;
neither a chart sample nor a model-written scalar is an execution input.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import math
import json
from typing import Annotated, Literal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import ToolException

from data_analytics_agent.execution import cancellable_query


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


ColumnName = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=200)]


class QueryMeasure(QueryModel):
    name: str = Field(min_length=1, max_length=200)
    aggregation: Literal["sum", "avg", "min", "max", "count", "count_distinct"]
    column: ColumnName | None = None

    @model_validator(mode="after")
    def required_column(self):
        if self.aggregation != "count" and self.column is None:
            raise ValueError("This aggregation requires an explicit input column.")
        return self


class QueryFilter(QueryModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    column: ColumnName
    kind: Literal["category", "date_range"] = "category"


class QueryDefinition(QueryModel):
    input_result_id: str = Field(min_length=1)
    dimensions: list[ColumnName] = Field(default_factory=list, max_length=12)
    measures: list[QueryMeasure] = Field(min_length=1, max_length=20)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_names(self):
        names = [*self.dimensions, *(m.name for m in self.measures)]
        if any(not name or len(name) > 200 for name in names):
            raise ValueError("Query fields require bounded nonempty names.")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Query output names must be unique.")
        ids = [f.id for f in self.filters]
        if len(set(ids)) != len(ids):
            raise ValueError("Query filter IDs must be unique.")
        return self


class QueryExecution(QueryModel):
    # Category values are source data. Whitespace is significant and must survive
    # receipt persistence, unlike human-authored definition labels.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    result_id: str
    thread_id: str
    source_id: str
    definition: QueryDefinition
    filter_values: dict[str, list[str | int | float | bool | None]]
    query: str
    parameters: dict[str, str | int | float | bool | None]


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def _column_type(result, column):
    data_type = pq.read_schema(result.parquet_path).field(column).type
    return data_type.value_type if pa.types.is_dictionary(data_type) else data_type


def validate_date_range_column(result, column):
    """Require a day/timestamp field; period labels do not establish dates."""
    if column not in result.columns:
        raise ValueError("The date range references an unknown saved input column.")
    data_type = _column_type(result, column)
    if pa.types.is_date(data_type) or pa.types.is_timestamp(data_type):
        return
    profile = next(item for item in result.profile.columns if item.name == column)
    if (
        (pa.types.is_string(data_type) or pa.types.is_large_string(data_type))
        and profile.temporal_kind in {"date", "datetime"}
    ):
        return
    raise ValueError("Date ranges require an ISO date or timestamp temporal input field.")


def _decimal_value(value, data_type):
    """Validate exact decimal representability before the driver performs a cast."""
    if type(value) not in (str, int, float):
        raise ValueError("Decimal filter values require an exact numeric value.")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Decimal filter values require an exact numeric value.") from exc
    if not decimal.is_finite():
        raise ValueError("Decimal filter values must be finite.")
    # Do not use normalize/quantize: their default decimal context can round
    # high-precision source values. Inspect the coefficient without arithmetic.
    _, coefficient, exponent = decimal.as_tuple()
    digits = list(coefficient)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    fraction = max(-exponent, 0) if digits else 0
    integral = max(len(digits) + exponent, 0) if digits else 0
    if fraction > data_type.scale or integral > data_type.precision - data_type.scale:
        raise ValueError("The decimal filter value exceeds the saved precision or scale.")
    return str(value)


def _bound_value(data_type, value, parameter):
    if pa.types.is_decimal(data_type):
        return f"CAST(${parameter} AS DECIMAL({data_type.precision},{data_type.scale}))", _decimal_value(value, data_type)
    if pa.types.is_date(data_type):
        return f"CAST(${parameter} AS DATE)", value
    if pa.types.is_timestamp(data_type):
        sql_type = "TIMESTAMPTZ" if data_type.tz else "TIMESTAMP_NS" if data_type.unit == "ns" else "TIMESTAMP"
        return f"CAST(${parameter} AS {sql_type})", value
    return f"${parameter}", value


def _scalar_values(result, column, values):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError("Filters require at most 100 scalar values.")
    data_type = _column_type(result, column)
    for value in values:
        if not isinstance(value, (str, int, float, bool, type(None))) or (
            isinstance(value, str) and len(value) > 500
        ) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("Filters require bounded finite scalar values.")
        if value is None:
            continue
        valid = True
        if pa.types.is_boolean(data_type):
            valid = type(value) is bool
        elif pa.types.is_integer(data_type):
            valid = type(value) is int
        elif pa.types.is_floating(data_type):
            valid = type(value) in (int, float)
        elif pa.types.is_decimal(data_type):
            _decimal_value(value, data_type)
        elif pa.types.is_string(data_type) or pa.types.is_large_string(data_type):
            valid = isinstance(value, str)
        elif pa.types.is_date(data_type) or pa.types.is_timestamp(data_type):
            valid = isinstance(value, str)
            if valid:
                try:
                    if pa.types.is_date(data_type):
                        date.fromisoformat(value)
                    else:
                        datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("Temporal filters require an ISO date or timestamp matching the saved field.") from exc
        elif pa.types.is_null(data_type):
            valid = False
        if not valid:
            raise ValueError("Filter values must match the saved column's scalar type.")
    return data_type


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _execution_id(definition, filter_values, query, parameters, thread_id, source_id):
    payload = {
        "definition": definition.model_dump(mode="json"),
        "filter_values": filter_values,
        "query": query,
        "parameters": parameters,
        "parent_result_ids": [definition.input_result_id],
        "thread_id": thread_id,
        "source_id": source_id,
    }
    return "dashboard-query:" + sha256(_canonical(payload).encode()).hexdigest()


def compile_query(definition, filter_values, results, thread_id, source_id):
    """Validate the entire input and compile SQL with driver-bound parameters."""
    definition = QueryDefinition.model_validate(definition)
    population = results.get(definition.input_result_id, thread_id, source_id=source_id)
    if population.truncated or population.kind == "presentation":
        raise ValueError("Dashboard queries require complete analytical input.")
    if not isinstance(filter_values, dict):
        raise ValueError("Query filter values must be a named mapping.")
    needed = set(definition.dimensions) | {f.column for f in definition.filters}
    needed.update(m.column for m in definition.measures if m.column)
    if needed - set(population.columns):
        raise ValueError("The query references an unknown saved input column.")
    declarations = {f.id: f for f in definition.filters}
    if set(filter_values) - set(declarations):
        raise ValueError("The query names an undeclared filter.")
    schema = pq.read_schema(population.parquet_path)
    for measure in definition.measures:
        if measure.aggregation in {"sum", "avg"} and population.row_count:
            kind = schema.field(measure.column).type
            if not (pa.types.is_integer(kind) or pa.types.is_floating(kind) or pa.types.is_decimal(kind)):
                raise ValueError("Sum and average require a numeric input column.")
    expressions = [quote(name) for name in definition.dimensions]
    for measure in definition.measures:
        column = quote(measure.column) if measure.column else "*"
        aggregate = (
            f"COUNT(DISTINCT {column})" if measure.aggregation == "count_distinct"
            else f"{measure.aggregation.upper()}({column})"
        )
        expressions.append(f"{aggregate} AS {quote(measure.name)}")
    predicates, parameters = [], {}
    for key, values in filter_values.items():
        data_type = _scalar_values(population, declarations[key].column, values)
        if not values:
            continue
        field = declarations[key]
        if field.kind == "date_range":
            if len(values) != 2 or any(not isinstance(v, str) for v in values):
                raise ValueError("A date range requires two ISO dates.")
            start, end = (date.fromisoformat(v) for v in values)
            if start > end:
                raise ValueError("The date range start must not follow its end.")
            validate_date_range_column(population, field.column)
            observed = quote(field.column)
            if pa.types.is_timestamp(data_type) and data_type.tz:
                # DuckDB otherwise uses its session timezone for DATE casts,
                # which can move a source observation to the preceding day.
                timezone_param = f"p{len(parameters)}"
                parameters[timezone_param] = data_type.tz
                observed = f"timezone(${timezone_param}, {observed})"
            keys = []
            for value in values:
                param = f"p{len(parameters)}"
                parameters[param] = value
                keys.append(f"CAST(${param} AS DATE)")
            predicates.append(f"CAST({observed} AS DATE) BETWEEN {keys[0]} AND {keys[1]}")
        else:
            keys = []
            for value in values:
                if value is not None:
                    param = f"p{len(parameters)}"
                    reference, parameters[param] = _bound_value(data_type, value, param)
                    keys.append(reference)
            parts = [f"{quote(field.column)} IN ({', '.join(keys)})"] if keys else []
            if None in values:
                parts.append(f"{quote(field.column)} IS NULL")
            predicates.append("(" + " OR ".join(parts) + ")")
    query = "SELECT " + ", ".join(expressions) + " FROM population"
    if predicates:
        query += " WHERE " + " AND ".join(predicates)
    if definition.dimensions:
        grouped = ", ".join(quote(name) for name in definition.dimensions)
        query += " GROUP BY " + grouped + " ORDER BY " + grouped
    else:
        # Preserve the product's explicit no-population state, including COUNT.
        query += " HAVING COUNT(*) > 0"
    return query, parameters


def execute_dashboard_query(definition, filter_values, *, results, runs, thread_id, source_id, run_id, purpose):
    definition = QueryDefinition.model_validate(definition)
    run = runs.get(run_id)
    if (run.thread_id, run.source_id) != (thread_id, source_id):
        raise ValueError("The dashboard query run has an invalid scope.")
    query, parameters = compile_query(definition, filter_values, results, thread_id, source_id)
    population = results.get(definition.input_result_id, thread_id, source_id=source_id)
    with runs.worker(run_id), duckdb.connect(config={"enable_external_access": False}) as db, cancellable_query(db, runs.cancel_event(run_id), 120):
        db.register("population", pq.read_table(population.parquet_path))
        output = results.save_batches(
            db.execute(query, parameters).to_arrow_reader(8192),
            thread_id=thread_id, source_id=source_id, executed_sql=query,
            originating_question=runs.get(run_id).question, purpose=purpose,
            kind="saved_sql", parent_result_ids=[population.result_id],
            sql_bindings={"population": population.result_id},
            execution_id=_execution_id(definition, filter_values, query, parameters, thread_id, source_id),
        )
    if output.truncated:
        raise ValueError("The dashboard calculation exceeds the complete-result limit.")
    record = QueryExecution(result_id=output.result_id, thread_id=thread_id, source_id=source_id, definition=definition, filter_values=filter_values, query=query, parameters=parameters)
    results.storage.put("dashboard_queries", output.result_id, record)
    return output


def query_execution(result, results):
    """Resolve only application-created receipts matching the immutable result."""
    record = results.storage.get("dashboard_queries", result.result_id, QueryExecution)
    if record is None:
        return None
    if (record.thread_id, record.source_id, record.result_id) != (result.thread_id, result.source_id, result.result_id):
        raise ValueError("The saved query receipt has an invalid scope.")
    query, parameters = compile_query(record.definition, record.filter_values, results, result.thread_id, result.source_id)
    if result.truncated or result.kind != "saved_sql" or result.executed_sql != query or record.query != query or _canonical(record.parameters) != _canonical(parameters) or result.sql_bindings != {"population": record.definition.input_result_id} or result.parent_result_ids != [record.definition.input_result_id] or result.execution_id != _execution_id(record.definition, record.filter_values, query, parameters, result.thread_id, result.source_id):
        raise ValueError("The saved query receipt does not match its evidence.")
    return record


def filter_domain(result, column, *, search="", offset=0, limit=100):
    """Read a bounded domain page from a complete named saved population."""
    if result.truncated or result.kind == "presentation" or column not in result.columns:
        raise ValueError("Filter values require a complete analytical column.")
    if not 0 <= offset or not 1 <= limit <= 100 or len(search) > 200:
        raise ValueError("The filter search page is invalid.")
    field = quote(column)
    with duckdb.connect(config={"enable_external_access": False}) as db:
        db.register("population", pq.read_table(result.parquet_path, columns=[column]))
        query = f"SELECT DISTINCT {field} AS value FROM population"
        params = {"limit": limit + 1, "offset": offset}
        if search:
            query += f" WHERE contains(lower(CAST({field} AS VARCHAR)), lower($search))"
            params["search"] = search
        query += f" ORDER BY {field} NULLS FIRST LIMIT $limit OFFSET $offset"
        values = [row[0] for row in db.execute(query, params).fetchall()]
    return values[:limit], len(values) > limit


def validate_selected_values(result, column, values):
    if result.truncated or result.kind == "presentation" or column not in result.columns:
        raise ValueError("Selections require a complete saved analytical column.")
    data_type = _scalar_values(result, column, values)
    with duckdb.connect(config={"enable_external_access": False}) as db:
        db.register("population", pq.read_table(result.parquet_path, columns=[column]))
        for value in values:
            reference, bound = _bound_value(data_type, value, "value") if value is not None else ("$value", None)
            if not db.execute(f"SELECT 1 FROM population WHERE {quote(column)} IS NOT DISTINCT FROM {reference} LIMIT 1", {"value": bound}).fetchone():
                raise ValueError("A selected value is absent from this saved population.")


def create_execute_dashboard_query_tool(results, runs, *, source_id):
    from data_analytics_agent.agents.text_to_sql.tools import _runtime_context, result_payload
    from data_analytics_agent.handoff import assignment_call_id, record_dataset

    @tool("execute_dashboard_query")
    def execute_dashboard_query_action(definition: QueryDefinition, filter_values: dict[str, list[str | int | float | bool | None]], purpose: str, runtime: ToolRuntime) -> dict:
        """Calculate a reusable dashboard dataset from one complete saved population.

        Declare exact dimensions, named aggregates and filter IDs/columns. Match
        the reviewed metric meaning. This does not refresh warehouse data or join
        datasets. Use the same filter IDs in DashboardSpec. Scalar metric cards
        require no dimensions; charts/tables can group the same complete input.
        """
        context = _runtime_context(runtime)
        if saved := runs.storage.committed(context.run_id, assignment_call_id(runtime)):
            return json.loads(saved)
        if context.source_id != source_id:
            raise ValueError("Source mismatch")
        if reason := runs.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason}
        try:
            output = execute_dashboard_query(definition, filter_values, results=results, runs=runs, thread_id=context.thread_id, source_id=source_id, run_id=context.run_id, purpose=purpose)
        except (ValueError, duckdb.Error) as exc:
            raise ToolException(str(exc)) from exc
        payload = result_payload(output)
        payload["dashboard_query"] = query_execution(output, results).model_dump(mode="json")
        record_dataset(runs, runtime, payload, purpose)
        runs.storage.commit(context.run_id, assignment_call_id(runtime), json.dumps(payload))
        return payload

    execute_dashboard_query_action.handle_tool_error = True
    return execute_dashboard_query_action
