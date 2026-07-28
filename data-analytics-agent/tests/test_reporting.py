from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
import pytest
from streamlit.testing.v1 import AppTest

from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisResult,
    StatisticalOutput,
)
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.reporting.renderer import render_report
from data_analytics_agent.reporting.schemas import (
    ReportBrief,
    ReportSpec,
    ReportToolResult,
)
from data_analytics_agent.reporting.tools import create_create_report_tool
from data_analytics_agent.run_manager import _apply_report
from data_analytics_agent.schemas import FinalAnswer
from data_analytics_agent.stores import (
    ReportStore,
    ResultStore,
    RunStore,
    StatisticalAnalysisStore,
)


def _saved_result(results: ResultStore, *, thread_id: str = "thread-1"):
    return results.save(
        thread_id=thread_id,
        source_id="source-1",
        executed_sql="SELECT category, amount FROM metrics",
        columns=["category", "amount"],
        rows=[
            {"category": "A", "amount": 10},
            {"category": "B", "amount": 7},
        ],
        truncated=False,
        elapsed_ms=1.0,
        originating_question="Compare category amounts",
    )


def test_report_spec_rejects_executable_markup_and_inaccessible_theme() -> None:
    brief = ReportBrief(
        purpose="Explain the operational findings.",
        audience="Operations leaders",
        design_direction="Editorial infographic",
    )
    assert brief.audience == "Operations leaders"

    with pytest.raises(ValueError, match="extra"):
        ReportSpec.model_validate(
            {
                "title": "Unsafe",
                "blocks": [{"type": "narrative", "body": "Finding"}],
                "javascript": "alert(1)",
            }
        )

    with pytest.raises(ValueError, match="WCAG AA"):
        ReportSpec.model_validate(
            {
                "title": "Low contrast",
                "theme": {
                    "primary_color": "#FFFF00",
                    "text_color": "#EEEEEE",
                    "background_color": "#FFFFFF",
                },
                "blocks": [{"type": "narrative", "body": "Finding"}],
            }
        )


def test_create_report_exports_a_recursively_strict_openai_schema() -> None:
    tool = create_create_report_tool(
        ResultStore(),
        StatisticalAnalysisStore(),
        RunStore(),
        ReportStore(),
        source_id="source-1",
    )
    parameters = convert_to_openai_tool(tool, strict=True)["function"][
        "parameters"
    ]

    def assert_strict_objects(value) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                assert value.get("additionalProperties") is False
                assert value.get("required") == list(properties)
            for child in value.values():
                assert_strict_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict_objects(child)

    assert_strict_objects(parameters)
    theme = parameters["properties"]["spec"]["properties"]["theme"]
    assert "primary_color" in theme["required"]


def test_renderer_escapes_model_text_and_includes_all_requested_rows() -> None:
    results = ResultStore()
    saved = _saved_result(results)
    spec = ReportSpec.model_validate(
        {
            "title": "Category report",
            "subtitle": "<script>alert('unsafe')</script>",
            "blocks": [
                {
                    "type": "narrative",
                    "body": "The result is **reviewed**.\n- First point",
                },
                {
                    "type": "table",
                    "result_id": saved.result_id,
                    "title": "All categories",
                    "include_all_rows": True,
                },
            ],
        }
    )

    html = render_report(
        spec,
        results={saved.result_id: saved},
        analyses={},
        generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert "&lt;script&gt;alert" in html
    assert "<strong>reviewed</strong>" in html
    assert "<td>A</td>" in html and "<td>B</td>" in html
    assert "Content-Security-Policy" in html
    assert "sha256-" in html
    assert 'src="http' not in html
    assert 'href="http' not in html


def test_report_tool_enforces_scope_and_versions_revisions() -> None:
    results = ResultStore()
    saved = _saved_result(results)
    reports = ReportStore()
    tool = create_create_report_tool(
        results,
        StatisticalAnalysisStore(),
        RunStore(),
        reports,
        source_id="source-1",
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        }
    )
    first_spec = ReportSpec.model_validate(
        {
            "title": "First report",
            "blocks": [
                {
                    "type": "table",
                    "result_id": saved.result_id,
                    "title": "Metrics",
                }
            ],
        }
    )
    first = ReportToolResult.model_validate_json(tool.func(first_spec, runtime))
    revised_spec = first_spec.model_copy(
        update={
            "title": "Revised report",
            "previous_report_id": first.report.report_id,
        }
    )
    revised = ReportToolResult.model_validate_json(
        tool.func(revised_spec, runtime)
    )

    assert first.report.version == 1
    assert revised.report.version == 2
    assert revised.report.previous_report_id == first.report.report_id
    assert reports.get(
        revised.report.report_id,
        "thread-1",
        source_id="source-1",
    ).renderer_version == "1.0"

    wrong_thread = SimpleNamespace(
        state={
            "thread_id": "thread-2",
            "run_id": "run-2",
            "source_id": "source-1",
        }
    )
    with pytest.raises(ValueError, match="outside this"):
        tool.func(first_spec, wrong_thread)


