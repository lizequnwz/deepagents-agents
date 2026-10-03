from datetime import date, datetime
from types import SimpleNamespace

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from data_analytics_agent.analytical_scope import (
    SavedScope,
    check_inputs,
    prepare_input,
    scope_options,
)
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.schemas import CoordinatorResponse, FinalAnswer
from data_analytics_agent.stores import RunStore
from tests.test_persistent_analyst import save
from tests.test_run_manager import Graph, Stream


def rows(w):
    return save(
        w,
        [
            {"region": "West", "day": date(2024, 1, 1), "amount": 10},
            {"region": "East", "day": date(2024, 1, 2), "amount": 20},
            {"region": None, "day": date(2024, 1, 3), "amount": 30},
        ],
    )


def test_filters_are_saved_typed_and_authoritative(workspace):
    w = workspace
    base = rows(w)
    scope = SavedScope(
        base_result_id=base.result_id,
        categories={"region": ["West", None]},
        dates={"column": "day", "start": "2024-01-01", "end": "2024-01-02"},
    )
    selected = prepare_input(w.results, w.thread, "test", base.result_id, scope)
    result = w.results.get_unscoped(selected.input_result_id)
    assert result.rows == [{"region": "West", "day": date(2024, 1, 1), "amount": 10}]
    assert result.parent_result_ids == [base.result_id]
    run = w.runs.create(w.thread, "test", "West", analytical_input=selected)
    check_inputs(w.results, w.runs, run, [result.result_id])
    with pytest.raises(ValueError, match="outside"):
        check_inputs(w.results, w.runs, run, [base.result_id])
    with pytest.raises(ValueError, match="snapshot"):
        w.runs.require_source_access(run)
    restored = RunStore(w.storage).get(run)
    assert restored.analytical_input == selected


def test_specialist_assignment_carries_application_bound_exact_input(workspace):
    from langchain_core.messages import HumanMessage
    from data_analytics_agent.handoff import AssignmentMiddleware

    w = workspace
    base = rows(w)
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(base_result_id=base.result_id, categories={"region": ["West"]}),
    )
    run = w.runs.create(w.thread, "test", "Compare West", analytical_input=selected)
    update = AssignmentMiddleware(w.runs, "text-to-sql").before_agent(
        {
            "run_id": run,
            "messages": [HumanMessage(content="Compare the saved population")],
        },
        None,
    )
    assert selected.input_result_id in update["messages"][0].content
    assert (
        selected.input_result_id
        in w.runs.assignment(run, update["assignment_id"]).brief
    )
    repeated = AssignmentMiddleware(w.runs, "text-to-sql").before_agent(
        {
            "run_id": run,
            "assignment_id": update["assignment_id"],
            "messages": [HumanMessage(content="Compare the saved population")],
        },
        None,
    )
    assert repeated["messages"][0].id == update["messages"][0].id


def test_mixed_lineage_cannot_silently_expand_selected_population(workspace):
    w = workspace
    base = rows(w)
    broader = save(w, [{"amount": 999}])
    mixed = save(
        w,
        [{"amount": 999}],
        kind="python",
        parent_result_ids=[base.result_id, broader.result_id],
    )
    selected = prepare_input(w.results, w.thread, "test", base.result_id)
    run = w.runs.create(
        w.thread, "test", "Use this snapshot", analytical_input=selected
    )
    with pytest.raises(ValueError, match="outside"):
        check_inputs(w.results, w.runs, run, [mixed.result_id])
    left = save(
        w, [{"amount": 10}], kind="saved_sql", parent_result_ids=[base.result_id]
    )
    right = save(
        w, [{"amount": 20}], kind="saved_sql", parent_result_ids=[base.result_id]
    )
    valid = save(
        w,
        [{"amount": 30}],
        kind="python",
        parent_result_ids=[left.result_id, right.result_id],
    )
    check_inputs(w.results, w.runs, run, [valid.result_id])


