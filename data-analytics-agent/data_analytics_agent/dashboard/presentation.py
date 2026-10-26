"""Metric display edits over immutable dashboard evidence and reports."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Annotated

from pydantic import Field, model_validator

from data_analytics_agent.dashboard.schemas import (
    DashboardModel,
    Identifier,
    MetricComponent,
)
from data_analytics_agent.dashboard.store import DashboardConflict
from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.reporting.formats import validate_number_format
from data_analytics_agent.reporting.schemas import ReportMetricsBlock, ReportSpec
from data_analytics_agent.reporting.tools import generate_report


class DashboardPresentationEdit(DashboardModel):
    expected_revision: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=100)
    metric_formats: dict[
        Identifier, Annotated[str, Field(min_length=1, max_length=20)]
    ] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def explicit_formats(self):
        for value in self.metric_formats.values():
            validate_number_format(value)
        return self


class DashboardPresentationRenderError(RuntimeError):
    """The previous dashboard/report pair remains current after rendering fails."""


def _binding(metric):
    return metric.result_id, metric.column, metric.row_index


def _digest(edit):
    return sha256(
        json.dumps(
            edit.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def edit_dashboard_presentation(services, dashboard_id, thread_id, source_id, edit):
    """Render first, then atomically commit the dashboard and matching report.

    Persistent request records retain completed results and rendered candidates.
    Retrying a failed render never starts a model, query or analytical run.
    """
    with services._lock:
        if thread_id in services.deleting_conversations:
            raise DashboardConflict("Wait for history deletion to finish.")
        conversation = services.conversations.get(thread_id)
        if conversation.source_id != source_id:
            raise StoreNotFound("Unknown dashboard in this conversation.")
        if conversation.active_run_id or thread_id in services.uploading_conversations:
            raise DashboardConflict("Finish active work before changing the dashboard.")
        previous = services.dashboards.get_revision(
            edit.expected_revision, thread_id, source_id=source_id
        )
        if previous.dashboard_id != dashboard_id:
            raise DashboardConflict(
                "The requested revision belongs to another dashboard."
            )
        storage = services.storage
        key = f"{dashboard_id}:{edit.request_id}"
        request_hash = _digest(edit)
        request = storage.get("dashboard_presentation_requests", key, dict)
        if request:
            if request["request_hash"] != request_hash:
                raise DashboardConflict(
                    "The request ID was reused with different content."
                )
            if request.get("revision_id"):
                return services.dashboards.get_revision(
                    request["revision_id"], thread_id, source_id=source_id
                )
            committed_request = storage.get(
                "dashboard_view_requests",
                f"{dashboard_id}:presentation:{edit.request_id}",
                dict,
            )
            if committed_request:
                committed = services.dashboards.get_revision(
                    committed_request["revision_id"], thread_id, source_id=source_id
                )
                if committed.report_id != request.get("report_id"):
                    raise DashboardConflict(
                        "The saved presentation request does not match its committed report."
                    )
                request.update(status="committed", revision_id=committed.revision_id)
                storage.put("dashboard_presentation_requests", key, request)
                return committed
        head = services.dashboards.get(dashboard_id, thread_id, source_id=source_id)
        if head.revision_id != previous.revision_id:
            raise DashboardConflict(
                "The dashboard changed. Reload before editing its presentation."
            )
        pending = services.dashboards.latest_action(
            dashboard_id, thread_id, source_id=source_id
        )
        if pending and pending.status in {"queued", "running"}:
            raise DashboardConflict(
                "Finish or resume the pending dashboard action before editing its presentation."
            )
        by_id = {component.id: component for component in previous.spec.components}
        if any(
            not isinstance(by_id.get(key), MetricComponent)
            for key in edit.metric_formats
        ):
            raise ValueError("Metric formats must name existing metric components.")
        revised = previous.spec.model_copy(deep=True)
        replacements = {}
        for component in revised.components:
            if component.id not in edit.metric_formats:
                continue
            metric = component.metric
            result = services.results.get(
                metric.result_id, thread_id, source_id=source_id
            )
            rows = result.read_rows(1, metric.row_index)
            if result.row_count and not rows:
                raise ValueError("The metric row is outside its saved evidence.")
            number_format = validate_number_format(
                edit.metric_formats[component.id],
                rows[0][metric.column] if rows else None,
            )
            component.metric = metric.model_copy(
                update={"number_format": number_format}
            )
            binding = _binding(metric)
            if (
                binding in replacements
                and replacements[binding].number_format != number_format
            ):
                raise ValueError(
                    "Metrics bound to the same saved cell require one report format."
                )
            replacements[binding] = component.metric
        for component in revised.components:
            if (
                isinstance(component, MetricComponent)
                and _binding(component.metric) in replacements
                and component.metric.number_format
                != replacements[_binding(component.metric)].number_format
            ):
                raise ValueError(
                    "Include all metrics bound to this saved cell with the same format."
                )
        request = request or {
            "thread_id": thread_id,
            "source_id": source_id,
            "dashboard_id": dashboard_id,
            "expected_revision": previous.revision_id,
            "request_hash": request_hash,
            "status": "preparing",
            "report_id": None,
            "revision_id": None,
        }
        if revised == previous.spec:
            request.update(
                status="committed",
                report_id=previous.report_id,
                revision_id=previous.revision_id,
            )
            storage.put("dashboard_presentation_requests", key, request)
            return previous
        run = services.runs.get(previous.run_id)
        if (run.thread_id, run.source_id) != (thread_id, source_id):
            raise StoreNotFound("The dashboard run is outside this conversation.")
        findings = run.findings or run.answer
        if findings is None:
            raise ValueError("The dashboard's published findings are unavailable.")
        # Validate bindings without applying new authoring rules to untouched
        # historical formats. Only the explicitly requested formats change.
        selected = {item.result_id for item in findings.results}
        if any(metric.result_id not in selected for metric in replacements.values()):
            raise ValueError(
                "Dashboard metrics must use their published saved evidence."
            )
        report = services.reports.get(
            previous.report_id, thread_id, source_id=source_id
        )
        found, blocks = set(), []
        for block in report.spec.blocks:
            if isinstance(block, ReportMetricsBlock):
                metrics = []
                for metric in block.metrics:
                    binding = _binding(metric)
                    if binding in replacements:
                        metric = metric.model_copy(
                            update={
                                "number_format": replacements[binding].number_format
                            }
                        )
                        found.add(binding)
                    metrics.append(metric)
                block = block.model_copy(update={"metrics": metrics})
            blocks.append(block)
        missing = [
            metric for binding, metric in replacements.items() if binding not in found
        ]
        for offset in range(0, len(missing), 12):
            blocks.append(ReportMetricsBlock(metrics=missing[offset : offset + 12]))
        report_spec = ReportSpec.model_validate(
            {
                **report.spec.model_dump(),
                "blocks": blocks,
                "previous_report_id": report.report_id,
            }
        )
        storage.put("dashboard_presentation_requests", key, request)
        revised_report = None
        if request.get("report_id"):
            revised_report = services.reports.get(
                request["report_id"], thread_id, source_id=source_id
            )
        if revised_report is None:
            try:
                # The immutable report already owns its published selections.
                # Later chart view edits can differ from the original run's
                # findings; preserve the report's exact scoped artifact IDs.
                revised_report = generate_report(
                    report_spec,
                    thread_id=thread_id,
                    source_id=source_id,
                    result_store=services.results,
                    analysis_store=services.analyses,
                    run_store=services.runs,
                    report_store=services.reports,
                )
                if set(revised_report.input_result_ids) != set(
                    report.input_result_ids
                ) or set(revised_report.input_analysis_ids) != set(
                    report.input_analysis_ids
                ):
                    raise ValueError(
                        "A presentation edit cannot change the report's saved evidence."
                    )
            except (ValueError, KeyError, IndexError, OSError) as exc:
                request.update(status="failed", error=str(exc))
                storage.put("dashboard_presentation_requests", key, request)
                raise DashboardPresentationRenderError(
                    "The revised report could not be rendered. The previous dashboard and report are still displayed; retry the edit."
                ) from exc
            request.update(
                status="ready", report_id=revised_report.report_id, error=None
            )
            storage.put("dashboard_presentation_requests", key, request)
        committed = services.dashboards.commit_view(
            previous,
            revised,
            request_id=f"presentation:{edit.request_id}",
            report_id=revised_report.report_id,
        )
        request.update(status="committed", revision_id=committed.revision_id)
        storage.put("dashboard_presentation_requests", key, request)
        return committed
