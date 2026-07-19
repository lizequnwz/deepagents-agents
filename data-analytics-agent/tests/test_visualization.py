from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from data_analytics_agent.agents.visualization.geocoding import GeoPoint
from data_analytics_agent.agents.visualization.renderer import build_chart
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    VisualizationOutcome,
    VisualizationResult,
)
from data_analytics_agent.agents.visualization.tools import (
    create_chart_result,
    create_create_chart_tool,
    create_finish_visualization_tool,
)
from data_analytics_agent.agents.visualization.validation import (
    presentation_rows,
    validate_chart_spec,
)
from data_analytics_agent.run_manager import (
    RunManager,
    _apply_sql_analysis,
    _apply_visualization,
    _chart_activity,
)
from data_analytics_agent.profiling import profile_result
from data_analytics_agent.schemas import (
    FinalAnswer,
    SQLAnalysisResult,
    SavedResult,
)
from data_analytics_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
)


def _saved_result(
    *,
    result_id: str = "result-1",
    rows: list[dict] | None = None,
) -> SavedResult:
    data = rows or [
        {"category": "B", "amount": 12.0},
        {"category": "A", "amount": 8.0},
    ]
    return SavedResult(
        result_id=result_id,
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT category, amount FROM metrics",
        originating_question="Show metrics",
        short_label="Show metrics",
        columns=list(data[0]),
        rows=data,
        profile=profile_result(list(data[0]), data),
        row_count=len(data),
        truncated=False,
        elapsed_ms=1.0,
        created_at=datetime.now(timezone.utc),
    )


def _bar_spec(**updates) -> ChartSpec:
    values = {
        "result_id": "result-1",
        "chart_type": "bar",
        "title": "Amount by category",
        "x": "category",
        "y": ["amount"],
    }
    values.update(updates)
    return ChartSpec.model_validate(values)


def test_chart_spec_is_constrained_and_rejects_ambiguous_wide_color() -> None:
    with pytest.raises(ValueError, match="extra"):
        ChartSpec.model_validate(
            {
                **_bar_spec().model_dump(mode="json"),
                "arbitrary_plotly_layout": {"template": "custom"},
            }
        )

    with pytest.raises(ValueError, match="multi-series"):
        _bar_spec(y=["amount", "forecast"], color="segment")

    with pytest.raises(ValueError, match="marker maps support"):
        ChartSpec(
            result_id="result-1",
            chart_type="map",
            title="States",
            map_mode="markers",
            location_mode="us_state",
            location="state",
        )


def test_chart_validation_enforces_columns_numeric_data_and_limits() -> None:
    result = _saved_result()
    validate_chart_spec(_bar_spec(), result)

    with pytest.raises(ValueError, match="not present"):
        validate_chart_spec(_bar_spec(y=["missing"]), result)

    many = _saved_result(
        rows=[
            {"category": f"C{index}", "amount": index}
            for index in range(31)
        ]
    )
    with pytest.raises(ValueError, match="at most 30"):
        validate_chart_spec(_bar_spec(), many)
    validate_chart_spec(
        _bar_spec(
            category_limit=30,
            sort_by="amount",
            sort_direction="descending",
        ),
        many,
    )

    size_result = _saved_result(
        rows=[{"x": 2, "amount": 1, "size": -1}]
    )
    with pytest.raises(ValueError, match="nonnegative"):
        validate_chart_spec(
            ChartSpec(
                result_id="result-1",
                chart_type="scatter",
                title="Invalid size",
                x="x",
                y=["amount"],
                size="size",
            ),
            size_result,
        )


def test_presentation_operations_are_reviewed_sort_and_category_limit() -> None:
    result = _saved_result(
        rows=[
            {"category": "C", "amount": 1},
            {"category": "A", "amount": 3},
            {"category": "B", "amount": 2},
            {"category": "A", "amount": 4},
        ]
    )
    spec = _bar_spec(
        sort_by="amount",
        sort_direction="descending",
        category_limit=2,
        orientation="horizontal",
    )

    assert presentation_rows(result.rows, spec) == [
        {"category": "A", "amount": 4},
        {"category": "A", "amount": 3},
        {"category": "B", "amount": 2},
    ]
    rendered = build_chart(spec, result.rows)
    assert any(
        "Displaying 2 of 3 categories" in warning
        for warning in rendered.warnings
    )


