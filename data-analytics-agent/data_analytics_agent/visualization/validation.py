"""Deterministic validation and presentation-only row shaping for charts."""

from __future__ import annotations

from collections.abc import Iterable
from numbers import Real
from decimal import Decimal, localcontext
from math import isfinite
from typing import Any
import pandas as pd

from data_analytics_agent.visualization.schemas import (
    ChartSpec,
    ChartType,
)
from data_analytics_agent.schemas import (
    AnalyticalRole,
    ColumnProfile,
    SavedResult,
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (Real, Decimal)) and not isinstance(value, bool)


def _has_numeric_value(rows: Iterable[dict[str, Any]], column: str) -> bool:
    return any(_is_number(row.get(column)) for row in rows)


def _has_nonnegative_numeric_value(rows: Iterable[dict[str, Any]], column: str) -> bool:
    return any(_is_number(row.get(column)) and row[column] >= 0 for row in rows)


def _column_profile(result: SavedResult, column: str) -> ColumnProfile:
    for profile in result.profile.columns:
        if profile.name == column:
            return profile
    raise ValueError(f"Column {column!r} has no stored profile.")


def _supports_role(
    result: SavedResult,
    column: str,
    roles: set[AnalyticalRole],
) -> bool:
    return any(
        candidate.role in roles and candidate.confidence > 0
        for candidate in _column_profile(result, column).role_candidates
    )


def _require_role(
    result: SavedResult,
    column: str,
    roles: set[AnalyticalRole],
    description: str,
) -> None:
    if not _supports_role(result, column, roles):
        raise ValueError(f"Chart column {column!r} must be {description}.")


def chart_columns(spec: ChartSpec) -> set[str]:
    """Return every saved-result column referenced by a chart specification."""

    values = {
        spec.lower_bound,
        spec.upper_bound,
        spec.error_y,
        spec.x,
        *spec.y,
        spec.secondary_y,
        spec.color,
        spec.size,
        spec.value,
        spec.location,
        spec.region,
        spec.latitude,
        spec.longitude,
        spec.sort_by,
        spec.waterfall_measure,
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
    if spec.chart_type is ChartType.FUNNEL:
        assert spec.stage_order is not None
        # The declared process order is authoritative, never a sort by counts.
        return sorted(
            presented,
            key=lambda row: (
                spec.stage_order.index(row.get(spec.x))
                if row.get(spec.x) in spec.stage_order
                else len(spec.stage_order)
            ),
        )
    if spec.sort_by:
        presented.sort(
            key=lambda row: _sort_key(row.get(spec.sort_by)),
            reverse=spec.sort_direction == "descending",
        )

    category_column = spec.location if spec.chart_type is ChartType.MAP else spec.x
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
        if (type(row.get(category_column)), str(row.get(category_column))) in allowed
    ]


