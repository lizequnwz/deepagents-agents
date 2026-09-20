"""Explicit presentation edits over immutable evidence and agent-authored reports."""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_analytics_agent.reporting.schemas import ReportChartBlock, ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import FinalAnswer, RunStatus
from data_analytics_agent.visualization.schemas import ChartSpec, ChartType, Palette
from data_analytics_agent.visualization.validation import validate_chart_spec


class ChartPresentationEdit(BaseModel):
    """Only display fields may change; omitted fields retain their stored values."""

    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(min_length=1)
    chart_id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    x_label: str | None = Field(default=None, max_length=80)
    y_label: str | None = Field(default=None, max_length=80)
    secondary_y_label: str | None = Field(default=None, max_length=80)
    palette: Palette | None = None
    chart_type: ChartType | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        for name in ("title", "palette", "chart_type"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        if self.title is not None and not self.title.strip():
            raise ValueError("A chart title cannot be blank.")
        if not self.model_fields_set - {"report_id", "chart_id"}:
            raise ValueError("Choose at least one presentation change.")
        return self


class PresentationConflict(ValueError):
    pass


class PresentationRenderError(RuntimeError):
    pass


def current_presentation(storage, run_id, original):
    """Resolve the committed view without changing the original analytical turn."""
    view = storage.get("presentation_views", run_id, dict)
    return FinalAnswer.model_validate(view["answer"]) if view else original


def edit_chart_presentation(services, run_id: str, edit: ChartPresentationEdit):
    """Build a matching chart/report pair before publishing its view pointer.

    The caller serializes edits with conversation lifecycle changes. Failed
    candidates are recorded, and submitting the same edit retries rendering.
    Neither model creation nor source readiness/execution is involved.
    """
    run = services.runs.get(run_id)
    conversation = services.conversations.get(run.thread_id)
    if conversation.active_run_id or run.status != RunStatus.COMPLETED:
        raise PresentationConflict(
            "Finish or stop active work before editing a completed result."
        )
    answer = run.answer
    if not answer or not answer.report or answer.report.report_id != edit.report_id:
        raise PresentationConflict(
            "This report has changed. Reload the result before editing."
        )
    previous = next((c for c in answer.charts if c.chart_id == edit.chart_id), None)
    if previous is None:
        raise PresentationConflict("This chart is not part of the displayed result.")
    report = services.reports.get(
        edit.report_id, run.thread_id, source_id=run.source_id
    )
    if not any(
        isinstance(b, ReportChartBlock) and b.chart_id == edit.chart_id
        for b in report.spec.blocks
    ):
        raise ValueError("The displayed report does not contain this chart.")
    updates = edit.model_dump(exclude_unset=True, exclude={"report_id", "chart_id"})
    if all(getattr(previous, key) == value for key, value in updates.items()):
        return answer
    chart = ChartSpec.model_validate(
        {
            **previous.model_dump(),
            **updates,
            "chart_id": str(uuid4()),
            "previous_chart_id": previous.chart_id,
            "version": previous.version + 1,
        }
    )
    dataset = services.results.get(
        chart.result_id, run.thread_id, source_id=run.source_id
    )
    # A sampled line/scatter must not become a sampled distribution or total.
    if (
        dataset.chart_preparation
        and dataset.chart_preparation.sampling != "none"
        and chart.chart_type != previous.chart_type
    ):
        raise ValueError(
            "A downsampled chart cannot change type. Use the complete saved evidence to create a new chart."
        )
    validate_chart_spec(chart, dataset)
    blocks = [
        b.model_copy(
            update={
                "chart_id": chart.chart_id,
                "summary": chart.title if b.summary == previous.title else b.summary,
            }
        )
        if isinstance(b, ReportChartBlock) and b.chart_id == previous.chart_id
        else b
        for b in report.spec.blocks
    ]
    spec = ReportSpec.model_validate(
        {
            **report.spec.model_dump(),
            "blocks": blocks,
            "previous_report_id": report.report_id,
        }
    )
    storage = services.storage
    candidate = {
        "thread_id": run.thread_id,
        "source_id": run.source_id,
        "run_id": run_id,
        "edit": edit.model_dump(mode="json", exclude_unset=True),
        "chart_id": chart.chart_id,
        "status": "preparing",
        "error": None,
    }
    storage.put("presentation_edits", chart.chart_id, candidate, dict)
    storage.put(
        "charts",
        chart.chart_id,
        {
            "thread_id": run.thread_id,
            "source_id": run.source_id,
            "spec": chart.model_dump(mode="json"),
        },
        dict,
    )
    try:
        revised_report = generate_report(
            spec,
            thread_id=run.thread_id,
            source_id=run.source_id,
            result_store=services.results,
            analysis_store=services.analyses,
            run_store=services.runs,
            report_store=services.reports,
        )
    except (ValueError, KeyError, IndexError, OSError) as exc:
        candidate.update(status="failed", error=str(exc))
        storage.put("presentation_edits", chart.chart_id, candidate, dict)
        raise PresentationRenderError(
            "The revised report could not be rendered. Your previous chart and report are still displayed. Save the edit again to retry."
        ) from exc
    revised_answer = answer.model_copy(
        update={
            "charts": [
                chart if c.chart_id == previous.chart_id else c for c in answer.charts
            ],
            "report": revised_report.reference(),
        }
    )
    candidate.update(status="ready", report_id=revised_report.report_id)
    storage.put("presentation_edits", chart.chart_id, candidate, dict)
    # One atomic metadata write commits the pair; original turns/artifacts survive.
    storage.put(
        "presentation_views",
        run_id,
        {
            "thread_id": run.thread_id,
            "source_id": run.source_id,
            "answer": revised_answer.model_dump(mode="json"),
        },
        dict,
    )
    return revised_answer