def test_renderer_builds_chart_and_reports_excluded_invalid_values() -> None:
    rendered = build_chart(
        _bar_spec(),
        [
            {"category": "A", "amount": 10},
            {"category": "B", "amount": "not numeric"},
            {"category": "C", "amount": None},
        ],
    )

    assert len(rendered.figure.data) == 1
    assert any("incompatible" in warning for warning in rendered.warnings)
    assert any("missing bar point" in warning for warning in rendered.warnings)


def test_heatmap_accepts_two_dimensions_and_one_numeric_value() -> None:
    result = _saved_result(
        rows=[
            {"month_start": "2025-01-01", "genre": "Rock", "sales": 10},
            {"month_start": "2025-01-01", "genre": "Jazz", "sales": 8},
            {"month_start": "2025-02-01", "genre": "Rock", "sales": 12},
            {"month_start": "2025-02-01", "genre": "Jazz", "sales": 9},
        ]
    )
    spec = ChartSpec(
        result_id=result.result_id,
        chart_type="heatmap",
        title="Monthly sales by genre",
        x="month_start",
        y=["genre"],
        value="sales",
    )

    validate_chart_spec(spec, result)
    assert build_chart(spec, result.rows).figure.data


def test_scatter_rejects_a_categorical_x_role() -> None:
    result = _saved_result()
    spec = ChartSpec(
        result_id=result.result_id,
        chart_type="scatter",
        title="Invalid scatter",
        x="category",
        y=["amount"],
    )

    with pytest.raises(ValueError, match="'category' must be numeric"):
        validate_chart_spec(spec, result)


@pytest.mark.parametrize(
    "spec",
    [
        ChartSpec(
            result_id="result-1",
            chart_type="line",
            title="Line",
            x="category",
            y=["amount", "forecast"],
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="area",
            title="Area",
            x="category",
            y=["amount"],
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="scatter",
            title="Scatter",
            x="amount",
            y=["forecast"],
            size="size",
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="pie",
            title="Donut",
            x="category",
            y=["amount"],
            donut=True,
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="histogram",
            title="Histogram",
            x="amount",
            bin_count=10,
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="box",
            title="Box",
            x="category",
            y=["amount"],
        ),
        ChartSpec(
            result_id="result-1",
            chart_type="heatmap",
            title="Heatmap",
            x="category",
            y=["segment"],
            value="amount",
        ),
    ],
)
def test_renderer_supports_each_non_map_chart_type(spec: ChartSpec) -> None:
    rows = [
        {
            "category": "A",
            "segment": "S1",
            "amount": 10,
            "forecast": 12,
            "size": 4,
        },
        {
            "category": "B",
            "segment": "S1",
            "amount": 20,
            "forecast": 18,
            "size": 6,
        },
    ]

    assert build_chart(spec, rows).figure.data


class _Resolver:
    def resolve_zip(self, postal_code):
        if str(postal_code) == "10001":
            return GeoPoint(latitude=40.75, longitude=-73.99)
        return None

    def resolve_city_state(self, city, state):
        return None


def test_marker_map_renders_partial_resolution_with_visible_warning() -> None:
    spec = ChartSpec(
        result_id="result-1",
        chart_type="map",
        title="Customers",
        map_mode="markers",
        location_mode="us_zip",
        location="zip",
        value="customers",
    )
    rendered = build_chart(
        spec,
        [
            {"zip": "10001", "customers": 10},
            {"zip": "invalid", "customers": 5},
        ],
        resolver=_Resolver(),
    )

    assert len(rendered.figure.data) == 1
    assert any("Mapped 1 of 2" in warning for warning in rendered.warnings)


def test_state_choropleth_normalizes_names_and_warns_on_invalid_state() -> None:
    spec = ChartSpec(
        result_id="result-1",
        chart_type="map",
        title="Revenue by state",
        map_mode="choropleth",
        location_mode="us_state",
        location="state",
        value="revenue",
    )
    rendered = build_chart(
        spec,
        [
            {"state": "New York", "revenue": 10},
            {"state": "not a state", "revenue": 5},
        ],
        resolver=_Resolver(),
    )

    assert list(rendered.figure.data[0].locations) == ["NY"]
    assert any("unrecognized map" in warning for warning in rendered.warnings)


def test_exact_visualization_subagent_result_overrides_coordinator_chart() -> None:
    approved = _bar_spec(title="Generated title")
    result = VisualizationResult(
        answer="Chart generated successfully.",
        chart=approved,
    )
    output = {
        "messages": [
            HumanMessage(content="Chart it"),
            ToolMessage(
                content=result.model_dump_json(),
                tool_call_id="viz-task",
            ),
            AIMessage(content="Made a chart."),
        ]
    }
    answer = FinalAnswer(
        answer="Made a chart.",
        result_id=approved.result_id,
        chart=_bar_spec(title="Stale title"),
    )

    authoritative = _apply_visualization(answer, output)
    assert authoritative.chart == approved
    assert authoritative.answer == (
        "Chart generated successfully: bar chart 'Generated title'."
    )