def test_fresh_run_can_combine_multiple_fresh_inputs_but_no_old_input(workspace):
    w = workspace
    old = rows(w)
    left = save(w, [{"amount": 10}])
    right = save(w, [{"amount": 20}])
    run = w.runs.create(w.thread, "test", "Fresh analysis", fresh_source_required=True)
    for item in [left, right]:
        w.runs.record_fresh_result(run, item.result_id)
    valid = save(
        w,
        [{"amount": 30}],
        kind="python",
        parent_result_ids=[left.result_id, right.result_id],
    )
    check_inputs(w.results, w.runs, run, [valid.result_id])
    invalid = save(
        w,
        [{"amount": 30}],
        kind="python",
        parent_result_ids=[valid.result_id, old.result_id],
    )
    with pytest.raises(ValueError, match="outside"):
        check_inputs(w.results, w.runs, run, [invalid.result_id])


def test_shared_lineage_checks_do_not_repeat_exponentially(workspace, monkeypatch):
    w = workspace
    base = rows(w)
    selected = prepare_input(w.results, w.thread, "test", base.result_id)
    run = w.runs.create(
        w.thread, "test", "Shared derivations", analytical_input=selected
    )
    previous = [base.result_id]
    for depth in range(12):
        previous = [
            save(
                w, [{"amount": depth}], kind="python", parent_result_ids=previous
            ).result_id
            for _ in range(2)
        ]
    get = w.results.get
    reads = []

    def observe(*args, **kwargs):
        reads.append(args[0])
        return get(*args, **kwargs)

    monkeypatch.setattr(w.results, "get", observe)
    check_inputs(w.results, w.runs, run, previous)
    assert len(reads) < 500, f"Shared evidence caused {len(reads)} repeated lookups"


def test_empty_reader_rejects_duplicate_column_aliases(workspace):
    schema = pa.schema([("same", pa.int64()), ("same", pa.int64())])
    reader = pa.RecordBatchReader.from_batches(schema, [])
    with pytest.raises(ValueError, match="unique aliases|duplicate"):
        workspace.results.save_batches(
            reader, thread_id=workspace.thread, source_id="test"
        )


def test_selector_excludes_incomplete_and_presentation_populations(
    workspace, test_settings
):
    w = workspace
    base = rows(w)
    save(w, [{"region": "West"}], truncated=True)
    save(
        w, [{"region": "West"}], kind="presentation", parent_result_ids=[base.result_id]
    )
    services = Services(
        settings=test_settings,
        conversations=w.conversations,
        results=w.results,
        runs=w.runs,
        analyses=w.analyses,
        reports=w.reports,
        agent=Graph([]),
    )
    with TestClient(create_app(services)) as api:
        available = api.get(f"/api/conversations/{w.thread}/datasets").json()[
            "datasets"
        ]
        assert [item["result_id"] for item in available] == [base.result_id]
        other = w.conversations.create("test")
        assert (
            api.get(
                f"/api/conversations/{other}/datasets/{base.result_id}/scope-options"
            ).status_code
            == 404
        )


def test_stale_categories_missing_detail_and_unsupported_dates_explain_gap(workspace):
    w = workspace
    base = rows(w)
    assert scope_options(base)["date_bounds"]["day"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
    }
    for filters in [{"region": ["North"]}, {"missing_detail": ["x"]}]:
        with pytest.raises(ValueError, match="absent|supported"):
            prepare_input(
                w.results,
                w.thread,
                "test",
                base.result_id,
                SavedScope(base_result_id=base.result_id, categories=filters),
            )
    with pytest.raises(ValueError, match="typed date"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "amount", "start": "2024-01-01", "end": "2024-01-03"},
            ),
        )


