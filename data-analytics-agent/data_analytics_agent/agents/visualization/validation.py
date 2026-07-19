"""Deterministic validation and presentation-only row shaping for charts."""

from __future__ import annotations

from collections.abc import Iterable
from numbers import Real
from typing import Any

from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    ChartType,
)
from data_analytics_agent.schemas import SavedResult


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _has_numeric_value(rows: Iterable[dict[str, Any]], column: str) -> bool:
    return any(_is_number(row.get(column)) for row in rows)


def _has_nonnegative_numeric_value(
    rows: Iterable[dict[str, Any]], column: str
) -> bool:
    return any(
        _is_number(row.get(column)) and row[column] >= 0
        for row in rows
    )


def chart_columns(spec: ChartSpec) -> set[str]:
    """Return every saved-result column referenced by a chart specification."""

    values = {
        spec.x,
        *spec.y,
        spec.color,
        spec.size,
        spec.value,
        spec.location,
        spec.region,
        spec.latitude,
        spec.longitude,
        spec.sort_by,
    }
    return {value for value in values if value is not None}


def _sort_key(value: Any) -> tuple[int, int, Any]:
    if value is None:
        return (1, 0, "")
    if _is_number(value):
        return (0, 0, value)
    return (0, 1, str(value).casefold())


def presentation_rows(
    rows: list[dict[str, Any]],
    spec: ChartSpec,
) -> list[dict[str, Any]]:
    """Apply only the reviewed sort and category-limit operations."""

    presented = list(rows)
    if spec.sort_by:
        presented.sort(
            key=lambda row: _sort_key(row.get(spec.sort_by)),
            reverse=spec.sort_direction == "descending",
        )

    category_column = (
        spec.location
        if spec.chart_type is ChartType.MAP
        else spec.x
    )
    if spec.category_limit is None or category_column is None:
        return presented

    selected: list[Any] = []
    selected_keys: set[tuple[type[Any], str]] = set()
    for row in presented:
        value = row.get(category_column)
        key = (type(value), str(value))
        if key in selected_keys:
            continue
        selected_keys.add(key)
        selected.append(value)
        if len(selected) == spec.category_limit:
            break
    allowed = {(type(value), str(value)) for value in selected}
    return [
        row
        for row in presented
        if (type(row.get(category_column)), str(row.get(category_column)))
        in allowed
    ]


def validate_chart_spec(spec: ChartSpec, result: SavedResult) -> None:
    """Validate chart mappings, data compatibility, and readability limits."""

    if spec.result_id != result.result_id:
        raise ValueError("The chart result ID does not match the saved result.")
    missing = sorted(chart_columns(spec) - set(result.columns))
    if missing:
        raise ValueError(
            "Chart columns are not present in the saved result: "
            + ", ".join(missing)
        )
    if not result.rows:
        raise ValueError("The saved result has no rows to visualize.")

    rows = presentation_rows(result.rows, spec)
    if not rows:
        raise ValueError("The reviewed presentation operations removed all rows.")

    numeric_columns = list(spec.y)
    if spec.size:
        numeric_columns.append(spec.size)
    if spec.value:
        numeric_columns.append(spec.value)
    if spec.latitude:
        numeric_columns.append(spec.latitude)
    if spec.longitude:
        numeric_columns.append(spec.longitude)
    for column in numeric_columns:
        if not _has_numeric_value(rows, column):
            raise ValueError(
                f"Chart column {column!r} has no usable numeric values."
            )
    if spec.size and not _has_nonnegative_numeric_value(rows, spec.size):
        raise ValueError("A size column requires nonnegative numeric values.")

    if (
        spec.chart_type is ChartType.HISTOGRAM
        and spec.x
        and not _has_numeric_value(rows, spec.x)
    ):
        raise ValueError("A histogram requires a numeric x column.")
    if (
        spec.chart_type is ChartType.PIE
        and not _has_nonnegative_numeric_value(rows, spec.y[0])
    ):
        raise ValueError("A pie chart requires nonnegative numeric values.")
    if (
        spec.chart_type is ChartType.MAP
        and spec.map_mode == "markers"
        and spec.value
        and not _has_nonnegative_numeric_value(rows, spec.value)
    ):
        raise ValueError(
            "A marker-map value column requires nonnegative numeric values."
        )
    if (
        spec.chart_type is ChartType.MAP
        and spec.location_mode == "coordinates"
        and not any(
            _is_number(row.get(spec.latitude))
            and _is_number(row.get(spec.longitude))
            and -90 <= row[spec.latitude] <= 90
            and -180 <= row[spec.longitude] <= 180
            for row in rows
        )
    ):
        raise ValueError(
            "A coordinate map requires at least one valid latitude/longitude "
            "pair."
        )

    if spec.chart_type is ChartType.HEATMAP:
        assert spec.x is not None
        y_column = spec.y[0]
        populated = [
            row
            for row in rows
            if row.get(spec.x) is not None
            and row.get(y_column) is not None
            and _is_number(row.get(spec.value))
        ]
        keys = {(row[spec.x], row[y_column]) for row in populated}
        if len(keys) != len(populated):
            raise ValueError(
                "Heatmap x/y cells must be unique; aggregate duplicates in SQL."
            )
        if len(keys) > 500:
            raise ValueError("A heatmap may contain at most 500 populated cells.")

    category_column = spec.x
    if spec.chart_type is ChartType.PIE and category_column:
        populated_categories = [
            row.get(category_column)
            for row in rows
            if row.get(category_column) is not None
            and _is_number(row.get(spec.y[0]))
        ]
        count = len(set(populated_categories))
        if count != len(populated_categories):
            raise ValueError(
                "Pie categories must be unique; aggregate duplicates in SQL."
            )
        if count > 12:
            raise ValueError(
                "A pie or donut chart may contain at most 12 slices. "
                "Set category_limit or reshape the SQL result."
            )
    if (
        spec.chart_type is ChartType.MAP
        and spec.map_mode == "choropleth"
        and spec.location
    ):
        locations = [
            row.get(spec.location)
            for row in rows
            if row.get(spec.location) is not None
            and _is_number(row.get(spec.value))
        ]
        if len(set(locations)) != len(locations):
            raise ValueError(
                "Choropleth locations must be unique; aggregate duplicates "
                "in SQL."
            )
    if spec.chart_type in {ChartType.BAR, ChartType.BOX} and category_column:
        count = len({row.get(category_column) for row in rows})
        if count > 30:
            raise ValueError(
                "Bar and box charts may display at most 30 categories. "
                "Set category_limit or reshape the SQL result."
            )
