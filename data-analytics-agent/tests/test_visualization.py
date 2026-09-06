from __future__ import annotations


import pytest

from data_analytics_agent.visualization.geocoding import GeoPoint
from data_analytics_agent.visualization.renderer import (
    ChartRenderStyle,
    build_chart,
)
from data_analytics_agent.visualization.schemas import (
    ChartSpec,
)
from data_analytics_agent.visualization.validation import (
    presentation_rows,
    validate_chart_spec,
)
from data_analytics_agent.schemas import (
    ResultReference,
    SavedResult,
)
from data_analytics_agent.stores import (
    ResultStore,
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
    return (
        ResultStore()
        .save(
            thread_id="thread-1",
            source_id="source-1",
            executed_sql="SELECT category, amount FROM metrics",
            columns=list(data[0]),
            rows=data,
        )
        .model_copy(update={"result_id": result_id})
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


def _reference(result_id: str = "result-1") -> ResultReference:
    return ResultReference(
        result_id=result_id,
        executed_sql="SELECT category, amount FROM metrics",
        originating_question="Show metrics",
        short_label="Show metrics",
    )


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


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"chart_type": "line", "secondary_y": "forecast"},
            "supported only for bar charts",
        ),
        (
            {"y": ["amount", "forecast"], "secondary_y": "rate"},
            "exactly one primary y",
        ),
        (
            {"secondary_y": "forecast", "orientation": "horizontal"},
            "vertical orientation",
        ),
        (
            {"secondary_y": "forecast", "color": "segment"},
            "do not support color grouping",
        ),
        (
            {"secondary_y_label": "Forecast"},
            "requires a secondary_y column",
        ),
    ],
)
def test_dual_axis_bar_spec_rejects_ambiguous_shapes(
    updates: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _bar_spec(**updates)


def test_dual_axis_bar_validates_and_renders_secondary_line() -> None:
    result = _saved_result(
        rows=[
            {"month": "2025-01", "revenue": 1200, "margin_rate": 0.2},
            {"month": "2025-02", "revenue": 1500, "margin_rate": 0.24},
        ]
    )
    spec = ChartSpec(
        result_id=result.result_id,
        chart_type="bar",
        title="Revenue and margin rate",
        x="month",
        y=["revenue"],
        secondary_y="margin_rate",
        y_label="Revenue",
        secondary_y_label="Margin rate",
    )

    validate_chart_spec(spec, result)
    rendered = build_chart(spec, result.rows)

    assert [trace.type for trace in rendered.figure.data] == ["bar", "scatter"]
    assert rendered.figure.data[0].name == "revenue"
    assert rendered.figure.data[1].name == "margin_rate"
    assert rendered.figure.data[1].yaxis == "y2"
    assert rendered.figure.layout.yaxis.title.text == "Revenue"
    assert rendered.figure.layout.yaxis2.title.text == "Margin rate"
    assert rendered.figure.layout.yaxis2.overlaying == "y"
    assert rendered.figure.layout.yaxis2.side == "right"


def test_dual_axis_bar_validates_secondary_y_as_numeric() -> None:
    result = _saved_result()
    spec = _bar_spec(secondary_y="category")

    with pytest.raises(ValueError, match="'category' must be numeric"):
        validate_chart_spec(spec, result)


def test_chart_validation_enforces_columns_numeric_data_and_limits() -> None:
    result = _saved_result()
    validate_chart_spec(_bar_spec(), result)

    with pytest.raises(ValueError, match="not present"):
        validate_chart_spec(_bar_spec(y=["missing"]), result)

    many = _saved_result(
        rows=[{"category": f"C{index}", "amount": index} for index in range(31)]
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

    size_result = _saved_result(rows=[{"x": 2, "amount": 1, "size": -1}])
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
        "Displaying 2 of 3 categories" in warning for warning in rendered.warnings
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


def test_surface_style_overrides_only_default_chart_palette() -> None:
    style = ChartRenderStyle(
        discrete_colors=("#2563EB", "#D97706", "#0F766E"),
        continuous_colors=("#E0F2FE", "#0284C7", "#082F49"),
        show_title=False,
        font_family="Inter, sans-serif",
    )

    styled = build_chart(_bar_spec(), _saved_result().rows, style=style).figure
    explicit = build_chart(
        _bar_spec(palette="sunset"),
        _saved_result().rows,
        style=style,
    ).figure

    assert styled.data[0].marker.color == "#2563EB"
    assert styled.layout.title.text is None
    assert styled.layout.margin.t == 24
    assert styled.layout.font.family == "Inter, sans-serif"
    assert explicit.data[0].marker.color != "#2563EB"


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