def test_analytical_input_persists_in_request_and_reopened_history(test_settings):
    services = Services(
        settings=test_settings,
        agent=Graph(
            [Stream(CoordinatorResponse(answer="Saved-input metadata checked."))]
        ),
    )
    thread = services.conversations.create("test")
    selected = services.results.save(
        columns=["country", "count"],
        rows=[{"country": "US", "count": 10}],
        thread_id=thread,
        source_id="test",
    )
    with TestClient(create_app(services)) as api:
        response = api.post(
            f"/api/conversations/{thread}/messages",
            json={
                "message": "Explain this saved dataset",
                "selected_result_id": selected.result_id,
            },
        )
        assert response.status_code == 202
        run = api.get("/api/runs/" + response.json()["run_id"]).json()
        assert run["analytical_input"]["input_result_id"] == selected.result_id
        assert (
            run["answer"]["analytical_input"]["input_result_id"] == selected.result_id
        )
    restored = Services(settings=test_settings).conversations.get(thread)
    assert restored.analytical_input.input_result_id == selected.result_id
    assert restored.turns[-1].analytical_input == restored.analytical_input


def test_refresh_reapplies_scope_before_publication(workspace):
    w = workspace
    old = rows(w)
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        old.result_id,
        SavedScope(base_result_id=old.result_id, categories={"region": ["West"]}),
    )
    run = w.runs.create(
        w.thread,
        "test",
        "Refresh West",
        analytical_input=selected,
        fresh_source_required=True,
    )
    with pytest.raises(ValueError, match="Fresh"):
        w.runs.publish(run, FinalAnswer(answer="Old values"))
    new = save(
        w,
        [
            {"region": "West", "day": date(2024, 1, 1), "amount": 100},
            {"region": "East", "day": date(2024, 1, 2), "amount": 200},
        ],
    )
    w.runs.record_fresh_result(run, new.result_id)
    with pytest.raises(ValueError, match="reapply"):
        w.runs.publish(run, FinalAnswer(answer="Unfiltered values"))
    bind = next(
        t
        for t in create_presentation_tools(
            w.results, w.analyses, w.runs, w.conversations, source_id="test"
        )
        if t.name == "bind_refreshed_input"
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": w.thread,
            "source_id": "test",
            "run_id": run,
            "question": "Refresh West",
        },
        tool_call_id="bind",
    )
    response = bind.func(result_id=new.result_id, runtime=runtime)
    scoped_id = response["analytical_input"]["input_result_id"]
    assert w.results.get_unscoped(scoped_id).rows[0]["amount"] == 100
    assert w.results.get_unscoped(scoped_id).row_count == 1
    check_inputs(w.results, w.runs, run, [scoped_id])
    with pytest.raises(ValueError, match="outside"):
        check_inputs(w.results, w.runs, run, [new.result_id])
    w.runs.publish(run, FinalAnswer(answer="Fresh West"))
    assert w.runs.get(run).findings.analytical_input.selected_result_id == new.result_id


def test_empty_filtered_population_keeps_types(workspace):
    w = workspace
    base = rows(w)
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "day", "start": "2025-01-01", "end": "2025-02-01"},
        ),
    )
    empty = w.results.get_unscoped(selected.input_result_id)
    assert empty.row_count == 0
    import pyarrow.parquet as pq

    assert pa.types.is_date(pq.read_schema(empty.parquet_path).field("day").type)


@pytest.mark.parametrize(
    "value", ["O'Reilly", 'x"; DROP TABLE selected; --', "Été 東京"]
)
def test_scope_quotes_identifiers_and_values_without_changing_data(workspace, value):
    w = workspace
    column = 'region" name'
    base = save(w, [{column: value, "amount": 10}, {column: "Other", "amount": 20}])
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(base_result_id=base.result_id, categories={column: [value]}),
    )
    assert w.results.get_unscoped(selected.input_result_id).rows == [
        {column: value, "amount": 10}
    ]
    assert w.results.get_unscoped(base.result_id).row_count == 2


