"""Strict declarative contracts for self-contained analytical reports."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from data_analytics_agent.agents.visualization.schemas import ChartSpec


class ReportingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportTheme(ReportingModel):
    """Semantic design controls interpreted by the trusted renderer."""

    primary_color: str = "#1E40AF"
    accent_color: str = "#D97706"
    surface_color: str = "#FFFFFF"
    background_color: str = "#F8FAFC"
    text_color: str = "#0F172A"
    muted_color: str = "#475569"
    font_style: Literal["modern", "editorial", "technical", "humanist"] = (
        "modern"
    )
    density: Literal["spacious", "balanced", "dense"] = "balanced"
    corner_style: Literal["square", "soft", "rounded"] = "soft"
    color_mode: Literal["light", "dark", "adaptive"] = "adaptive"

    @field_validator(
        "primary_color",
        "accent_color",
        "surface_color",
        "background_color",
        "text_color",
        "muted_color",
    )
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        if len(value) != 7 or value[0] != "#":
            raise ValueError("Report colors must use six-digit hex notation.")
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise ValueError(
                "Report colors must use six-digit hex notation."
            ) from exc
        return value.upper()

    @model_validator(mode="after")
    def validate_accessible_contrast(self) -> ReportTheme:
        def luminance(color: str) -> float:
            channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def ratio(first: str, second: str) -> float:
            lighter, darker = sorted(
                (luminance(first), luminance(second)), reverse=True
            )
            return (lighter + 0.05) / (darker + 0.05)

        pairs = [
            (self.text_color, self.background_color, "text/background"),
            (self.text_color, self.surface_color, "text/surface"),
            (self.muted_color, self.background_color, "muted/background"),
            (self.muted_color, self.surface_color, "muted/surface"),
            ("#FFFFFF", self.primary_color, "hero text/primary"),
        ]
        failures = [
            name for foreground, background, name in pairs if ratio(foreground, background) < 4.5
        ]
        if failures:
            raise ValueError(
                "Report theme must meet WCAG AA 4.5:1 contrast for: "
                + ", ".join(failures)
                + "."
            )
        return self


class ReportBrief(ReportingModel):
    """Coordinator interpretation of an open-ended reporting request."""

    purpose: str = Field(min_length=1, max_length=2_000)
    audience: str | None = Field(default=None, max_length=500)
    primary_questions: list[str] = Field(default_factory=list, max_length=20)
    key_messages: list[str] = Field(default_factory=list, max_length=20)
    design_direction: str = Field(default="", max_length=2_000)
    requested_sections: list[str] = Field(default_factory=list, max_length=30)
    evidence_result_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_analysis_ids: list[str] = Field(default_factory=list, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=10)


class ReportMetric(ReportingModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=120)
    change: str | None = Field(default=None, max_length=100)
    context: str | None = Field(default=None, max_length=240)


class ReportInfographicItem(ReportingModel):
    label: str = Field(min_length=1, max_length=100)
    value: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=600)


class ReportNarrativeBlock(ReportingModel):
    type: Literal["narrative"] = "narrative"
    title: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=1, max_length=20_000)
    emphasis: Literal["standard", "lead", "muted"] = "standard"


class ReportMetricsBlock(ReportingModel):
    type: Literal["metrics"] = "metrics"
    title: str | None = Field(default=None, max_length=160)
    metrics: list[ReportMetric] = Field(min_length=1, max_length=12)
    columns: int = Field(default=4, ge=1, le=6)


class ReportCalloutBlock(ReportingModel):
    type: Literal["callout"] = "callout"
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5_000)
    variant: Literal["insight", "note", "warning", "action"] = "insight"


class ReportInfographicBlock(ReportingModel):
    type: Literal["infographic"] = "infographic"
    title: str = Field(min_length=1, max_length=160)
    introduction: str | None = Field(default=None, max_length=2_000)
    items: list[ReportInfographicItem] = Field(min_length=2, max_length=12)
    layout: Literal["steps", "cards", "flow"] = "cards"


class ReportTableBlock(ReportingModel):
    type: Literal["table"] = "table"
    result_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)
    caption: str | None = Field(default=None, max_length=1_000)
    columns: list[str] = Field(default_factory=list, max_length=40)
    include_all_rows: bool = False
    row_limit: int = Field(default=25, ge=1, le=10_000)


class ReportChartBlock(ReportingModel):
    type: Literal["chart"] = "chart"
    chart: ChartSpec
    summary: str = Field(min_length=1, max_length=2_000)
    caption: str | None = Field(default=None, max_length=1_000)
    show_data_table: bool = True


class ReportStatisticalBlock(ReportingModel):
    type: Literal["statistical_analysis"] = "statistical_analysis"
    title: str = Field(min_length=1, max_length=160)
    analysis_id: str | None = None
    use_current_run: bool = False
    parent_result_id: str | None = None
    summary: str = Field(min_length=1, max_length=5_000)
    method: str = Field(default="", max_length=5_000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    interpretation: str = Field(default="", max_length=5_000)
    include_outputs: bool = True

    @model_validator(mode="after")
    def validate_analysis_reference(self) -> ReportStatisticalBlock:
        if bool(self.analysis_id) == self.use_current_run:
            raise ValueError(
                "Statistical blocks require exactly one of analysis_id or "
                "use_current_run=true."
            )
        if self.use_current_run and not self.parent_result_id:
            raise ValueError(
                "Current-run statistical blocks require parent_result_id."
            )
        return self


ReportBlock = Annotated[
    ReportNarrativeBlock
    | ReportMetricsBlock
    | ReportCalloutBlock
    | ReportInfographicBlock
    | ReportTableBlock
    | ReportChartBlock
    | ReportStatisticalBlock,
    Field(discriminator="type"),
]


class ReportSpec(ReportingModel):
    """Open, versioned document specification with no executable markup."""

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=500)
    eyebrow: str | None = Field(default=None, max_length=100)
    audience: str | None = Field(default=None, max_length=240)
    design_direction: str = Field(default="", max_length=1_000)
    theme: ReportTheme = Field(default_factory=ReportTheme)
    blocks: list[ReportBlock] = Field(min_length=1, max_length=50)
    footer: str | None = Field(default=None, max_length=2_000)
    previous_report_id: str | None = None


class ReportReference(ReportingModel):
    report_id: str
    title: str
    version: int = Field(ge=1)
    previous_report_id: str | None = None
    html_sha256: str
    created_at: datetime


class ReportArtifact(ReportingModel):
    report_id: str
    thread_id: str
    source_id: str
    title: str
    version: int = Field(ge=1)
    previous_report_id: str | None = None
    spec: ReportSpec
    html: str
    html_sha256: str
    renderer_version: str
    input_result_ids: list[str] = Field(default_factory=list)
    input_analysis_ids: list[str] = Field(default_factory=list)
    created_at: datetime

    def reference(self) -> ReportReference:
        return ReportReference(
            report_id=self.report_id,
            title=self.title,
            version=self.version,
            previous_report_id=self.previous_report_id,
            html_sha256=self.html_sha256,
            created_at=self.created_at,
        )


class ReportResponse(ReportingModel):
    report_id: str
    source_id: str
    title: str
    version: int
    previous_report_id: str | None = None
    html: str
    html_sha256: str
    renderer_version: str
    input_result_ids: list[str]
    input_analysis_ids: list[str]
    created_at: datetime


class ReportToolResult(ReportingModel):
    ok: Literal[True] = True
    report: ReportReference
    message: str


class ReportToolIssue(ReportingModel):
    """One compact, model-actionable report validation issue."""

    path: str
    message: str


class ReportToolFailure(ReportingModel):
    """Expected report-spec failure returned without failing the tool call."""

    ok: Literal[False] = False
    code: Literal[
        "invalid_report_json",
        "invalid_report_spec",
        "artifact_not_found",
        "artifact_not_ready",
        "report_render_failed",
    ]
    message: str
    retryable: bool = True
    issues: list[ReportToolIssue] = Field(default_factory=list, max_length=8)


class ResolvedStatisticalAnalysis(ReportingModel):
    """Renderer input for a stored or current-run statistical block."""

    reference_id: str
    parent_result_id: str
    answer: str
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