def validate_analytical_chart_rows(spec: ChartSpec, rows: list[dict[str, Any]]) -> None:
    """Require complete, already-shaped stages/contributions without dropping rows."""

    if spec.chart_type not in {ChartType.WATERFALL, ChartType.FUNNEL}:
        return
    labels = [row.get(spec.x) for row in rows]
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError(f"{spec.chart_type} requires nonblank text category labels.")
    if len(set(labels)) != len(labels):
        raise ValueError(
            f"{spec.chart_type} categories must be unique; reshape the saved data explicitly."
        )
    if not 2 <= len(rows) <= 30:
        raise ValueError(
            f"{spec.chart_type} requires between 2 and 30 saved categories."
        )
    values = [row.get(spec.y[0]) for row in rows]
    try:
        valid = all(_is_number(value) and isfinite(float(value)) for value in values)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValueError(
            f"{spec.chart_type} requires a finite numeric value for every category."
        )
    if spec.chart_type is ChartType.FUNNEL:
        if set(labels) != set(spec.stage_order or []):
            raise ValueError(
                "stage_order must cover every saved funnel stage exactly once."
            )
        if any(value < 0 or value != int(value) for value in values):
            raise ValueError("Funnel counts must be nonnegative integers.")
        if any(current > previous for previous, current in zip(values, values[1:])):
            raise ValueError(
                "Funnel counts must not increase in the declared stage_order."
            )
        return
    measures = [row.get(spec.waterfall_measure) for row in rows]
    if len(rows) < 3 or measures != [
        "absolute",
        *(["relative"] * (len(rows) - 2)),
        "total",
    ]:
        raise ValueError(
            "Waterfall requires an absolute baseline, relative contributions, and a final total in saved row order."
        )
    # Decimal arithmetic preserves saved money values; only tiny floating-point
    # roundoff (absolute 1e-9 source units) is tolerated in the supplied total.
    with localcontext() as context:
        context.prec = 400
        expected = sum((Decimal(str(value)) for value in values[:-1]), Decimal(0))
        if abs(expected - Decimal(str(values[-1]))) > Decimal("1e-9"):
            raise ValueError(
                "Waterfall ending total must equal its baseline plus all relative contributions (absolute tolerance 1e-9)."
            )