@pytest.mark.parametrize(
    "values,expected", [([False], [False]), ([True, None], [True, None])]
)
def test_scope_preserves_boolean_and_missing_categories(workspace, values, expected):
    w = workspace
    base = save(w, [{"active": value} for value in [False, True, None]])
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(base_result_id=base.result_id, categories={"active": values}),
    )
    assert [
        r["active"] for r in w.results.get_unscoped(selected.input_result_id).rows
    ] == expected
    with pytest.raises(ValueError, match="absent"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(base_result_id=base.result_id, categories={"active": [0]}),
        )


def test_scope_includes_entire_end_day_and_excludes_missing_dates(workspace):
    w = workspace
    base = save(
        w,
        [
            {"event": value, "n": n}
            for n, value in enumerate(
                [
                    datetime(2024, 1, 31),
                    datetime(2024, 1, 31, 23, 59, 59, 999999),
                    datetime(2024, 2, 1),
                    None,
                ]
            )
        ],
    )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "event", "start": "2024-01-31", "end": "2024-01-31"},
        ),
    )
    assert [r["n"] for r in w.results.get_unscoped(selected.input_result_id).rows] == [
        0,
        1,
    ]


def test_timezone_scope_requires_explicit_calendar_preparation(workspace):
    from datetime import timezone

    w = workspace
    base = save(w, [{"event": datetime(2024, 1, 1, tzinfo=timezone.utc)}])
    assert scope_options(base)["date_columns"] == []
    with pytest.raises(ValueError, match="without timezone"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "event", "start": "2024-01-01", "end": "2024-01-02"},
            ),
        )


def test_vanished_refresh_category_is_a_saved_empty_population(workspace):
    w = workspace
    base = save(w, [{"region": "East", "amount": 10}])
    scope = SavedScope(base_result_id=base.result_id, categories={"region": ["West"]})
    selected = prepare_input(
        w.results, w.thread, "test", base.result_id, scope, refreshed=True
    )
    assert selected.row_count == 0 and selected.scope.categories == {"region": ["West"]}
    empty = w.results.get_unscoped(selected.input_result_id)
    assert empty.columns == base.columns and empty.parent_result_ids == [base.result_id]
    assert [column.name for column in empty.profile.columns] == base.columns
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_query_saved_results_tool,
    )

    queried = create_query_saved_results_tool(w.results, w.runs, source_id="test").func(
        query="SELECT count(*) AS records, sum(amount) AS total FROM snapshot",
        bindings={"snapshot": empty.result_id},
        purpose="Empty population check",
        runtime=w.runtime("empty-followup"),
    )
    assert w.results.get_unscoped(queried["result_id"]).rows == [
        {"records": 0, "total": None}
    ]


@pytest.mark.parametrize("cardinality", [100, 101])
def test_scope_bounds_actual_categorical_cardinality(workspace, cardinality):
    base = save(workspace, [{"category": str(i)} for i in range(cardinality)])
    options = scope_options(base)["categories"]
    assert ("category" in options) is (cardinality == 100)
    if cardinality == 100:
        assert len(options["category"]) == 100


@pytest.mark.parametrize(
    "unit,start,end,partial",
    [
        ("quarter", "2024-01-01", "2024-03-31", "2024-03-15"),
        ("year", "2024-01-01", "2024-12-31", "2024-11-30"),
    ],
)
def test_scope_preserves_whole_quarter_and_year_aggregates(
    workspace, unit, start, end, partial
):
    w = workspace
    base = save(
        w,
        [{"period": date(2024, 1, 1), "total": 100}],
        executed_sql=f"SELECT DATE_TRUNC('{unit}', day) AS period, SUM(amount) AS total FROM facts GROUP BY 1",
    )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "period", "start": start, "end": end},
        ),
    )
    assert selected.row_count == 1
    with pytest.raises(ValueError, match=f"whole {unit} periods"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "period", "start": start, "end": partial},
            ),
        )