def test_terminal_visualization_failure_clears_stale_chart() -> None:
    outcome = VisualizationResult(
        outcome="cannot_create",
        result_id="result-1",
        answer="The requested map requires location columns.",
    )
    output = {
        "messages": [
            HumanMessage(content="Map it"),
            ToolMessage(
                content=outcome.model_dump_json(),
                tool_call_id="viz-task",
            ),
        ]
    }

    authoritative = _apply_visualization(
        FinalAnswer(
            answer="Working.",
            result_id="result-1",
            chart=_bar_spec(),
        ),
        output,
    )

    assert authoritative.answer == outcome.answer
    assert authoritative.chart is None


def test_create_chart_returns_success_message_and_exact_spec() -> None:
    spec = _bar_spec()

    result = create_chart_result(spec, _saved_result())

    assert result.chart == spec
    assert result.answer == (
        "Chart generated successfully: bar chart 'Amount by category'."
    )


def test_create_chart_completes_visualization_directly() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT category, amount FROM metrics",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    tool = create_create_chart_tool(results, source_id="source-1")
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        },
        tool_call_id="chart-call",
    )

    command = tool.func(
        _bar_spec(result_id=saved.result_id),
        runtime,
    )

    assert tool.return_direct is True
    assert command.update["structured_response"].chart.result_id == saved.result_id
    assert command.update["messages"][0].tool_call_id == "chart-call"


def test_visualization_can_finish_with_a_structured_reshape_outcome() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT category, amount FROM metrics",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    tool = create_finish_visualization_tool(
        results, source_id="source-1"
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        },
        tool_call_id="finish-call",
    )

    command = tool.func(
        saved.result_id,
        "needs_sql_reshape",
        "Aggregate duplicate heatmap cells in SQL.",
        runtime,
    )
    outcome = command.update["structured_response"]

    assert outcome.outcome is VisualizationOutcome.NEEDS_SQL_RESHAPE
    assert outcome.chart is None
    assert command.update["messages"][0].tool_call_id == "finish-call"


def test_chart_progress_shows_safe_partial_arguments() -> None:
    spec = _bar_spec(
        orientation="horizontal",
        category_limit=10,
        sort_by="amount",
    )

    kind, label = _chart_activity(
        {"spec": spec.model_dump(mode="json")}
    )

    assert kind == "chart"
    assert label == (
        "Generating bar chart · x=category · y=amount · horizontal · top 10"
    )
    assert spec.result_id not in label


def test_chart_request_preserves_coordinator_answer_with_exact_sql_result() -> None:
    approved = _bar_spec()
    saved = _saved_result()
    sql_result = SQLAnalysisResult(
        answer="The query returned grouped rows.",
        sql="SELECT category, SUM(amount) AS amount FROM metrics GROUP BY 1",
        result_id=approved.result_id,
        columns=saved.columns,
        sample_rows=saved.rows,
        profile=saved.profile,
        row_count=2,
        truncated=False,
    )
    visualization = VisualizationResult(answer="Approved.", chart=approved)
    output = {
        "messages": [
            HumanMessage(content="Chart it"),
            ToolMessage(
                content=sql_result.model_dump_json(),
                tool_call_id="sql-task",
            ),
            ToolMessage(
                content=visualization.model_dump_json(),
                tool_call_id="viz-task",
            ),
            AIMessage(content="Here is the generated chart."),
        ]
    }
    answer = FinalAnswer(
        answer="Here is the generated chart.",
        result_id=approved.result_id,
        chart=approved,
    )

    authoritative = _apply_sql_analysis(answer, output)
    assert authoritative.answer == "Here is the generated chart."
    assert authoritative.sql == sql_result.sql


def test_answer_chart_must_match_saved_result_provenance() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT category, amount FROM metrics",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    manager = RunManager(
        agent=object(),
        conversations=ConversationStore(),
        runs=RunStore(),
        results=results,
    )
    spec = _bar_spec(result_id=saved.result_id)

    answer = manager._validate_answer_provenance(
        FinalAnswer(
            answer="Chart.",
            result_id=saved.result_id,
            chart=spec,
        ),
        "thread-1",
        "source-1",
    )

    assert answer.sql == saved.executed_sql
    assert answer.chart == spec
