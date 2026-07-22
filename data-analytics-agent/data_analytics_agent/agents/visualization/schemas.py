"""Strict chart contracts shared by the agent, API, and renderer."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisualizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    SCATTER = "scatter"
    PIE = "pie"
    HISTOGRAM = "histogram"
    BOX = "box"
    HEATMAP = "heatmap"
    MAP = "map"


class Palette(StrEnum):
    DEFAULT = "default"
    BLUES = "blues"
    VIRIDIS = "viridis"
    PLASMA = "plasma"
    TEAL = "teal"
    SUNSET = "sunset"
    RED_BLUE = "red_blue"


class VisualizationOutcome(StrEnum):
    CHART_CREATED = "chart_created"
    NEEDS_SQL_RESHAPE = "needs_sql_reshape"
    CANNOT_CREATE = "cannot_create"


class ChartSpec(VisualizationModel):
    """One reviewed, declarative chart over one saved result."""

    result_id: str = Field(min_length=1)
    chart_type: ChartType
    title: str = Field(min_length=1, max_length=160)
    x: str | None = None
    y: list[str] = Field(default_factory=list, max_length=5)
    secondary_y: str | None = None
    color: str | None = None
    size: str | None = None
    value: str | None = None
    location: str | None = None
    region: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    map_mode: Literal["markers", "choropleth"] | None = None
    location_mode: Literal[
        "coordinates",
        "us_zip",
        "us_city_state",
        "us_state",
        "iso_country",
    ] | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    sort_by: str | None = None
    sort_direction: Literal["ascending", "descending"] = "ascending"
    category_limit: int | None = Field(default=None, ge=1, le=30)
    bin_count: int | None = Field(default=None, ge=5, le=100)
    box_points: Literal["outliers", "all", "none"] = "outliers"
    donut: bool = False
    palette: Palette = Palette.DEFAULT
    x_label: str | None = Field(default=None, max_length=80)
    y_label: str | None = Field(default=None, max_length=80)
    secondary_y_label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_shape(self) -> ChartSpec:
        chart_type = self.chart_type
        map_fields = {
            self.location,
            self.region,
            self.latitude,
            self.longitude,
            self.map_mode,
            self.location_mode,
        }
        if chart_type is not ChartType.MAP and any(
            value is not None for value in map_fields
        ):
            raise ValueError("map fields are supported only for map charts.")
        if (
            chart_type not in {ChartType.HEATMAP, ChartType.MAP}
            and self.value is not None
        ):
            raise ValueError("value is supported only for heatmaps and maps.")
        if self.size is not None and chart_type is not ChartType.SCATTER:
            raise ValueError("size is supported only for scatter charts.")
        if self.color is not None and chart_type in {
            ChartType.PIE,
            ChartType.HEATMAP,
        }:
            raise ValueError(f"color is not supported for {chart_type}.")
        if (
            self.box_points != "outliers"
            and chart_type is not ChartType.BOX
        ):
            raise ValueError("box_points is supported only for box charts.")
        if (
            self.category_limit is not None
            and chart_type is ChartType.HISTOGRAM
        ):
            raise ValueError(
                "category_limit is not supported for histograms."
            )
        if self.category_limit is not None and self.sort_by is None:
            raise ValueError(
                "category_limit requires an explicit meaningful sort_by."
            )
        if self.secondary_y is not None:
            if chart_type is not ChartType.BAR:
                raise ValueError(
                    "secondary_y is supported only for bar charts."
                )
            if len(self.y) != 1:
                raise ValueError(
                    "dual-axis bar charts require exactly one primary y."
                )
            if self.secondary_y == self.y[0]:
                raise ValueError(
                    "secondary_y must differ from the primary y."
                )
            if self.orientation != "vertical":
                raise ValueError(
                    "dual-axis bar charts require vertical orientation."
                )
            if self.color is not None:
                raise ValueError(
                    "dual-axis bar charts do not support color grouping."
                )
        elif self.secondary_y_label is not None:
            raise ValueError(
                "secondary_y_label requires a secondary_y column."
            )

        if chart_type in {
            ChartType.BAR,
            ChartType.LINE,
            ChartType.AREA,
        }:
            if not self.x or not self.y:
                raise ValueError(f"{chart_type} requires x and at least one y.")
        elif chart_type is ChartType.SCATTER:
            if not self.x or len(self.y) != 1:
                raise ValueError("scatter requires x and exactly one y.")
        elif chart_type is ChartType.PIE:
            if not self.x or len(self.y) != 1:
                raise ValueError("pie requires x and exactly one y.")
        elif chart_type is ChartType.HISTOGRAM:
            if not self.x or self.y:
                raise ValueError("histogram requires x and no y columns.")
            if self.bin_count is None:
                raise ValueError("histogram requires bin_count.")
        elif chart_type is ChartType.BOX:
            if len(self.y) != 1:
                raise ValueError("box requires exactly one y column.")
        elif chart_type is ChartType.HEATMAP:
            if not self.x or len(self.y) != 1 or not self.value:
                raise ValueError("heatmap requires x, one y, and value.")
        elif chart_type is ChartType.MAP:
            if self.x is not None or self.y or self.size is not None:
                raise ValueError("map charts do not use x, y, or size fields.")
            if self.map_mode is None or self.location_mode is None:
                raise ValueError("map requires map_mode and location_mode.")
            if self.location_mode == "coordinates":
                if not self.latitude or not self.longitude:
                    raise ValueError(
                        "coordinate maps require latitude and longitude."
                    )
                if self.location is not None or self.region is not None:
                    raise ValueError(
                        "coordinate maps do not use location or region."
                    )
            elif not self.location:
                raise ValueError(
                    "location-based maps require a location column."
                )
            if (
                self.location_mode != "coordinates"
                and (
                    self.latitude is not None
                    or self.longitude is not None
                )
            ):
                raise ValueError(
                    "latitude and longitude are used only by coordinate maps."
                )
            if (
                self.location_mode == "us_city_state"
                and not self.region
            ):
                raise ValueError(
                    "US city/state maps require a region column."
                )
            if (
                self.location_mode != "us_city_state"
                and self.region is not None
            ):
                raise ValueError(
                    "region is used only by US city/state maps."
                )
            if (
                self.location_mode == "coordinates"
                and self.category_limit is not None
            ):
                raise ValueError(
                    "category_limit is not supported for coordinate maps."
                )
            if (
                self.map_mode == "choropleth"
                and self.location_mode not in {"us_state", "iso_country"}
            ):
                raise ValueError(
                    "choropleth maps support US states or ISO countries."
                )
            if self.map_mode == "choropleth" and not self.value:
                raise ValueError("choropleth maps require a value column.")
            if self.map_mode == "choropleth" and self.color is not None:
                raise ValueError(
                    "choropleth maps use value for color and do not accept "
                    "a color grouping column."
                )
            if (
                self.map_mode == "markers"
                and self.location_mode not in {
                    "coordinates",
                    "us_zip",
                    "us_city_state",
                }
            ):
                raise ValueError(
                    "marker maps support coordinates, US ZIP codes, or "
                    "US city/state locations."
                )

        if self.orientation == "horizontal" and chart_type is not ChartType.BAR:
            raise ValueError("horizontal orientation is supported only for bar.")
        if len(self.y) > 1 and self.color is not None:
            raise ValueError(
                "multi-series charts cannot also use a color grouping column."
            )
        if self.donut and chart_type is not ChartType.PIE:
            raise ValueError("donut mode is supported only for pie.")
        if self.bin_count is not None and chart_type is not ChartType.HISTOGRAM:
            raise ValueError("bin_count is supported only for histogram.")
        return self


class VisualizationResult(VisualizationModel):
    """Terminal outcome from one visualization assignment."""

    outcome: VisualizationOutcome = VisualizationOutcome.CHART_CREATED
    result_id: str | None = None
    answer: str
    chart: ChartSpec | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> VisualizationResult:
        if self.outcome is VisualizationOutcome.CHART_CREATED:
            if self.chart is None:
                raise ValueError("chart_created requires a chart.")
            if self.result_id is None:
                self.result_id = self.chart.result_id
            elif self.result_id != self.chart.result_id:
                raise ValueError(
                    "Visualization result ID must match the chart result ID."
                )
        elif self.chart is not None:
            raise ValueError(
                f"{self.outcome.value} must not include a chart."
            )
        elif self.result_id is None:
            raise ValueError(
                f"{self.outcome.value} requires a result_id."
            )
        return self