def test_saved_monthly_aggregates_reject_partial_periods(workspace):
    w = workspace
    base = save(
        w,
        [
            {"month": date(2024, 1, 1), "total": 100},
            {"month": date(2024, 2, 1), "total": 200},
        ],
        executed_sql="SELECT DATE_TRUNC('month', day) AS month, SUM(amount) AS total FROM facts GROUP BY DATE_TRUNC('month', day)",
    )
    with pytest.raises(ValueError, match="whole month periods"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "month", "start": "2024-01-15", "end": "2024-02-20"},
            ),
        )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "month", "start": "2024-02-01", "end": "2024-02-29"},
        ),
    )
    assert w.results.get_unscoped(selected.input_result_id).rows == [
        {"month": date(2024, 2, 1), "total": 200}
    ]


def test_cte_aggregate_periods_keep_whole_month_boundaries(workspace):
    w = workspace
    base = save(
        w,
        [{"period": date(2024, 1, 1), "total": 100}],
        executed_sql="WITH totals AS (SELECT DATE_TRUNC('month', day) AS month, SUM(amount) AS total FROM facts GROUP BY 1) SELECT month AS period, total FROM totals",
    )
    with pytest.raises(ValueError, match="whole month periods"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "period", "start": "2024-01-15", "end": "2024-01-31"},
            ),
        )


def test_scoping_a_scoped_aggregate_preserves_original_period_boundaries(workspace):
    w = workspace
    base = save(
        w,
        [{"month": date(2024, 1, 1), "total": 100}],
        executed_sql="SELECT DATE_TRUNC('month', day) AS month, SUM(amount) AS total FROM facts GROUP BY 1",
    )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "month", "start": "2024-01-01", "end": "2024-01-31"},
        ),
    )
    with pytest.raises(ValueError, match="whole month periods"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            selected.input_result_id,
            SavedScope(
                base_result_id=selected.input_result_id,
                dates={"column": "month", "start": "2024-01-15", "end": "2024-01-31"},
            ),
        )


def test_unused_aggregate_cte_does_not_change_raw_date_grain(workspace):
    w = workspace
    base = save(
        w,
        [{"period": date(2024, 1, 16), "amount": 100}],
        executed_sql="WITH unused AS (SELECT DATE_TRUNC('month', day) AS month, SUM(amount) AS total FROM facts GROUP BY 1) SELECT day AS period, amount FROM facts",
    )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        base.result_id,
        SavedScope(
            base_result_id=base.result_id,
            dates={"column": "period", "start": "2024-01-15", "end": "2024-01-20"},
        ),
    )
    assert selected.row_count == 1


def test_saved_join_follows_the_selected_date_binding_only(workspace):
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_query_saved_results_tool,
    )

    w = workspace
    raw = save(w, [{"day": date(2024, 1, 16), "amount": 10, "category": "A"}])
    monthly = save(
        w,
        [{"day": date(2024, 1, 1), "total": 100, "category": "A"}],
        executed_sql="SELECT DATE_TRUNC('month', day) AS day, SUM(amount) AS total, category FROM facts GROUP BY 1, 3",
    )
    queried = create_query_saved_results_tool(w.results, w.runs, source_id="test").func(
        query="SELECT r.day AS period, r.amount FROM raw AS r JOIN monthly AS m ON r.category=m.category",
        bindings={"raw": raw.result_id, "monthly": monthly.result_id},
        purpose="Joined daily evidence",
        runtime=w.runtime("joined-date"),
    )
    selected = prepare_input(
        w.results,
        w.thread,
        "test",
        queried["result_id"],
        SavedScope(
            base_result_id=queried["result_id"],
            dates={"column": "period", "start": "2024-01-15", "end": "2024-01-20"},
        ),
    )
    assert selected.row_count == 1