def validate_chart_spec(spec: ChartSpec, result: SavedResult) -> None:
    """Validate chart mappings, data compatibility, and readability limits."""

    if spec.result_id != result.result_id:
        raise ValueError("The chart result ID does not match the saved result.")
    missing = sorted(chart_columns(spec) - set(result.columns))
    if missing:
        raise ValueError(
            "Chart columns are not present in the saved result: " + ", ".join(missing)
        )
    if not result.rows:
        raise ValueError("The saved result has no rows to visualize.")

    if spec.chart_type in {ChartType.WATERFALL, ChartType.FUNNEL} and (
        result.truncated
        or (
            result.chart_preparation is not None
            and (
                result.chart_preparation.sampling != "none"
                or result.chart_preparation.input_row_count
                != result.chart_preparation.output_row_count
            )
        )
    ):
        raise ValueError(
            "Waterfall and funnel charts require complete unsampled saved data."
        )

    rows = presentation_rows(result.rows, spec)
    if not rows:
        raise ValueError("The reviewed presentation operations removed all rows.")
    validate_analytical_chart_rows(spec, rows)
    if spec.forecast_start:
        _require_role(
            result,
            spec.x,
            {AnalyticalRole.TEMPORAL},
            "a typed temporal axis for a forecast-start marker",
        )
        marker = pd.Timestamp(spec.forecast_start)
        times = pd.to_datetime(
            [row.get(spec.x) for row in rows if row.get(spec.x) is not None]
        )
        if times.tz is not None or not times.min() <= marker <= times.max():
            raise ValueError(
                "Forecast start must fall within the saved calendar series without timezone."
            )
    if spec.lower_bound:
        target = spec.interval_series or spec.y[0]
        if any(
            (
                row.get(spec.lower_bound) is not None
                or row.get(spec.upper_bound) is not None
            )
            and row.get(target) is None
            for row in rows
        ):
            raise ValueError(
                "Interval bounds must be attached to saved values of their target series."
            )

    if spec.error_y and any(
        _is_number(row.get(spec.error_y)) and row[spec.error_y] < 0 for row in rows
    ):
        raise ValueError("Error bars must be nonnegative.")
    if (
        spec.lower_bound
        and spec.upper_bound
        and any(
            _is_number(row.get(spec.lower_bound))
            and _is_number(row.get(spec.upper_bound))
            and row[spec.lower_bound] > row[spec.upper_bound]
            for row in rows
        )
    ):
        raise ValueError("Uncertainty lower bounds must not exceed upper bounds.")

    dimensions = {
        AnalyticalRole.CATEGORICAL,
        AnalyticalRole.TEMPORAL,
        AnalyticalRole.DISCRETE_NUMERIC,
    }
    categorical = {AnalyticalRole.CATEGORICAL}
    numeric = {AnalyticalRole.NUMERIC}
    ordered = {*dimensions, AnalyticalRole.NUMERIC}

    if spec.chart_type is ChartType.BAR:
        assert spec.x is not None
        _require_role(
            result,
            spec.x,
            dimensions,
            "categorical, temporal, or discrete numeric",
        )
    elif spec.chart_type in {ChartType.PIE, ChartType.WATERFALL, ChartType.FUNNEL}:
        assert spec.x is not None
        _require_role(result, spec.x, categorical, "categorical")
    elif spec.chart_type in {ChartType.LINE, ChartType.AREA}:
        assert spec.x is not None
        _require_role(
            result,
            spec.x,
            ordered,
            "temporal, numeric, or an ordered categorical dimension",
        )
    elif spec.chart_type is ChartType.SCATTER:
        assert spec.x is not None
        _require_role(result, spec.x, numeric, "numeric")
    elif spec.chart_type is ChartType.BOX and spec.x:
        _require_role(result, spec.x, categorical, "categorical")
    elif spec.chart_type is ChartType.HEATMAP:
        assert spec.x is not None
        _require_role(
            result,
            spec.x,
            dimensions,
            "categorical, temporal, or already-binned numeric",
        )
        _require_role(
            result,
            spec.y[0],
            dimensions,
            "categorical, temporal, or already-binned numeric",
        )
    elif spec.chart_type is ChartType.MAP:
        location_roles = {*dimensions, AnalyticalRole.NUMERIC}
        if spec.location:
            _require_role(
                result,
                spec.location,
                location_roles,
                "a usable location identifier",
            )
        if spec.region:
            _require_role(
                result,
                spec.region,
                location_roles,
                "a usable region identifier",
            )

    numeric_columns: list[str] = [
        name for name in (spec.lower_bound, spec.upper_bound, spec.error_y) if name
    ]
    if spec.chart_type in {
        ChartType.BAR,
        ChartType.LINE,
        ChartType.AREA,
        ChartType.SCATTER,
        ChartType.PIE,
        ChartType.BOX,
        ChartType.WATERFALL,
        ChartType.FUNNEL,
    }:
        numeric_columns.extend(spec.y)
    if spec.secondary_y:
        numeric_columns.append(spec.secondary_y)
    if spec.chart_type is ChartType.HISTOGRAM and spec.x:
        numeric_columns.append(spec.x)
    if spec.size:
        numeric_columns.append(spec.size)
    if spec.value:
        numeric_columns.append(spec.value)
    if spec.latitude:
        numeric_columns.append(spec.latitude)
    if spec.longitude:
        numeric_columns.append(spec.longitude)
    for column in numeric_columns:
        _require_role(result, column, numeric, "numeric")
        if not _has_numeric_value(rows, column):
            raise ValueError(f"Chart column {column!r} has no usable numeric values.")
    if spec.size and not _has_nonnegative_numeric_value(rows, spec.size):
        raise ValueError("A size column requires nonnegative numeric values.")

    if spec.chart_type is ChartType.PIE and not _has_nonnegative_numeric_value(
        rows, spec.y[0]
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
            "A coordinate map requires at least one valid latitude/longitude pair."
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
            if row.get(category_column) is not None and _is_number(row.get(spec.y[0]))
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
            if row.get(spec.location) is not None and _is_number(row.get(spec.value))
        ]
        if len(set(locations)) != len(locations):
            raise ValueError(
                "Choropleth locations must be unique; aggregate duplicates in SQL."
            )
    if spec.chart_type in {ChartType.BAR, ChartType.BOX} and category_column:
        count = len({row.get(category_column) for row in rows})
        if count > 30:
            raise ValueError(
                "Bar and box charts may display at most 30 categories. "
                "Set category_limit or reshape the SQL result."
            )
