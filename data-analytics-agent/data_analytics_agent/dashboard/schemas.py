"""Declarative dashboard contracts; all numerical values bind to saved evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_analytics_agent.reporting.schemas import ReportMetric


class DashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Identifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
]
FilterValue = str | int | float | bool | None


class ComponentBase(DashboardModel):
    id: Identifier
    span: Literal[1, 2, 3] = 1


class MetricComponent(ComponentBase):
    type: Literal["metric"] = "metric"
    metric: ReportMetric


class ChartComponent(ComponentBase):
    type: Literal["chart"] = "chart"
    chart_id: str | None = Field(default=None, min_length=1)
    empty_result_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, max_length=160)
    span: Literal[1, 2, 3] = 2

    @model_validator(mode="after")
    def chart_or_empty_population(self):
        if bool(self.chart_id) == bool(self.empty_result_id):
            raise ValueError(
                "A chart component requires one saved chart or one explicit empty result."
            )
        return self


class TableComponent(ComponentBase):
    type: Literal["table"] = "table"
    result_id: str = Field(min_length=1)
    title: str = Field(default="Supporting data", min_length=1, max_length=160)
    columns: list[str] = Field(default_factory=list, max_length=40)
    row_limit: int = Field(default=10, ge=1, le=10)
    span: Literal[1, 2, 3] = 3


class TextComponent(ComponentBase):
    type: Literal["text"] = "text"
    title: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=1, max_length=5_000)
    span: Literal[1, 2, 3] = 3


DashboardComponent = Annotated[
    MetricComponent | ChartComponent | TableComponent | TextComponent,
    Field(discriminator="type"),
]


class FilterBinding(DashboardModel):
    component_id: Identifier
    column: str = Field(min_length=1, max_length=200)


class DashboardFilter(DashboardModel):
    id: Identifier
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["category", "date_range"] = "category"
    description: str = Field(default="", max_length=500)
    bindings: list[FilterBinding] = Field(min_length=1, max_length=60)
    default_values: list[FilterValue] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_bindings(self):
        pairs = [(b.component_id, b.column) for b in self.bindings]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Filter bindings must be unique.")
        return self


class DashboardSpec(DashboardModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    components: list[DashboardComponent] = Field(min_length=1, max_length=60)
    filters: list[DashboardFilter] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_ids_and_explicit_scope(self):
        components = {c.id for c in self.components}
        if len(components) != len(self.components):
            raise ValueError("Dashboard component IDs must be unique.")
        filters = {f.id for f in self.filters}
        if len(filters) != len(self.filters):
            raise ValueError("Dashboard filter IDs must be unique.")
        if any(
            b.component_id not in components for f in self.filters for b in f.bindings
        ):
            raise ValueError("Filters must bind to declared components.")
        return self


class DashboardRevision(DashboardModel):
    dashboard_id: str
    revision_id: str
    version: int = Field(ge=1)
    thread_id: str
    source_id: str
    run_id: str
    report_id: str | None = None
    question: str
    spec: DashboardSpec
    applied_filters: dict[str, list[FilterValue]] = Field(default_factory=dict)
    saved_filter_values: dict[str, list[FilterValue]] = Field(default_factory=dict)
    created_at: datetime


class DashboardCandidate(DashboardModel):
    revision: DashboardRevision
    expected_revision: str | None = None
    request_id: str | None = None
    status: Literal["preparing", "committed", "failed"] = "preparing"
    error: str | None = None


class DashboardAction(DashboardModel):
    action: Literal["filter", "refresh", "drill"]
    expected_revision: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=100)
    filter_values: dict[str, list[FilterValue]] = Field(default_factory=dict)
    component_id: str | None = None
    question: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def valid_action_payload(self):
        if self.action != "filter" and self.filter_values:
            raise ValueError("Only filter actions can change filter values.")
        if self.action == "drill" and (not self.component_id or not self.question):
            raise ValueError("Drill actions require a component and a question.")
        if self.action != "drill" and (self.component_id or self.question):
            raise ValueError("Only drill actions accept a component and a question.")
        return self


class DashboardViewEdit(DashboardModel):
    expected_revision: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    component_order: list[str] | None = None
    component_spans: dict[str, Literal[1, 2, 3]] | None = None
    saved_filter_values: dict[str, list[FilterValue]] | None = None
    filters: list[DashboardFilter] | None = Field(default=None, max_length=12)


class DashboardActionRecord(DashboardModel):
    action_id: str
    dashboard_id: str
    revision_id: str
    request_id: str
    request_hash: str
    action: DashboardAction
    run_id: str | None = None
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    result_revision_id: str | None = None
    error: str | None = None
    created_at: datetime


class DashboardActionPlan(DashboardModel):
    question: str
    dashboard_id: str
    revision_id: str
    applied_filters: dict[str, list[FilterValue]]
    affected_component_ids: list[str]


class ResolvedComponent(DashboardModel):
    id: str
    type: Literal["metric", "chart", "table", "text"]
    title: str
    span: int
    value: Any | None = None
    formatted_value: str | None = None
    figure: dict[str, Any] | None = None
    rows: list[dict[str, Any]] | None = None
    columns: list[str] | None = None
    body: str | None = None
    result_id: str | None = None
    analysis_result_id: str | None = None
    chart_id: str | None = None
    row_count: int | None = None
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResolvedFilter(DashboardFilter):
    options: list[FilterValue] = Field(default_factory=list)
    options_truncated: bool = False


class DashboardFreshness(DashboardModel):
    result_id: str
    queried_at: datetime
    completeness: Literal["unknown"] = "unknown"
    snapshot_kind: str
    truncated: bool


class DashboardView(DashboardModel):
    revision: DashboardRevision
    components: list[ResolvedComponent]
    filters: list[ResolvedFilter]
    freshness: list[DashboardFreshness]
    pending_action: DashboardActionRecord | None = None