def test_saved_sql_rejects_aliases_that_only_differ_by_case(workspace):
    from langchain_core.tools import ToolException
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_query_saved_results_tool,
    )

    w = workspace
    left = save(w, [{"amount": 10}])
    right = save(w, [{"amount": 100}])
    with pytest.raises(ToolException, match="aliases.*unique"):
        create_query_saved_results_tool(w.results, w.runs, source_id="test").func(
            query='SELECT amount FROM "Snapshot"',
            bindings={"Snapshot": left.result_id, "snapshot": right.result_id},
            purpose="Distinct saved inputs",
            runtime=w.runtime("case-collision"),
        )


@pytest.mark.parametrize("alias", ["Period", "order date"])
def test_quoted_date_alias_keeps_aggregate_boundaries(workspace, alias):
    w = workspace
    base = save(
        w,
        [{alias: date(2024, 1, 1), "total": 100}],
        executed_sql=f"SELECT DATE_TRUNC('month', day) AS \"{alias}\", SUM(amount) AS total FROM facts GROUP BY 1",
    )
    with pytest.raises(ValueError, match="whole month periods"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": alias, "start": "2024-01-15", "end": "2024-01-31"},
            ),
        )


def test_unsupported_week_bucket_explains_calendar_gap(workspace):
    w = workspace
    base = save(
        w,
        [{"week": date(2024, 1, 1), "total": 100}],
        executed_sql="SELECT DATE_TRUNC('week', day) AS week, SUM(amount) AS total FROM facts GROUP BY 1",
    )
    with pytest.raises(ValueError, match="saved week grain"):
        prepare_input(
            w.results,
            w.thread,
            "test",
            base.result_id,
            SavedScope(
                base_result_id=base.result_id,
                dates={"column": "week", "start": "2024-01-02", "end": "2024-01-05"},
            ),
        )


@pytest.mark.parametrize("damage", ["empty", "timestamp", "untyped_null"])
def test_refresh_compares_stored_types_and_accepts_typed_empty_inputs(
    workspace, damage
):
    from langchain_core.tools import ToolException

    w = workspace
    old = rows(w)
    selected = prepare_input(w.results, w.thread, "test", old.result_id)
    run = w.runs.create(
        w.thread,
        "test",
        "Refresh",
        analytical_input=selected,
        fresh_source_required=True,
    )
    table = pa.Table.from_pylist(old.rows)
    if damage == "empty":
        table = table.slice(0, 0)
    elif damage == "timestamp":
        table = table.set_column(1, "day", table["day"].cast(pa.timestamp("us")))
    else:
        table = table.set_column(1, "day", pa.nulls(table.num_rows))
    fresh = w.results.save_batches(
        table.to_reader(), thread_id=w.thread, source_id="test"
    )
    w.runs.record_fresh_result(run, fresh.result_id)
    bind = next(
        t
        for t in create_presentation_tools(
            w.results, w.analyses, w.runs, w.conversations, source_id="test"
        )
        if t.name == "bind_refreshed_input"
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": w.thread,
            "source_id": "test",
            "run_id": run,
            "question": "Refresh",
        },
        tool_call_id="fresh-bind",
    )
    if damage == "empty":
        response = bind.func(result_id=fresh.result_id, runtime=runtime)
        assert response["analytical_input"]["row_count"] == 0
    else:
        with pytest.raises(ToolException, match="fields and types"):
            bind.func(result_id=fresh.result_id, runtime=runtime)
        assert w.runs.get(run).analytical_input == selected


