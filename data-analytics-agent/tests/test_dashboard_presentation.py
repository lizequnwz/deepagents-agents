"""Metric format corrections preserve source values, history and report parity."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.dashboard.presentation import (
    DashboardPresentationEdit,
    DashboardPresentationRenderError,
    edit_dashboard_presentation,
)
from data_analytics_agent.dashboard.schemas import DashboardSpec
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.dashboard.store import DashboardConflict
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.formats import validate_number_format
from data_analytics_agent.reporting.schemas import ReportMetricsBlock, ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChatTurn, CoordinatorResponse
from data_analytics_agent.visualization.schemas import ChartRequest
from data_analytics_agent.visualization.tools import create_chart_tool


@pytest.fixture
def saved_dashboard(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Average amount")
    services.conversations.begin_run(thread, run)
    dataset = services.results.save(
        thread_id=thread,
        source_id="test",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 138.6}],
        executed_sql="SELECT category, amount FROM saved_facts",
    )
    chart = create_chart_tool(services.results, services.runs, source_id="test").func(
        spec=ChartRequest(
            result_id=dataset.result_id,
            chart_type="bar",
            title="Average amount",
            x="category",
            y=["amount"],
        ),
        runtime=SimpleNamespace(
            state={"thread_id": thread, "source_id": "test", "run_id": run},
            tool_call_id="original-chart",
        ),
    )
    assert chart["ok"], chart
    metric = {
        "label": "Average amount",
        "result_id": dataset.result_id,
        "column": "amount",
        "number_format": "0.00",
    }
    answer = resolve_answer(
        CoordinatorResponse(
            answer="The average amount is stored in source units.",
            result_ids=[dataset.result_id],
            chart_ids=[chart["chart_id"]],
        ),
        thread_id=thread,
        source_id="test",
        results=services.results,
        analyses=services.analyses,
        runs=services.runs,
    )
    services.runs.publish(run, answer)
    # Simulate existing persisted history. The permissive stored schema must
    # remain readable even after new authoring boundaries become strict.
    report = generate_report(
        ReportSpec(
            title="Average amount",
            blocks=[
                {"type": "metrics", "metrics": [metric]},
                {
                    "type": "chart",
                    "chart_id": chart["chart_id"],
                    "summary": "Average amount",
                },
            ],
        ),
        thread_id=thread,
        source_id="test",
        result_store=services.results,
        analysis_store=services.analyses,
        run_store=services.runs,
        report_store=services.reports,
        findings=answer,
    )
    services.runs.attach_report(run, report.reference())
    answer = answer.model_copy(update={"report": report.reference()})
    services.runs.complete(run, answer)
    services.conversations.complete_run(
        thread, run, ChatTurn(run_id=run, user_message="Average amount", answer=answer)
    )
    spec = DashboardSpec.model_validate(
        {
            "title": "Average amount",
            "components": [
                {"type": "metric", "id": "average", "metric": metric},
                {"type": "chart", "id": "chart", "chart_id": chart["chart_id"]},
            ],
        }
    )
    candidate = services.dashboards.create_candidate(
        spec,
        thread_id=thread,
        source_id="test",
        run_id=run,
        question="Average amount",
        request_id="original-dashboard",
    )
    services.dashboards.finalize_for_run(run, report.report_id)
    revision = services.dashboards.get(candidate.dashboard_id, thread, source_id="test")
    for name in (
        "manager",
        "agent_for_source",
        "backend_for_source",
        "source",
        "require_ready_source",
    ):
        setattr(
            services,
            name,
            Mock(side_effect=AssertionError(f"Presentation must not call {name}")),
        )
    service = DashboardService(
        services.results,
        services.analyses,
        services.runs,
        services.reports,
        services.dashboards,
    )
    edit = DashboardPresentationEdit(
        expected_revision=revision.revision_id,
        request_id="format-average",
        metric_formats={"average": ",.2f"},
    )
    return SimpleNamespace(
        services=services,
        service=service,
        thread=thread,
        run=run,
        dataset=dataset,
        report=report,
        answer=answer,
        revision=revision,
        edit=edit,
        url=f"/api/conversations/{thread}/dashboards/{revision.dashboard_id}/presentation",
    )


def apply(w, edit=None):
    return edit_dashboard_presentation(
        w.services, w.revision.dashboard_id, w.thread, "test", edit or w.edit
    )


@pytest.mark.parametrize(
    "invalid", ["0.00", ",.2", "", "invalid", "100000000000f", ".1000000000f", "c"]
)
def test_authoring_requires_an_explicit_bounded_numeric_type(invalid):
    with pytest.raises(ValueError):
        validate_number_format(invalid)


@pytest.mark.parametrize("valid", [",.2f", ".1%", "d", ".2e", ".2E", ".3g", "+,.2f"])
def test_explicit_fixed_scientific_and_general_formats_are_preserved(valid):
    assert validate_number_format(valid) == valid


def test_saved_implicit_format_remains_readable_and_correction_is_evidence_bound(
    saved_dashboard,
):
    w = saved_dashboard
    before_datasets = w.services.storage.load("datasets", dict)
    before_charts = w.services.storage.load("charts", dict)
    before_runs = w.services.storage.load("runs", dict)
    before_conversation = w.services.storage.get("conversations", w.thread, dict)
    assert (
        w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
        .components[0]
        .formatted_value
        == "1e+02"
    )
    revised = apply(w)
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    assert view.components[0].value == 138.6
    assert view.components[0].formatted_value == "138.60"
    assert revised.version == 2 and revised.report_id != w.report.report_id
    report = w.services.reports.get(revised.report_id, w.thread, source_id="test")
    metrics = [
        metric
        for block in report.spec.blocks
        if isinstance(block, ReportMetricsBlock)
        for metric in block.metrics
    ]
    assert metrics[0].number_format == ",.2f" and "138.60" in report.html
    assert report.previous_report_id == w.report.report_id and report.version == 2
    assert report.input_result_ids == w.report.input_result_ids
    assert w.services.storage.load("datasets", dict) == before_datasets
    assert w.services.storage.load("charts", dict) == before_charts
    assert w.services.storage.load("runs", dict) == before_runs
    assert (
        w.services.storage.get("conversations", w.thread, dict) == before_conversation
    )
    assert (
        w.services.reports.get(w.report.report_id, w.thread, source_id="test")
        == w.report
    )
    assert (
        w.services.dashboards.get_revision(
            w.revision.revision_id, w.thread, source_id="test"
        )
        == w.revision
    )
    assert (
        w.services.results.get(
            w.dataset.result_id, w.thread, source_id="test"
        ).read_rows(1)[0]["amount"]
        == 138.6
    )
    for name in (
        "manager",
        "agent_for_source",
        "backend_for_source",
        "source",
        "require_ready_source",
    ):
        getattr(w.services, name).assert_not_called()


def test_request_replay_survives_restart_and_does_not_render_another_report(
    saved_dashboard,
):
    w = saved_dashboard
    revised = apply(w)
    reports = w.services.storage.load("reports", dict)
    restarted = Services(settings=w.services.settings)
    assert (
        edit_dashboard_presentation(
            restarted, revised.dashboard_id, w.thread, "test", w.edit
        )
        == revised
    )
    assert restarted.storage.load("reports", dict) == reports
    # Recover the small post-commit request-cache write after an interrupted
    # response; the dashboard transaction already records its exact revision.
    key = f"{revised.dashboard_id}:{w.edit.request_id}"
    request = restarted.storage.get("dashboard_presentation_requests", key, dict)
    request.update(status="ready", revision_id=None)
    restarted.storage.put("dashboard_presentation_requests", key, request)
    assert (
        edit_dashboard_presentation(
            restarted, revised.dashboard_id, w.thread, "test", w.edit
        )
        == revised
    )
    assert restarted.storage.load("reports", dict) == reports
    with pytest.raises(DashboardConflict, match="reused"):
        apply(w, w.edit.model_copy(update={"metric_formats": {"average": ".1f"}}))
    with pytest.raises(DashboardConflict, match="changed"):
        apply(w, w.edit.model_copy(update={"request_id": "stale-request"}))


def test_report_failure_preserves_head_and_retry_reuses_saved_evidence(
    saved_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import presentation

    w = saved_dashboard
    renderer = presentation.generate_report
    monkeypatch.setattr(
        presentation,
        "generate_report",
        Mock(side_effect=OSError("Synthetic render failure")),
    )
    with pytest.raises(
        DashboardPresentationRenderError, match="previous dashboard and report"
    ):
        apply(w)
    assert (
        w.services.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )
    records = w.services.storage.load("dashboard_presentation_requests", dict)
    assert next(iter(records.values()))["status"] == "failed"
    monkeypatch.setattr(presentation, "generate_report", renderer)
    revised = apply(w)
    assert revised.report_id != w.report.report_id
    assert (
        w.services.results.get(
            w.dataset.result_id, w.thread, source_id="test"
        ).read_rows(1)[0]["amount"]
        == 138.6
    )


def test_report_ready_before_failed_commit_is_reused(saved_dashboard, monkeypatch):
    from data_analytics_agent.dashboard import presentation

    w = saved_dashboard
    commit = w.services.dashboards.commit_view
    monkeypatch.setattr(
        w.services.dashboards,
        "commit_view",
        Mock(side_effect=DashboardConflict("Commit interrupted")),
    )
    with pytest.raises(DashboardConflict, match="interrupted"):
        apply(w)
    assert (
        w.services.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )
    reports = w.services.storage.load("reports", dict)
    monkeypatch.setattr(w.services.dashboards, "commit_view", commit)
    monkeypatch.setattr(
        presentation,
        "generate_report",
        Mock(side_effect=AssertionError("Must reuse rendered candidate")),
    )
    revised = apply(w)
    assert revised.report_id != w.report.report_id
    assert w.services.storage.load("reports", dict) == reports


def test_metric_edit_preserves_an_existing_chart_presentation_revision(saved_dashboard):
    from data_analytics_agent.presentation_edits import (
        ChartPresentationEdit,
        edit_chart_presentation,
    )

    w = saved_dashboard
    revised_answer = edit_chart_presentation(
        w.services,
        w.run,
        ChartPresentationEdit(
            report_id=w.report.report_id,
            chart_id=w.answer.charts[0].chart_id,
            title="Revised chart title",
        ),
    )
    spec = w.revision.spec.model_copy(deep=True)
    spec.components[1].chart_id = revised_answer.charts[0].chart_id
    w.revision = w.services.dashboards.commit_view(
        w.revision,
        spec,
        request_id="saved-chart-view",
        report_id=revised_answer.report.report_id,
    )
    corrected = apply(
        w, w.edit.model_copy(update={"expected_revision": w.revision.revision_id})
    )
    report = w.services.reports.get(corrected.report_id, w.thread, source_id="test")
    assert any(
        getattr(block, "chart_id", None) == revised_answer.charts[0].chart_id
        for block in report.spec.blocks
    )
    assert "138.60" in report.html
    assert w.services.runs.get(w.run).answer == revised_answer


def test_invalid_components_types_foreign_scope_and_report_hook_are_rejected(
    saved_dashboard,
):
    w = saved_dashboard
    for component in ("chart", "missing"):
        with pytest.raises(ValueError, match="metric components"):
            apply(w, w.edit.model_copy(update={"metric_formats": {component: ".2f"}}))
    with pytest.raises(ValueError, match="saved metric type"):
        apply(w, w.edit.model_copy(update={"metric_formats": {"average": "d"}}))
    with pytest.raises(ValueError, match="same scoped saved evidence"):
        w.services.dashboards.commit_view(
            w.revision,
            w.revision.spec,
            request_id="bad-report",
            report_id=w.report.report_id,
        )
    with pytest.raises(ValidationError):
        DashboardPresentationEdit(
            expected_revision=w.revision.revision_id,
            request_id="implicit",
            metric_formats={"average": "0.00"},
        )


def test_presentation_endpoint_returns_view_and_enforces_idle_and_stale_state(
    saved_dashboard, monkeypatch
):
    from data_analytics_agent.dashboard import presentation

    w = saved_dashboard
    with TestClient(create_app(w.services)) as client:
        payload = w.edit.model_dump(mode="json")
        invalid = client.post(
            w.url, json={**payload, "metric_formats": {"average": "0.00"}}
        )
        assert invalid.status_code == 422
        active = w.services.runs.create(w.thread, "test", "Active work")
        w.services.conversations.begin_run(w.thread, active)
        assert client.post(w.url, json=payload).status_code == 409
        w.services.runs.fail(active, "Test finished")
        w.services.conversations.fail_run(w.thread, active)
        renderer = presentation.generate_report
        monkeypatch.setattr(
            presentation, "generate_report", Mock(side_effect=OSError("Render failed"))
        )
        failed = client.post(w.url, json=payload)
        assert failed.status_code == 422, failed.text
        monkeypatch.setattr(presentation, "generate_report", renderer)
        response = client.post(w.url, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["components"][0]["formatted_value"] == "138.60"
        assert response.json()["revision"]["report_id"] != w.report.report_id
        assert (
            client.post(w.url, json=payload).json()["revision"]["revision_id"]
            == response.json()["revision"]["revision_id"]
        )
        assert (
            client.post(
                w.url, json={**payload, "request_id": "stale-request"}
            ).status_code
            == 409
        )
        w.services.deleting_conversations.add(w.thread)
        assert client.post(w.url, json=payload).status_code == 409


async def test_request_records_and_revised_report_are_deleted_with_history(
    saved_dashboard,
):
    from data_analytics_agent.history import delete_history

    w = saved_dashboard
    revised = apply(w)
    report = w.services.reports.get(revised.report_id, w.thread, source_id="test")
    assert w.services.storage.load("dashboard_presentation_requests", dict)
    await delete_history(w.services, {w.thread})
    assert w.services.storage.load("dashboard_presentation_requests", dict) == {}
    assert not Path(report.html_path).exists()
