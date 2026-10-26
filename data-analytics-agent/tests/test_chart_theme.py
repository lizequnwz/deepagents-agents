"""One saved chart keeps its palette and font across interactive and HTML views."""

import json
import re

from fastapi.testclient import TestClient
import plotly.express as px
import pytest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.visualization.renderer import PRODUCT_CHART_STYLE
from data_analytics_agent.visualization.schemas import ChartRequest
from data_analytics_agent.visualization.tools import create_chart_tool


def report_figure(document):
    invocation = re.search(r'Plotly\.newPlot\(\s*"report-chart-\d+",\s*', document)
    assert invocation is not None
    decoder = json.JSONDecoder()
    data, end = decoder.raw_decode(document[invocation.end() :])
    remainder = document[invocation.end() + end :].lstrip().removeprefix(",").lstrip()
    layout, _ = decoder.raw_decode(remainder)
    return {"data": data, "layout": layout}


@pytest.mark.parametrize("palette", ["default", "blues"])
def test_saved_chart_theme_agrees_across_api_dashboard_and_report(
    workspace, test_settings, palette
):
    w = workspace
    result = w.results.save(
        columns=["month", "current", "baseline"],
        rows=[
            {"month": "2026-01", "current": 10, "baseline": 9},
            {"month": "2026-02", "current": 20, "baseline": 18},
        ],
        thread_id=w.thread,
        source_id="test",
    )
    created = create_chart_tool(w.results, w.runs, source_id="test").func(
        spec=ChartRequest(
            result_id=result.result_id,
            chart_type="line",
            title="Current and baseline",
            x="month",
            y=["current", "baseline"],
            palette=palette,
        ),
        runtime=w.runtime("theme-chart"),
    )
    assert created["ok"], created
    chart_id = created["chart"]["chart_id"]
    findings = resolve_answer(
        CoordinatorResponse(
            answer="Current and baseline in source units.",
            result_ids=[result.result_id],
            chart_ids=[chart_id],
        ),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    w.runs.publish(w.run, findings)
    report = generate_report(
        ReportSpec(
            title="Current and baseline",
            blocks=[{"type": "chart", "chart_id": chart_id, "summary": "Saved values"}],
        ),
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
        findings=findings,
    )
    w.runs.attach_report(w.run, report.reference())
    w.runs.complete(w.run, findings.model_copy(update={"report": report.reference()}))
    services = Services(
        settings=test_settings,
        storage=w.storage,
        results=w.results,
        runs=w.runs,
        conversations=w.conversations,
        analyses=w.analyses,
        reports=w.reports,
    )
    dashboards = DashboardService(
        w.results, w.analyses, w.runs, w.reports, services.dashboards
    )
    revision = dashboards.create_from_report(
        w.run, thread_id=w.thread, source_id="test"
    )
    dashboard = dashboards.view(revision.dashboard_id, w.thread, source_id="test")
    dashboard_figure = next(c.figure for c in dashboard.components if c.type == "chart").model_dump(mode="json")
    with TestClient(create_app(services)) as client:
        response = client.get(f"/api/conversations/{w.thread}/charts/{chart_id}/figure")
        assert response.status_code == 200, response.text
        api_figure = response.json()
    expected = (
        PRODUCT_CHART_STYLE.discrete_colors[:2]
        if palette == "default"
        else tuple(px.colors.sequential.Blues[2:4])
    )
    for figure in (api_figure, dashboard_figure, report_figure(report.html)):
        assert tuple(trace["line"]["color"] for trace in figure["data"]) == expected
        assert figure["layout"]["font"]["family"] == PRODUCT_CHART_STYLE.font_family
    assert api_figure["layout"]["title"]["text"] == "Current and baseline"