def test_reviewed_upload_and_python_populations_are_selectable(test_settings):
    from tests.test_uploads import reviewed

    s = Services(settings=test_settings)
    upload = reviewed(
        s,
        b"region,day,amount\nWest,2024-01-01,10\nEast,2024-01-02,20\n",
        grain="One sale",
    )
    base = s.results.get_unscoped(upload.result_id)
    derived = s.results.save(
        columns=["region", "amount"],
        rows=[{"region": "West", "amount": 10}],
        thread_id=upload.thread_id,
        source_id=upload.source_id,
        parent_result_ids=[base.result_id],
        kind="python",
        purpose="West sales",
    )
    with TestClient(create_app(s)) as api:
        available = api.get(f"/api/conversations/{upload.thread_id}/datasets").json()[
            "datasets"
        ]
        assert {item["result_id"] for item in available} == {
            base.result_id,
            derived.result_id,
        }
        assert (
            next(item for item in available if item["result_id"] == base.result_id)[
                "grain"
            ]
            == "One sale"
        )
    selected = prepare_input(
        s.results,
        upload.thread_id,
        upload.source_id,
        base.result_id,
        SavedScope(base_result_id=base.result_id, categories={"region": ["West"]}),
    )
    assert s.results.get_unscoped(selected.input_result_id).row_count == 1


@pytest.mark.parametrize("allow_expansion", [False, True])
def test_selected_input_survives_clarification_stop_resume_and_restart(
    test_settings, monkeypatch, allow_expansion
):
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from tests.test_agent_workflow import AnalystModel
    from data_analytics_agent import coordinator

    class ScopeModel(AnalystModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            answers = [
                m
                for m in messages
                if isinstance(m, ToolMessage) and m.name == "request_clarification"
            ]
            name = "CoordinatorResponse" if answers else "request_clarification"
            arguments = (
                {"answer": "Recorded the scope decision."}
                if answers
                else {
                    "question": "This snapshot lacks order detail. Retrieve a complete source population?",
                    "source_expansion": True,
                }
            )
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": name,
                                    "args": arguments,
                                    "id": "scope-response"
                                    if answers
                                    else "scope-question",
                                }
                            ],
                        )
                    )
                ]
            )

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(coordinator, "_build_chat_model", lambda *a, **k: ScopeModel())
    s = Services(settings=test_settings)
    thread = s.conversations.create("test")
    base = s.results.save(
        columns=["country", "count"],
        rows=[{"country": "US", "count": 10}],
        thread_id=thread,
        source_id="test",
    )
    with TestClient(create_app(s)) as api:
        response = api.post(
            f"/api/conversations/{thread}/messages",
            json={
                "message": "Inspect order detail",
                "selected_result_id": base.result_id,
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        current = api.get(f"/api/runs/{run_id}").json()
        assert current["status"] == "clarification_required", current.get("error")
        assert api.post(f"/api/runs/{run_id}/stop").json()["status"] == "paused"
    s = Services(settings=test_settings)
    with TestClient(create_app(s)) as api:
        assert api.post(f"/api/runs/{run_id}/resume").status_code == 202
        current = api.get(f"/api/runs/{run_id}").json()
        assert current["status"] == "clarification_required", current.get("error")
        assert current["analytical_input"]["input_result_id"] == base.result_id
        interrupt = current["clarification"]["interrupt_id"]
        stale = api.post(
            f"/api/runs/{run_id}/clarification",
            json={
                "message": "Yes",
                "allow_source_expansion": True,
                "interrupt_id": "stale",
            },
        )
        assert stale.status_code == 409
        assert not s.runs.get(run_id).source_expansion_allowed
        reply = api.post(
            f"/api/runs/{run_id}/clarification",
            json={
                "message": "Yes",
                "allow_source_expansion": allow_expansion,
                "interrupt_id": interrupt,
            },
        )
        assert reply.status_code == 202, reply.text
        current = api.get(f"/api/runs/{run_id}").json()
        assert current["status"] == "completed", current.get("error")
        assert (
            current["answer"]["analytical_input"]["input_result_id"] == base.result_id
        )
        assert current["source_expansion_allowed"] is allow_expansion
        if allow_expansion:
            s.runs.require_source_access(run_id)
        else:
            with pytest.raises(ValueError, match="snapshot"):
                s.runs.require_source_access(run_id)
    reopened = Services(settings=test_settings).conversations.get(thread)
    assert reopened.analytical_input.input_result_id == base.result_id
