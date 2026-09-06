"""Strict chart contracts shared by the agent, API, and renderer."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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


class ChartSpec(VisualizationModel):
    """One reviewed, declarative chart over one saved result."""

    result_id: str
    chart_id: str = ""
    previous_chart_id: str | None = None
    source_result_id: str | None = None
    version: int = 1
    notes: list[str] = Field(default_factory=list)
    lower_bound: str | None = None
    upper_bound: str | None = None
    error_y: str | None = None
    chart_type: ChartType
    title: str
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    secondary_y: str | None = None
    color: str | None = None
    size: str | None = None
    value: str | None = None
    location: str | None = None
    region: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    map_mode: Literal["markers", "choropleth"] | None = None
    location_mode: (
        Literal[
            "coordinates",
            "us_zip",
            "us_city_state",
            "us_state",
            "iso_country",
        ]
        | None
    ) = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    sort_by: str | None = None
    sort_direction: Literal["ascending", "descending"] = "ascending"
    category_limit: int | None = None
    bin_count: int | None = None
    box_points: Literal["outliers", "all", "none"] = "outliers"
    donut: bool = False
    palette: Palette = Palette.DEFAULT
    x_label: str | None = None
    y_label: str | None = None
    secondary_y_label: str | None = None

    @field_validator("result_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Chart result_id and title must be nonempty.")
        return value

    @field_validator("title")
    @classmethod
    def validate_title_length(cls, value: str) -> str:
        if len(value) > 160:
            raise ValueError("Chart titles must be at most 160 characters.")
        return value

    @field_validator("y")
    @classmethod
    def validate_series_count(cls, value: list[str]) -> list[str]:
        if len(value) > 5:
            raise ValueError("Charts support at most five y series.")
        return value

    @field_validator("category_limit")
    @classmethod
    def validate_category_limit(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 30:
            raise ValueError("category_limit must be between 1 and 30.")
        return value

    @field_validator("bin_count")
    @classmethod
    def validate_bin_count(cls, value: int | None) -> int | None:
        if value is not None and not 5 <= value <= 100:
            raise ValueError("bin_count must be between 5 and 100.")
        return value

    @field_validator("x_label", "y_label", "secondary_y_label")
    @classmethod
    def validate_label_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 80:
            raise ValueError("Chart axis labels must be at most 80 characters.")
        return value

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
        if self.box_points != "outliers" and chart_type is not ChartType.BOX:
            raise ValueError("box_points is supported only for box charts.")
        if self.category_limit is not None and chart_type is ChartType.HISTOGRAM:
            raise ValueError("category_limit is not supported for histograms.")
        if self.category_limit is not None and self.sort_by is None:
            raise ValueError("category_limit requires an explicit meaningful sort_by.")
        if self.secondary_y is not None:
            if chart_type is not ChartType.BAR:
                raise ValueError("secondary_y is supported only for bar charts.")
            if len(self.y) != 1:
                raise ValueError("dual-axis bar charts require exactly one primary y.")
            if self.secondary_y == self.y[0]:
                raise ValueError("secondary_y must differ from the primary y.")
            if self.orientation != "vertical":
                raise ValueError("dual-axis bar charts require vertical orientation.")
            if self.color is not None:
                raise ValueError("dual-axis bar charts do not support color grouping.")
        elif self.secondary_y_label is not None:
            raise ValueError("secondary_y_label requires a secondary_y column.")

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
                    raise ValueError("coordinate maps require latitude and longitude.")
                if self.location is not None or self.region is not None:
                    raise ValueError("coordinate maps do not use location or region.")
            elif not self.location:
                raise ValueError("location-based maps require a location column.")
            if self.location_mode != "coordinates" and (
                self.latitude is not None or self.longitude is not None
            ):
                raise ValueError(
                    "latitude and longitude are used only by coordinate maps."
                )
            if self.location_mode == "us_city_state" and not self.region:
                raise ValueError("US city/state maps require a region column.")
            if self.location_mode != "us_city_state" and self.region is not None:
                raise ValueError("region is used only by US city/state maps.")
            if self.location_mode == "coordinates" and self.category_limit is not None:
                raise ValueError("category_limit is not supported for coordinate maps.")
            if self.map_mode == "choropleth" and self.location_mode not in {
                "us_state",
                "iso_country",
            }:
                raise ValueError("choropleth maps support US states or ISO countries.")
            if self.map_mode == "choropleth" and not self.value:
                raise ValueError("choropleth maps require a value column.")
            if self.map_mode == "choropleth" and self.color is not None:
                raise ValueError(
                    "choropleth maps use value for color and do not accept "
                    "a color grouping column."
                )
            if self.map_mode == "markers" and self.location_mode not in {
                "coordinates",
                "us_zip",
                "us_city_state",
            }:
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
        if bool(self.lower_bound) != bool(self.upper_bound):
            raise ValueError(
                "Uncertainty bands require both lower_bound and upper_bound."
            )
        if self.lower_bound and (
            chart_type is not ChartType.LINE or self.color or len(self.y) != 1
        ):
            raise ValueError("Uncertainty bands require a single-series line chart.")
        if self.error_y and (
            chart_type not in {ChartType.BAR, ChartType.SCATTER}
            or self.color
            or len(self.y) != 1
        ):
            raise ValueError("Error bars require a single-series bar or scatter chart.")
        return self
