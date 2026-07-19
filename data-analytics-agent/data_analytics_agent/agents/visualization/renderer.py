"""Deterministic Plotly rendering for validated chart specifications."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data_analytics_agent.agents.visualization.geocoding import (
    USLocationResolver,
    normalize_us_state,
)
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    ChartType,
    Palette,
)
from data_analytics_agent.agents.visualization.validation import (
    presentation_rows,
)


@dataclass(frozen=True)
class RenderedChart:
    figure: go.Figure
    warnings: tuple[str, ...] = ()


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _palette(spec: ChartSpec) -> tuple[list[str], list[str]]:
    discrete = {
        Palette.DEFAULT: px.colors.qualitative.Safe,
        Palette.BLUES: px.colors.sequential.Blues[2:],
        Palette.VIRIDIS: px.colors.sequential.Viridis,
        Palette.PLASMA: px.colors.sequential.Plasma,
        Palette.TEAL: px.colors.sequential.Teal,
        Palette.SUNSET: px.colors.sequential.Sunset,
        Palette.RED_BLUE: px.colors.diverging.RdBu,
    }[spec.palette]
    continuous = {
        Palette.DEFAULT: px.colors.sequential.Teal,
        Palette.BLUES: px.colors.sequential.Blues,
        Palette.VIRIDIS: px.colors.sequential.Viridis,
        Palette.PLASMA: px.colors.sequential.Plasma,
        Palette.TEAL: px.colors.sequential.Teal,
        Palette.SUNSET: px.colors.sequential.Sunset,
        Palette.RED_BLUE: px.colors.diverging.RdBu,
    }[spec.palette]
    return list(discrete), list(continuous)


def _numeric_column(
    frame: pd.DataFrame,
    column: str,
    warnings: list[str],
    *,
    nonnegative: bool = False,
) -> None:
    invalid = 0

    def clean(value: Any) -> float | int | None:
        nonlocal invalid
        if value is None:
            return None
        if not _is_number(value) or (nonnegative and value < 0):
            invalid += 1
            return None
        return value

    frame[column] = frame[column].map(clean)
    if invalid:
        warnings.append(
            f"Excluded {invalid} incompatible value(s) from {column!r}."
        )


def _drop_missing(
    frame: pd.DataFrame,
    columns: list[str],
    warnings: list[str],
) -> pd.DataFrame:
    before = len(frame)
    usable = frame.dropna(subset=columns)
    dropped = before - len(usable)
    if dropped:
        warnings.append(
            f"Excluded {dropped} row(s) missing required chart values."
        )
    if usable.empty:
        raise ValueError("No usable chart points remain after validation.")
    return usable


def _style_figure(fig: go.Figure, spec: ChartSpec) -> go.Figure:
    fig.update_layout(
        title={"text": spec.title, "x": 0.01, "xanchor": "left"},
        margin={"l": 24, "r": 24, "t": 64, "b": 32},
        legend={
            "title_text": "",
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
        hovermode="closest",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    if spec.chart_type not in {ChartType.PIE, ChartType.MAP}:
        if (
            spec.chart_type is ChartType.BAR
            and spec.orientation == "horizontal"
        ):
            x_title = spec.y_label or (
                spec.y[0] if len(spec.y) == 1 else None
            )
            y_title = spec.x_label or spec.x
        else:
            x_title = spec.x_label or spec.x
            y_title = spec.y_label or (
                spec.y[0] if len(spec.y) == 1 else None
            )
        fig.update_xaxes(
            title_text=x_title,
            showgrid=False,
            zeroline=False,
        )
        fig.update_yaxes(
            title_text=y_title,
            gridcolor="rgba(127,127,127,0.18)",
            zeroline=False,
        )
    return fig


def _render_cartesian(
    frame: pd.DataFrame,
    spec: ChartSpec,
    warnings: list[str],
) -> go.Figure:
    discrete, continuous = _palette(spec)
    for column in spec.y:
        _numeric_column(frame, column, warnings)
    if spec.size:
        _numeric_column(frame, spec.size, warnings, nonnegative=True)
    y_mapping: str | list[str] = (
        spec.y[0] if len(spec.y) == 1 else spec.y
    )

    if spec.chart_type is ChartType.BAR:
        frame = _drop_missing(
            frame,
            [spec.x] if spec.x else [],
            warnings,
        )
        missing_points = int(frame[spec.y].isna().sum().sum())
        if missing_points:
            warnings.append(
                f"Excluded {missing_points} missing bar point(s)."
            )
        frame = frame.loc[frame[spec.y].notna().any(axis=1)]
        if frame.empty:
            raise ValueError("No usable chart points remain after validation.")
        if spec.orientation == "horizontal":
            return px.bar(
                frame,
                x=y_mapping,
                y=spec.x,
                color=spec.color,
                orientation="h",
                barmode="group",
                color_discrete_sequence=discrete,
                color_continuous_scale=continuous,
            )
        return px.bar(
            frame,
            x=spec.x,
            y=y_mapping,
            color=spec.color,
            barmode="group",
            color_discrete_sequence=discrete,
            color_continuous_scale=continuous,
        )
    if spec.chart_type is ChartType.LINE:
        frame = _drop_missing(frame, [spec.x] if spec.x else [], warnings)
        return px.line(
            frame,
            x=spec.x,
            y=y_mapping,
            color=spec.color,
            markers=True,
            color_discrete_sequence=discrete,
        )
    if spec.chart_type is ChartType.AREA:
        frame = _drop_missing(frame, [spec.x] if spec.x else [], warnings)
        return px.area(
            frame,
            x=spec.x,
            y=y_mapping,
            color=spec.color,
            color_discrete_sequence=discrete,
        )
    if spec.chart_type is ChartType.SCATTER:
        frame = _drop_missing(
            frame,
            [
                column
                for column in [spec.x, spec.y[0], spec.size]
                if column
            ],
            warnings,
        )
        return px.scatter(
            frame,
            x=spec.x,
            y=spec.y[0],
            color=spec.color,
            size=spec.size,
            color_discrete_sequence=discrete,
            color_continuous_scale=continuous,
            size_max=42,
        )
    if spec.chart_type is ChartType.HISTOGRAM:
        assert spec.x is not None
        _numeric_column(frame, spec.x, warnings)
        frame = _drop_missing(frame, [spec.x], warnings)
        return px.histogram(
            frame,
            x=spec.x,
            color=spec.color,
            nbins=spec.bin_count,
            color_discrete_sequence=discrete,
        )
    if spec.chart_type is ChartType.BOX:
        points = False if spec.box_points == "none" else spec.box_points
        frame = _drop_missing(
            frame,
            [column for column in [spec.x, spec.y[0]] if column],
            warnings,
        )
        return px.box(
            frame,
            x=spec.x,
            y=spec.y[0],
            color=spec.color,
            points=points,
            color_discrete_sequence=discrete,
        )
    raise ValueError(f"Unsupported Cartesian chart {spec.chart_type}.")


def _render_pie(
    frame: pd.DataFrame,
    spec: ChartSpec,
    warnings: list[str],
) -> go.Figure:
    assert spec.x is not None
    values = spec.y[0]
    _numeric_column(frame, values, warnings, nonnegative=True)
    frame = _drop_missing(frame, [spec.x, values], warnings)
    discrete, _ = _palette(spec)
    return px.pie(
        frame,
        names=spec.x,
        values=values,
        hole=0.45 if spec.donut else 0,
        color_discrete_sequence=discrete,
    )


def _render_heatmap(
    frame: pd.DataFrame,
    spec: ChartSpec,
    warnings: list[str],
) -> go.Figure:
    assert spec.x is not None and spec.value is not None
    y_column = spec.y[0]
    _numeric_column(frame, spec.value, warnings)
    frame = _drop_missing(
        frame,
        [spec.x, y_column, spec.value],
        warnings,
    )
    matrix = frame.pivot(
        index=y_column,
        columns=spec.x,
        values=spec.value,
    )
    _, continuous = _palette(spec)
    return go.Figure(
        data=go.Heatmap(
            x=list(matrix.columns),
            y=list(matrix.index),
            z=matrix.to_numpy(),
            colorscale=continuous,
            colorbar={"title": spec.value},
            hoverongaps=False,
        )
    )


def _render_map(
    frame: pd.DataFrame,
    spec: ChartSpec,
    warnings: list[str],
    resolver: USLocationResolver,
) -> go.Figure:
    discrete, continuous = _palette(spec)
    if spec.map_mode == "choropleth":
        assert spec.location is not None and spec.value is not None
        _numeric_column(frame, spec.value, warnings)
        frame = _drop_missing(
            frame,
            [spec.location, spec.value],
            warnings,
        )
        if spec.location_mode == "us_state":
            frame["__location_code"] = frame[spec.location].map(
                normalize_us_state
            )
            valid_states = {
                "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC",
                "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
                "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
                "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
                "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
                "VT", "VA", "WA", "WV", "WI", "WY",
            }
            valid = frame["__location_code"].isin(valid_states)
        else:
            frame["__location_code"] = frame[spec.location].map(
                lambda value: str(value).strip().upper()
            )
            valid = frame["__location_code"].str.fullmatch(r"[A-Z]{3}")
        invalid_locations = int((~valid).sum())
        if invalid_locations:
            warnings.append(
                f"Excluded {invalid_locations} unrecognized map location(s)."
            )
        frame = frame.loc[valid]
        if frame.empty:
            raise ValueError("No map locations could be resolved.")
        locations = "__location_code"
        return px.choropleth(
            frame,
            locations=locations,
            locationmode=(
                "USA-states"
                if spec.location_mode == "us_state"
                else "ISO-3"
            ),
            color=spec.value,
            scope="usa" if spec.location_mode == "us_state" else None,
            color_continuous_scale=continuous,
        )

    resolved_rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for row in frame.to_dict(orient="records"):
        point = None
        label = ""
        if spec.location_mode == "coordinates":
            latitude = row.get(spec.latitude)
            longitude = row.get(spec.longitude)
            if (
                _is_number(latitude)
                and _is_number(longitude)
                and -90 <= latitude <= 90
                and -180 <= longitude <= 180
            ):
                point = (float(latitude), float(longitude))
            label = f"{latitude}, {longitude}"
        elif spec.location_mode == "us_zip":
            assert spec.location is not None
            label = str(row.get(spec.location) or "")
            resolved = resolver.resolve_zip(row.get(spec.location))
            if resolved:
                point = (resolved.latitude, resolved.longitude)
        elif spec.location_mode == "us_city_state":
            assert spec.location is not None and spec.region is not None
            label = (
                f"{row.get(spec.location) or ''}, "
                f"{row.get(spec.region) or ''}"
            )
            resolved = resolver.resolve_city_state(
                row.get(spec.location),
                row.get(spec.region),
            )
            if resolved:
                point = (resolved.latitude, resolved.longitude)
        if point is None:
            unresolved.append(label)
            continue
        resolved_rows.append(
            {
                **row,
                "__latitude": point[0],
                "__longitude": point[1],
                "__location_label": label,
            }
        )
    if not resolved_rows:
        raise ValueError("No map locations could be resolved.")
    if unresolved:
        sample = ", ".join(repr(item) for item in unresolved[:5])
        warnings.append(
            f"Mapped {len(resolved_rows)} of {len(frame)} locations. "
            f"Unresolved sample: {sample}."
        )
    mapped = pd.DataFrame(resolved_rows)
    if spec.value:
        _numeric_column(mapped, spec.value, warnings, nonnegative=True)
        mapped = _drop_missing(mapped, [spec.value], warnings)
    figure = px.scatter_geo(
        mapped,
        lat="__latitude",
        lon="__longitude",
        hover_name="__location_label",
        size=spec.value,
        color=spec.color or spec.value,
        size_max=40,
        color_discrete_sequence=discrete,
        color_continuous_scale=continuous,
    )
    figure.update_geos(fitbounds="locations", visible=True)
    return figure


def build_chart(
    spec: ChartSpec,
    rows: list[dict[str, Any]],
    *,
    resolver: USLocationResolver | None = None,
) -> RenderedChart:
    """Build one Plotly figure from a previously validated ChartSpec."""

    warnings: list[str] = []
    presented_rows = presentation_rows(rows, spec)
    category_column = (
        spec.location if spec.chart_type is ChartType.MAP else spec.x
    )
    if spec.category_limit is not None and category_column is not None:
        all_categories = {
            (type(row.get(category_column)), str(row.get(category_column)))
            for row in rows
            if row.get(category_column) is not None
        }
        displayed_categories = {
            (type(row.get(category_column)), str(row.get(category_column)))
            for row in presented_rows
            if row.get(category_column) is not None
        }
        if len(displayed_categories) < len(all_categories):
            warnings.append(
                f"Displaying {len(displayed_categories)} of "
                f"{len(all_categories)} categories, ordered by "
                f"{spec.sort_by} {spec.sort_direction}."
            )
    frame = pd.DataFrame(presented_rows)
    if frame.empty:
        raise ValueError("No rows remain for chart rendering.")

    if spec.chart_type is ChartType.PIE:
        figure = _render_pie(frame, spec, warnings)
    elif spec.chart_type is ChartType.HEATMAP:
        figure = _render_heatmap(frame, spec, warnings)
    elif spec.chart_type is ChartType.MAP:
        figure = _render_map(
            frame,
            spec,
            warnings,
            resolver or USLocationResolver(),
        )
    else:
        figure = _render_cartesian(frame, spec, warnings)
    return RenderedChart(
        figure=_style_figure(figure, spec),
        warnings=tuple(dict.fromkeys(warnings)),
    )
