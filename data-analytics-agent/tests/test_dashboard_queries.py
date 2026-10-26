"""Exercise the deterministic dashboard calculation against saved typed data."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from types import SimpleNamespace

import pyarrow as pa
import pytest
from pydantic import ValidationError

from data_analytics_agent.agents.text_to_sql.dashboard_queries import (
    QueryDefinition,
    compile_query,
    create_execute_dashboard_query_tool,
    execute_dashboard_query,
    filter_domain,
    query_execution,
    validate_date_range_column,
    validate_selected_values,
)
from data_analytics_agent.approvals import _extract_approval, decisions_to_command
from data_analytics_agent.schemas import Decision
from data_analytics_agent.stores import StoreNotFound


@pytest.fixture
def population(workspace):
    w = workspace
    rows = [
        {"region": "North", "amount": Decimal("10.00"), "quantity": 1, "active": True, "day": date(2026, 1, 1)},
        {"region": "North", "amount": None, "quantity": 2, "active": False, "day": date(2026, 1, 31)},
        {"region": "South", "amount": Decimal("20.00"), "quantity": 3, "active": True, "day": date(2026, 2, 1)},
        {"region": None, "amount": Decimal("5.00"), "quantity": 4, "active": None, "day": date(2026, 2, 28)},
        {"region": "x'); DROP TABLE population; --", "amount": Decimal("-2.00"), "quantity": 5, "active": False, "day": date(2026, 3, 1)},
    ]
    w.population = w.results.save(
        columns=list(rows[0]), rows=rows, thread_id=w.thread, source_id="test",
        purpose="Complete population, one observation per row",
    )
    w.definition = QueryDefinition(
        input_result_id=w.population.result_id,
        measures=[{"name": "total", "aggregation": "sum", "column": "amount"}],
        filters=[
            {"id": "region", "column": "region"},
            {"id": "quantity", "column": "quantity"},
            {"id": "active", "column": "active"},
            {"id": "day", "column": "day", "kind": "date_range"},
        ],
    )
    return w


def execute(w, definition=None, values=None):
    return execute_dashboard_query(
        definition or w.definition, values or {}, results=w.results,
        runs=w.runs, thread_id=w.thread, source_id="test", run_id=w.run,
        purpose="Check the explicit dashboard calculation",
    )


def test_scalar_and_grouped_measures_preserve_population_and_nulls(population):
    w = population
    definition = QueryDefinition.model_validate({**w.definition.model_dump(), "measures": [
        {"name": "total", "aggregation": "sum", "column": "amount"},
        {"name": "average", "aggregation": "avg", "column": "amount"},
        {"name": "population", "aggregation": "count"},
        {"name": "observed", "aggregation": "count", "column": "amount"},
        {"name": "regions", "aggregation": "count_distinct", "column": "region"},
        {"name": "minimum", "aggregation": "min", "column": "amount"},
        {"name": "maximum", "aggregation": "max", "column": "amount"},
    ]})
    result = execute(w, definition)
    row = result.read_rows(1)[0]
    assert row == {"total": Decimal("33.00"), "average": 8.25, "population": 5,
                   "observed": 4, "regions": 3, "minimum": Decimal("-2.00"),
                   "maximum": Decimal("20.00")}
    assert result.parent_result_ids == [w.population.result_id]
    assert result.sql_bindings == {"population": w.population.result_id}
    assert result.execution_id.startswith("dashboard-query:")
    grouped = execute(w, definition.model_copy(update={"dimensions": ["region"]}))
    north = next(row for row in grouped.read_rows(10) if row["region"] == "North")
    assert north["total"] == 10 and north["average"] == 10
    assert north["population"] == 2 and north["observed"] == 1
    assert any(row["region"] is None for row in grouped.read_rows(10))
    assert query_execution(result, w.results).definition == definition


def test_all_null_numeric_column_remains_numeric(population):
    w = population
    table = pa.table({"amount": pa.array([None, None], type=pa.float64())})
    saved = w.results.save_batches(table.to_reader(), thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id, measures=[
        {"name": "total", "aggregation": "sum", "column": "amount"},
        {"name": "average", "aggregation": "avg", "column": "amount"},
        {"name": "observed", "aggregation": "count", "column": "amount"},
        {"name": "population", "aggregation": "count"},
    ])
    assert execute(w, definition).read_rows(1) == [
        {"total": None, "average": None, "observed": 0, "population": 2}
    ]


def test_decimal_domain_values_bind_without_float_conversion(population):
    w = population
    precise = Decimal("9007199254740993.01")
    table = pa.table({
        "price": pa.array([precise, Decimal("0.10"), None], type=pa.decimal128(38, 2)),
        "quantity": [7, 2, 100],
    })
    saved = w.results.save_batches(table.to_reader(), thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id,
        measures=[{"name": "quantity", "aggregation": "sum", "column": "quantity"}],
        filters=[{"id": "price", "column": "price"}])
    # The product serializes Decimal category options as exact strings.
    assert precise in filter_domain(saved, "price")[0]
    for selected, expected in ((str(precise), 7), ("0.10", 2), (0.1, 2)):
        result = execute(w, definition, {"price": [selected]})
        assert result.read_rows(1) == [{"quantity": expected}]
        receipt = query_execution(result, w.results)
        assert receipt.parameters == {"p0": str(selected)}
        assert "CAST($p0 AS DECIMAL(38,2))" in receipt.query
        validate_selected_values(saved, "price", [selected])
    for bad in ("NaN", "Infinity", "0.101", "1' OR TRUE --", True, "1e99"):
        with pytest.raises(ValueError, match="[Dd]ecimal"):
            execute(w, definition, {"price": [bad]})


def test_date_timestamp_categories_and_receipts_preserve_iso_values(population):
    w = population
    for column, data_type, values in (
        ("day", pa.date32(), [date(2026, 1, 1), date(2026, 1, 2)]),
        ("moment", pa.timestamp("us"), [datetime(2026, 1, 1, 12, 5, 6, 123456), datetime(2026, 1, 2)]),
        ("instant", pa.timestamp("us", tz="UTC"), [datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)]),
    ):
        saved = w.results.save_batches(pa.table({column: pa.array(values, type=data_type), "n": [7, 9]}).to_reader(),
            thread_id=w.thread, source_id="test")
        definition = QueryDefinition(input_result_id=saved.result_id,
            measures=[{"name": "n", "aggregation": "sum", "column": "n"}],
            filters=[{"id": "when", "column": column}])
        selected = values[0].isoformat()
        result = execute(w, definition, {"when": [selected]})
        assert result.read_rows(1) == [{"n": 7}]
        assert query_execution(result, w.results).parameters == {"p0": selected}
        validate_selected_values(saved, column, [selected])
        with pytest.raises(ValueError, match="ISO"):
            execute(w, definition, {"when": ["not a date"]})


def test_all_null_typed_dates_and_empty_numeric_population_keep_their_schema(population):
    w = population
    for dates in ([None, None], []):
        table = pa.table({"day": pa.array(dates, type=pa.date32()), "n": pa.array([7] * len(dates), type=pa.int64())})
        saved = w.results.save_batches(table.to_reader(), thread_id=w.thread, source_id="test")
        assert next(item for item in saved.profile.columns if item.name == "day").temporal_kind is None
        validate_date_range_column(saved, "day")
        definition = QueryDefinition(input_result_id=saved.result_id,
            measures=[{"name": "n", "aggregation": "sum", "column": "n"}],
            filters=[{"id": "day", "column": "day", "kind": "date_range"}])
        assert execute(w, definition, {"day": ["2026-01-01", "2026-01-31"]}).row_count == 0


def test_timestamp_date_range_uses_the_saved_timezone_day(population):
    w = population
    source_time = datetime(2026, 1, 1, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    table = pa.table({"moment": pa.array([source_time], type=pa.timestamp("us", tz="Asia/Kolkata")), "n": [7]})
    saved = w.results.save_batches(table.to_reader(), thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id,
        measures=[{"name": "n", "aggregation": "sum", "column": "n"}],
        filters=[{"id": "day", "column": "moment", "kind": "date_range"}])
    result = execute(w, definition, {"day": ["2026-01-01", "2026-01-01"]})
    assert result.read_rows(1) == [{"n": 7}]


@pytest.mark.parametrize("values", [[1] * 101, [float("nan")], [float("inf")], ["x" * 501], [{"sql": "SELECT 1"}]])
def test_filter_bounds_reject_non_scalar_or_excessive_input(population, values):
    with pytest.raises(ValueError):
        execute(population, values={"quantity": values})


def test_category_whitespace_is_data_and_survives_receipt(population):
    w = population
    saved = w.results.save(columns=["region", "n"], rows=[{"region": " North ", "n": 7}, {"region": "North", "n": 9}],
        thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id,
        measures=[{"name": "n", "aggregation": "sum", "column": "n"}],
        filters=[{"id": "region", "column": "region"}])
    result = execute(w, definition, {"region": [" North "]})
    assert result.read_rows(1) == [{"n": 7}]
    receipt = query_execution(result, w.results)
    assert receipt.filter_values == {"region": [" North "]}
    assert receipt.parameters == {"p0": " North "}


@pytest.mark.parametrize("key,value,total,kind", [
    ("quantity", 1, 10, int), ("active", True, 30, bool),
    ("active", False, -2, bool), ("region", None, 5, type(None)),
])
def test_typed_category_parameters_select_the_correct_rows(population, key, value, total, kind):
    w = population
    result = execute(w, values={key: [value]})
    assert result.read_rows(1)[0]["total"] == total
    receipt = query_execution(result, w.results)
    assert type(receipt.filter_values[key][0]) is kind
    if value is not None:
        assert type(receipt.parameters["p0"]) is kind


@pytest.mark.parametrize("key,value", [
    ("quantity", True), ("quantity", 1.0), ("quantity", "1"),
    ("active", 1), ("active", "true"), ("region", 1),
])
def test_filters_reject_implicit_scalar_type_coercion(population, key, value):
    w = population
    with pytest.raises(ValueError, match="scalar type"):
        execute(w, values={key: [value]})
    with pytest.raises(ValueError, match="scalar type"):
        validate_selected_values(w.population, key, [value])


def test_date_range_is_inclusive_and_bound(population):
    w = population
    result = execute(w, values={"day": ["2026-01-01", "2026-02-01"]})
    assert result.read_rows(1)[0]["total"] == 30
    receipt = query_execution(result, w.results)
    assert receipt.parameters == {"p0": "2026-01-01", "p1": "2026-02-01"}
    assert "2026-01-01" not in receipt.query
    assert "BETWEEN CAST($p0 AS DATE) AND CAST($p1 AS DATE)" in receipt.query
    for values in (["2026-03-01", "2026-01-01"], ["not-a-date", "2026-03-01"], ["2026-01-01"], [1, 2]):
        with pytest.raises(ValueError):
            execute(w, values={"day": values})
    non_temporal = QueryDefinition.model_validate({**w.definition.model_dump(),
        "filters": [{"id": "day", "column": "region", "kind": "date_range"}]
    })
    with pytest.raises(ValueError, match="temporal"):
        execute(w, non_temporal.model_dump(), {"day": ["2026-01-01", "2026-01-31"]})


@pytest.mark.parametrize("value", ["2026-01", "2026-Q1", "2026"])
def test_date_ranges_do_not_infer_dates_from_period_labels(population, value):
    w = population
    saved = w.results.save(columns=["period", "n"], rows=[{"period": value, "n": 7}],
        thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id,
        measures=[{"name": "n", "aggregation": "sum", "column": "n"}],
        filters=[{"id": "day", "column": "period", "kind": "date_range"}])
    with pytest.raises(ValueError, match="ISO date or timestamp"):
        execute(w, definition, {"day": ["2026-01-01", "2026-01-31"]})


def test_empty_selection_returns_explicit_no_population(population):
    w = population
    for dimensions in ([], ["region"]):
        definition = w.definition.model_copy(update={"dimensions": dimensions})
        result = execute(w, definition, {"region": ["no such region"]})
        assert result.row_count == 0 and result.read_rows(10) == []
        assert query_execution(result, w.results) is not None
    count = QueryDefinition(input_result_id=w.population.result_id,
        measures=[{"name": "count", "aggregation": "count"}],
        filters=[{"id": "region", "column": "region"}])
    assert execute(w, count, {"region": ["missing"]}).row_count == 0


def test_strings_and_quoted_identifiers_are_data_not_sql(population):
    w = population
    attack = "x'); DROP TABLE population; --"
    result = execute(w, values={"region": [attack]})
    assert result.read_rows(1)[0]["total"] == -2
    receipt = query_execution(result, w.results)
    assert attack not in receipt.query and receipt.parameters == {"p0": attack}
    column = 'odd"name); SELECT * FROM secret; --'
    alias = 'sum" FROM secret; --'
    saved = w.results.save(columns=[column], rows=[{column: 7}], thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id,
        measures=[{"name": alias, "column": column, "aggregation": "sum"}])
    assert execute(w, definition).read_rows(1) == [{alias: 7}]
    assert execute(w).read_rows(1)[0]["total"] == 33


def test_source_column_whitespace_is_an_exact_identifier(population):
    w = population
    saved = w.results.save(columns=[" amount ", "amount", " region ", "region"], rows=[
        {" amount ": 7, "amount": 900, " region ": " North ", "region": "South"},
    ], thread_id=w.thread, source_id="test")
    definition = QueryDefinition(input_result_id=saved.result_id, dimensions=[" region "],
        measures=[{"name": "total", "aggregation": "sum", "column": " amount "}],
        filters=[{"id": "region", "column": " region "}])
    result = execute(w, definition, {"region": [" North "]})
    assert result.read_rows(1) == [{" region ": " North ", "total": 7}]
    assert query_execution(result, w.results).definition == definition


def test_incomplete_and_presentation_inputs_are_rejected(population):
    w = population
    for attributes in ({"truncated": True}, {"kind": "presentation"}):
        modified = w.population.model_copy(update=attributes)
        w.results._items[modified.result_id] = modified
        with pytest.raises(ValueError, match="complete analytical"):
            execute(w)
    w.results._items[w.population.result_id] = w.population
    for definition in (
        w.definition.model_copy(update={"dimensions": ["missing"]}),
        {**w.definition.model_dump(), "filters": [{"id": "bad", "column": "missing"}]},
    ):
        with pytest.raises(ValueError, match="unknown saved input column"):
            execute(w, definition)
    with pytest.raises(ValueError, match="undeclared"):
        execute(w, values={"missing": ["North"]})
    invalid_sum = QueryDefinition(input_result_id=w.population.result_id,
        measures=[{"name": "total", "column": "region", "aggregation": "sum"}])
    with pytest.raises(ValueError, match="numeric"):
        execute(w, invalid_sum)


def test_scope_checks_apply_to_input_run_and_receipt(population):
    w = population
    foreign = w.results.save(columns=["amount"], rows=[{"amount": 900}], thread_id="other", source_id="test")
    with pytest.raises(StoreNotFound):
        execute(w, w.definition.model_copy(update={"input_result_id": foreign.result_id}))
    with pytest.raises(StoreNotFound):
        compile_query(w.definition, {}, w.results, w.thread, "test_alt")
    other_run = w.runs.create("other", "test", "Other question")
    with pytest.raises(ValueError, match="scope"):
        execute_dashboard_query(w.definition, {}, results=w.results, runs=w.runs,
            thread_id=w.thread, source_id="test", run_id=other_run, purpose="wrong run")
    result = execute(w)
    receipt = query_execution(result, w.results)
    w.storage.put("dashboard_queries", result.result_id, receipt.model_copy(update={"thread_id": "other"}))
    with pytest.raises(ValueError, match="scope"):
        query_execution(result, w.results)


@pytest.mark.parametrize("tamper", ["parameter", "filter_and_parameter", "definition", "parent", "binding", "query", "digest"])
def test_receipt_tampering_cannot_change_saved_execution(population, tamper):
    w = population
    result = execute(w, values={"active": [True]})
    receipt = query_execution(result, w.results)
    changed_result = result
    if tamper == "parameter":
        receipt = receipt.model_copy(update={"parameters": {"p0": 1}})
    elif tamper == "filter_and_parameter":
        receipt = receipt.model_copy(update={"filter_values": {"active": [False]}, "parameters": {"p0": False}})
    elif tamper == "definition":
        receipt = receipt.model_copy(update={"definition": receipt.definition.model_copy(update={"filters": []}), "filter_values": {}, "parameters": {}})
    elif tamper == "parent":
        changed_result = result.model_copy(update={"parent_result_ids": []})
    elif tamper == "binding":
        changed_result = result.model_copy(update={"sql_bindings": {"population": "other"}})
    elif tamper == "query":
        changed_result = result.model_copy(update={"executed_sql": "SELECT 999 AS total"})
    else:
        changed_result = result.model_copy(update={"execution_id": None})
    w.storage.put("dashboard_queries", result.result_id, receipt)
    with pytest.raises(ValueError, match="match its evidence"):
        query_execution(changed_result, w.results)


def test_filter_domain_is_bounded_literal_and_preserves_types(population):
    w = population
    values, more = filter_domain(w.population, "region", limit=2)
    assert values[0] is None and len(values) == 2 and more
    next_values, next_more = filter_domain(w.population, "region", offset=2, limit=2)
    assert set(values + next_values) == {None, "North", "South", "x'); DROP TABLE population; --"}
    assert not next_more
    assert filter_domain(w.population, "region", search="DROP TABLE")[0] == ["x'); DROP TABLE population; --"]
    assert filter_domain(w.population, "quantity")[0] == [1, 2, 3, 4, 5]
    assert filter_domain(w.population, "active")[0] == [None, False, True]
    validate_selected_values(w.population, "active", [False, None])
    with pytest.raises(ValueError, match="absent"):
        validate_selected_values(w.population, "quantity", [900])
    for kwargs in ({"offset": -1}, {"limit": 101}, {"search": "x" * 201}):
        with pytest.raises(ValueError):
            filter_domain(w.population, "region", **kwargs)
    with pytest.raises(ValueError):
        filter_domain(w.population, "missing")


def test_tool_schema_and_configured_review_are_constructible(population, test_settings):
    w = population
    tool = create_execute_dashboard_query_tool(w.results, w.runs, source_id="test")
    schema = tool.tool_call_schema.model_json_schema()
    assert set(schema["required"]) == {"definition", "filter_values", "purpose"}
    assert "runtime" not in schema["properties"]
    source = test_settings.load_catalog().get("test")
    arguments = {"definition": w.definition.model_dump(), "filter_values": {"active": [True]}, "purpose": "Approved saved population"}
    interrupt = SimpleNamespace(id="dashboard-review", value={
        "action_requests": [{"name": "execute_dashboard_query", "args": arguments}],
        "review_configs": [{"allowed_decisions": ["approve", "edit", "reject"]}],
    })
    before = len(w.results.list_for_conversation(w.thread, source_id="test"))
    review = _extract_approval([interrupt], source=source, result_store=w.results, thread_id=w.thread)
    action = review.actions[0]
    assert action.allowed_decisions == ["approve", "reject"] and action.dialect == "duckdb"
    assert action.arguments["parameters"] == {"p0": True} and "$p0" in action.query
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == before
    with pytest.raises(ValueError, match="not allowed"):
        decisions_to_command(review, [Decision(action="edit", edited_sql="SELECT 999")])
    assert decisions_to_command(review, [Decision(action="approve")]).resume["dashboard-review"] == {"decisions": [{"type": "approve"}]}
    output = tool.func(**arguments, runtime=w.runtime("dashboard-query"))
    assert output["result_id"] and output["dashboard_query"]["parameters"] == {"p0": True}
    assert tool.func(**arguments, runtime=w.runtime("dashboard-query")) == output

    from data_analytics_agent.agents.text_to_sql.agent import build_text_to_sql_subagent
    config = build_text_to_sql_subagent(
        source=SimpleNamespace(source_id="test", name="File workspace", dialect="duckdb", context="Reviewed files"),
        semantic_catalog=None, backend=None, result_store=w.results, run_store=w.runs,
        model=None, permissions=None, require_approval=True,
    )
    assert "execute_dashboard_query" in {item.name for item in config["tools"]}
    middleware = next(item for item in config["middleware"] if hasattr(item, "interrupt_on"))
    assert middleware.interrupt_on["execute_dashboard_query"] == {"allowed_decisions": ["approve", "reject"]}


@pytest.mark.parametrize("bad", [
    {"dimensions": ["region", "REGION"]},
    {"measures": [{"name": "a", "aggregation": "sum"}]},
    {"dimensions": ["total"]},
    {"filters": [{"id": "x", "column": "region"}, {"id": "x", "column": "quantity"}]},
])
def test_definition_rejects_ambiguous_or_incomplete_contract(population, bad):
    with pytest.raises(ValidationError):
        QueryDefinition.model_validate({**population.definition.model_dump(), **bad})
