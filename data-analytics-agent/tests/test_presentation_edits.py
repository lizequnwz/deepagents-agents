"""Presentation-only edits preserve evidence, immutable history and report parity."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.presentation_edits import (
    ChartPresentationEdit,
    PresentationConflict,
    PresentationRenderError,
    edit_chart_presentation,
)
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChatTurn, FinalAnswer
from data_analytics_agent.stores import ConversationStore, RunStore
from data_analytics_agent.ui.api_client import AgentAPIClient, APIError
from data_analytics_agent.visualization.schemas import ChartSpec, ChartType
from data_analytics_agent.visualization.tools import create_chart_tool


@pytest.fixture
def presented(workspace):
    w = workspace
    dataset = w.results.save(
        columns=["month", "revenue"],
        rows=[{"month": "2025-01", "revenue": 10}, {"month": "2025-02", "revenue": 20}],
        thread_id=w.thread,
        source_id="test",
        executed_sql="SELECT month, revenue FROM sales",
    )
    output = create_chart_tool(w.results, w.runs, source_id="test").func(
        spec=ChartSpec(
            result_id=dataset.result_id,
            chart_type="line",
            title="Monthly revenue",
            x="month",
            y=["revenue"],
        ),
        runtime=w.runtime("chart"),
    )
    assert output["ok"]
    chart = ChartSpec.model_validate(output["chart"])
    services = SimpleNamespace(
        storage=w.storage,
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
        reports=w.reports,
        conversations=w.conversations,
    )
    report = generate_report(
        ReportSpec(
            title="Revenue report",
            blocks=[
                {"type": "narrative", "body": "Revenue rose in the saved period."},
                {"type": "chart", "chart_id": chart.chart_id, "summary": chart.title},
            ],
        ),
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
    )
    answer = FinalAnswer(
        answer="Revenue rose.",
        primary_result_id=dataset.result_id,
        charts=[chart],
        report=report.reference(),
    )
    w.runs.publish(w.run, answer)
    w.runs.attach_report(w.run, report.reference())
    w.runs.complete(w.run, answer)
    w.conversations.complete_run(
        w.thread,
        w.run,
        ChatTurn(run_id=w.run, user_message="Show revenue", answer=answer),
    )
    w.services, w.answer, w.dataset, w.report = services, answer, dataset, report
    w.edit = ChartPresentationEdit(
        report_id=report.report_id, chart_id=chart.chart_id, title="Sales by month"
    )
    return w


def test_edit_keeps_evidence_and_commits_matching_revisions_across_restart(presented):
    w = presented
    before = w.storage.load("datasets", dict)
    revised = edit_chart_presentation(w.services, w.run, w.edit)
    chart = revised.charts[0]
    assert chart.title == "Sales by month"
    assert chart.result_id == w.answer.charts[0].result_id
    assert chart.previous_chart_id == w.answer.charts[0].chart_id and chart.version == 2
    report = w.reports.get(revised.report.report_id, w.thread)
    assert report.previous_report_id == w.report.report_id and report.version == 2
    assert report.spec.blocks[0] == w.report.spec.blocks[0]
    assert report.spec.blocks[1].chart_id == chart.chart_id
    assert "Sales by month" in report.html
    assert w.storage.load("datasets", dict) == before
    assert RunStore(w.storage).get(w.run).answer == revised
    assert ConversationStore(w.storage).get(w.thread).turns[0].answer == revised
    # Stored analytical turns, original report and original chart remain unchanged.
    original = w.storage.get("conversations", w.thread, dict)["turns"][0]["answer"]
    assert original == w.answer.model_dump(mode="json")
    assert w.reports.get(w.report.report_id, w.thread) == w.report
    with pytest.raises(PresentationConflict, match="changed"):
        edit_chart_presentation(w.services, w.run, w.edit)
    second = edit_chart_presentation(
        w.services,
        w.run,
        ChartPresentationEdit(
            report_id=revised.report.report_id, chart_id=chart.chart_id, palette="teal"
        ),
    )
    assert second.charts[0].version == 3 and second.report.version == 3
    assert second.report.previous_report_id == revised.report.report_id


def test_render_failure_retains_previous_pair_and_retry_uses_same_data(
    presented, monkeypatch
):
    import data_analytics_agent.presentation_edits as edits

    w = presented
    original = edits.generate_report

    def fail(*args, **kwargs):
        raise OSError("Synthetic rendering failure")

    monkeypatch.setattr(edits, "generate_report", fail)
    with pytest.raises(PresentationRenderError, match="previous chart and report"):
        edit_chart_presentation(w.services, w.run, w.edit)
    assert w.runs.get(w.run).answer == w.answer
    assert ConversationStore(w.storage).get(w.thread).turns[0].answer == w.answer
    candidates = w.storage.load("presentation_edits", dict)
    assert (
        len(candidates) == 1 and next(iter(candidates.values()))["status"] == "failed"
    )
    monkeypatch.setattr(edits, "generate_report", original)
    revised = edit_chart_presentation(w.services, w.run, w.edit)
    assert revised.report.version == 2
    assert revised.charts[0].result_id == w.answer.charts[0].result_id


def test_edit_rejects_incompatible_type_foreign_artifact_and_active_work(presented):
    w = presented
    with pytest.raises(ValueError, match="histogram"):
        edit_chart_presentation(
            w.services,
            w.run,
            w.edit.model_copy(update={"chart_type": ChartType.HISTOGRAM}),
        )
    with pytest.raises(PresentationConflict, match="not part"):
        edit_chart_presentation(
            w.services, w.run, w.edit.model_copy(update={"chart_id": "other-chart"})
        )
    assert not w.storage.load("presentation_edits", dict)
    other_run = w.runs.create(w.thread, "test", "Next question")
    w.conversations.begin_run(w.thread, other_run)
    with pytest.raises(PresentationConflict, match="active work"):
        edit_chart_presentation(w.services, w.run, w.edit)


def test_api_edits_need_no_source_or_model_and_reject_data_changes(
    presented, test_settings, monkeypatch
):
    w = presented
    services = Services(settings=test_settings, storage=w.storage)

    def forbidden(*args, **kwargs):
        raise AssertionError("A presentation edit must not access source or model")

    monkeypatch.setattr(services, "agent_for_source", forbidden)
    monkeypatch.setattr(services, "backend_for_source", forbidden)
    with TestClient(create_app(services)) as api:
        payload = w.edit.model_dump(exclude_unset=True)
        invalid = api.post(
            f"/api/runs/{w.run}/presentation", json={**payload, "result_id": "other"}
        )
        assert invalid.status_code == 422
        response = api.post(f"/api/runs/{w.run}/presentation", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["charts"][0]["title"] == w.edit.title
        assert (
            api.post(f"/api/runs/{w.run}/presentation", json=payload).status_code == 409
        )
        conversation = api.get(f"/api/conversations/{w.thread}").json()
        assert conversation["turns"][0]["answer"] == response.json()
        assert api.get(f"/api/runs/{w.run}").json()["answer"] == response.json()


def test_chart_controls_save_matching_report_and_collapse_preview(
    presented, test_settings, monkeypatch
):
    w = presented
    services = Services(settings=test_settings, storage=w.storage)
    with TestClient(create_app(services)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)

        def app_code(run_id, source_id):
            from data_analytics_agent.ui.components import render_answer
            from data_analytics_agent.ui.api_client import AgentAPIClient

            client = AgentAPIClient("http://presentation-test")
            render_answer(
                client,
                client.get_run(run_id)["answer"],
                turn_key=run_id,
                source_id=source_id,
            )

        app = AppTest.from_function(app_code, args=(w.run, "test")).run(timeout=15)
        assert not app.exception
        assert not app.warning, [w.value for w in app.warning]
        assert not app.error, [e.value for e in app.error]
        assert not next(
            e for e in [*app.expander, *app.status] if e.label == "Report preview"
        ).proto.expanded
        next(t for t in app.text_input if t.label == "Chart title").set_value(
            "Revised revenue"
        )
        next(b for b in app.button if b.label == "Save chart and report").click().run(
            timeout=15
        )
        assert not app.exception
        revised = services.runs.get(w.run).answer
        assert revised.charts[0].title == "Revised revenue"
        assert (
            "Revised revenue"
            in services.reports.get(revised.report.report_id, w.thread).html
        )


def test_unchanged_edit_does_not_create_revision(presented):
    w = presented
    edit = ChartPresentationEdit(
        report_id=w.report.report_id,
        chart_id=w.answer.charts[0].chart_id,
        title=w.answer.charts[0].title,
    )
    assert edit_chart_presentation(w.services, w.run, edit) == w.answer
    assert not w.storage.load("presentation_edits", dict)


def test_downsampled_chart_cannot_be_reinterpreted_as_another_type(presented):
    from data_analytics_agent.schemas import ChartDataPreparation

    w = presented
    w.dataset.chart_preparation = ChartDataPreparation(
        selected_columns=["month", "revenue"],
        input_row_count=10000,
        output_row_count=2,
        sampling="ordered_stride",
        order_by="month",
        stride=5000,
    )
    with pytest.raises(ValueError, match="downsampled"):
        edit_chart_presentation(
            w.services,
            w.run,
            ChartPresentationEdit(
                report_id=w.report.report_id,
                chart_id=w.answer.charts[0].chart_id,
                chart_type="bar",
            ),
        )
    # Title edits still preserve the same saved display population.
    assert (
        edit_chart_presentation(w.services, w.run, w.edit).charts[0].result_id
        == w.dataset.result_id
    )