def test_stored_statistical_analysis_can_be_embedded_with_figure() -> None:
    results = ResultStore()
    saved = _saved_result(results)
    analyses = StatisticalAnalysisStore()
    stored = analyses.save(
        thread_id="thread-1",
        source_id="source-1",
        analysis=StatisticalAnalysisResult(
            outcome="analysis_completed",
            parent_result_id=saved.result_id,
            answer="The estimate is 8.5.",
            method="Arithmetic mean.",
            outputs=[
                StatisticalOutput(name="Mean", kind="scalar", value=8.5),
                StatisticalOutput(
                    name="Diagnostic",
                    kind="figure",
                    image_base64="aW1hZ2U=",
                    media_type="image/png",
                ),
            ],
        ),
    )
    reports = ReportStore()
    tool = create_create_report_tool(
        results,
        analyses,
        RunStore(),
        reports,
        source_id="source-1",
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        }
    )
    spec = ReportSpec.model_validate(
        {
            "title": "Statistical report",
            "blocks": [
                {
                    "type": "statistical_analysis",
                    "title": "Estimate",
                    "analysis_id": stored.analysis_id,
                    "summary": "The estimate is 8.5.",
                }
            ],
        }
    )

    result = ReportToolResult.model_validate_json(tool.func(spec, runtime))
    artifact = reports.get(
        result.report.report_id,
        "thread-1",
        source_id="source-1",
    )
    assert result.report.title == "Statistical report"
    assert stored.analysis.analysis_id == stored.analysis_id
    assert "data:image/png;base64,aW1hZ2U=" in artifact.html
    assert "8.5" in artifact.html


def test_authoritative_report_tool_result_overrides_coordinator_copy() -> None:
    reports = ReportStore()
    spec = ReportSpec.model_validate(
        {"title": "Trusted", "blocks": [{"type": "narrative", "body": "Body"}]}
    )
    artifact = reports.save(
        thread_id="thread-1",
        source_id="source-1",
        spec=spec,
        html="<html>trusted</html>",
        input_result_ids=[],
        input_analysis_ids=[],
    )
    tool_result = ReportToolResult(
        report=artifact.reference(),
        message="Created.",
    )
    output = {
        "messages": [
            HumanMessage(content="Create a report"),
            ToolMessage(
                content=tool_result.model_dump_json(),
                tool_call_id="report-call",
            ),
        ]
    }

    answer = _apply_report(FinalAnswer(answer="Ready."), output)

    assert answer.report == artifact.reference()


def test_report_api_returns_identical_preview_and_download_bytes(
    test_settings,
) -> None:
    services = Services(settings=test_settings, agent=object())
    thread_id = services.conversations.create("test")
    spec = ReportSpec.model_validate(
        {"title": "API report", "blocks": [{"type": "narrative", "body": "Body"}]}
    )
    artifact = services.reports.save(
        thread_id=thread_id,
        source_id="test",
        spec=spec,
        html="<!doctype html><html><body>API report</body></html>",
        input_result_ids=[],
        input_analysis_ids=[],
    )
    client = TestClient(create_app(services))

    preview = client.get(f"/api/reports/{artifact.report_id}")
    download = client.get(f"/api/reports/{artifact.report_id}/download")

    assert preview.status_code == 200
    assert preview.json()["html"].encode("utf-8") == download.content
    assert download.headers["etag"] == f'"{artifact.html_sha256}"'
    assert "attachment" in download.headers["content-disposition"]


def test_streamlit_turn_previews_and_downloads_report() -> None:
    html = "<!doctype html><html><body><h1>Report</h1></body></html>"
    import hashlib

    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    app = AppTest.from_string(
        f'''
from data_analytics_agent.ui.components import render_turn

class Client:
    def get_report(self, _report_id):
        return {{
            "report_id": "report-1",
            "title": "Report",
            "version": 1,
            "html": {html!r},
            "html_sha256": {digest!r},
        }}

render_turn(
    Client(),
    {{
        "user_message": "Make a report",
        "answer": {{
            "answer": "The report is ready.",
            "report": {{
                "report_id": "report-1",
                "title": "Report",
                "version": 1,
                "html_sha256": {digest!r},
                "created_at": "2026-07-27T00:00:00Z",
            }},
        }},
        "activities": [],
    }},
    turn_key="turn-report",
    source_id="test",
)
'''
    ).run()

    assert not app.exception
    assert len(app.get("download_button")) == 1
