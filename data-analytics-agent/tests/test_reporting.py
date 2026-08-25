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
    ReportToolFailure,
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


def test_create_report_exports_a_simple_openai_schema() -> None:
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

    assert parameters["required"] == ["report_json"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["report_json"]["type"] == "string"
    assert "runtime" in tool.args_schema.model_fields
    assert "runtime" not in parameters["properties"]

    def assert_no_schema_composition(value) -> None:
        if isinstance(value, dict):
            assert not ({"oneOf", "anyOf", "allOf", "$ref", "$defs"} & value.keys())
            for child in value.values():
                assert_no_schema_composition(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_schema_composition(child)

    assert_no_schema_composition(parameters)


def test_create_report_returns_compact_repair_guidance() -> None:
    tool = create_create_report_tool(
        ResultStore(),
        StatisticalAnalysisStore(),
        RunStore(),
        ReportStore(),
        source_id="source-1",
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        }
    )

    malformed = ReportToolFailure.model_validate_json(
        tool.func('{"title": "Broken",', runtime)
    )
    invalid = ReportToolFailure.model_validate_json(
        tool.func(
            '{"title":"Broken","blocks":[{"type":"chart"}]}',
            runtime,
        )
    )

    assert malformed.code == "invalid_report_json"
    assert malformed.issues[0].path == "report_json"
    assert invalid.code == "invalid_report_spec"
    assert any(issue.path.startswith("blocks.0") for issue in invalid.issues)


@pytest.mark.parametrize(
    "payload",
    [
        '```json\n{"title":"Fenced","blocks":[]}\n```',
        '"{\\"title\\":\\"Double encoded\\",\\"blocks\\":[]}"',
        '{"spec":{"title":"Wrapped","blocks":[]}}',
    ],
)
def test_create_report_rejects_obsolete_transport_wrappers(
    payload: str,
) -> None:
    tool = create_create_report_tool(
        ResultStore(),
        StatisticalAnalysisStore(),
        RunStore(),
        ReportStore(),
        source_id="source-1",
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
        }
    )
    result = ReportToolFailure.model_validate_json(tool.func(payload, runtime))

    assert result.code in {"invalid_report_json", "invalid_report_spec"}


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
    assert "SQL queries" in html
    assert saved.executed_sql in html
    assert "Data provenance" not in html
    assert saved.result_id not in html
    assert "max-width: 1360px" in html
    assert "padding: clamp(1.75rem, 4vw, 3.5rem)" in html
    assert '<body data-theme="light">' in html
    assert "--primary: #368727" in html
    assert "'Fidelity Slab', 'Roboto Slab'" in html
    assert "--background: #F9F7F5" in html


def test_renderer_deduplicates_and_escapes_reproducible_sql() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT '<unsafe>' AS label",
        columns=["label"],
        rows=[{"label": "<unsafe>"}],
        truncated=True,
        elapsed_ms=1.0,
        originating_question="Inspect a label",
    )
    spec = ReportSpec.model_validate(
        {
            "title": "Reproducible report",
            "blocks": [
                {
                    "type": "table",
                    "result_id": saved.result_id,
                    "title": "Labels",
                },
                {
                    "type": "table",
                    "result_id": saved.result_id,
                    "title": "Labels again",
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

    assert html.count('<article class="sql-query">') == 1
    assert "SELECT &#x27;&lt;unsafe&gt;&#x27; AS label" in html
    assert "truncated at the configured limit" in html
    assert saved.result_id not in html


def test_metric_grid_caps_columns_at_responsive_breakpoints() -> None:
    spec = ReportSpec.model_validate(
        {
            "title": "Responsive metrics",
            "blocks": [
                {
                    "type": "metrics",
                    "columns": 6,
                    "metrics": [
                        {"label": f"Metric {index}", "value": str(index)}
                        for index in range(1, 7)
                    ],
                }
            ],
        }
    )

    html = render_report(
        spec,
        results={},
        analyses={},
        generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert "--metric-columns:6" in html
    assert "--metric-tablet-columns:3" in html
    assert "--metric-mobile-columns:2" in html
    assert "SQL queries" not in html


def test_report_chart_uses_coherent_default_palette() -> None:
    results = ResultStore()
    saved = _saved_result(results)
    spec = ReportSpec.model_validate(
        {
            "title": "Chart report",
            "blocks": [
                {
                    "type": "chart",
                    "summary": "Category A has the larger amount.",
                    "show_data_table": False,
                    "chart": {
                        "result_id": saved.result_id,
                        "chart_type": "bar",
                        "title": "Amount by category",
                        "x": "category",
                        "y": ["amount"],
                    },
                }
            ],
        }
    )

    html = render_report(
        spec,
        results={saved.result_id: saved},
        analyses={},
        generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert "#368727" in html
    assert html.count("Amount by category") == 1
    assert "Plotly.relayout" in html
    assert "hoverlabel.bgcolor" in html


def test_report_dark_theme_uses_fidelity_dark_tokens() -> None:
    spec = ReportSpec.model_validate(
        {
            "title": "Dark report",
            "theme": {"color_mode": "dark"},
            "blocks": [{"type": "narrative", "body": "Finding"}],
        }
    )

    html = render_report(
        spec,
        results={},
        analyses={},
        generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert '<body data-theme="dark">' in html
    assert "--surface: #292928" in html
    assert "--background: #141414" in html
    assert "--primary: #65C754" in html


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
    first = ReportToolResult.model_validate_json(
        tool.func(first_spec.model_dump_json(), runtime)
    )
    revised_spec = first_spec.model_copy(
        update={
            "title": "Revised report",
            "previous_report_id": first.report.report_id,
        }
    )
    revised = ReportToolResult.model_validate_json(
        tool.func(revised_spec.model_dump_json(), runtime)
    )

    assert first.report.version == 1
    assert revised.report.version == 2
    assert revised.report.previous_report_id == first.report.report_id
    assert reports.get(
        revised.report.report_id,
        "thread-1",
        source_id="source-1",
    ).renderer_version == "1.3"

    wrong_thread = SimpleNamespace(
        state={
            "thread_id": "thread-2",
            "run_id": "run-2",
            "source_id": "source-1",
        }
    )
    wrong_scope = ReportToolFailure.model_validate_json(
        tool.func(first_spec.model_dump_json(), wrong_thread)
    )
    assert wrong_scope.code == "artifact_not_found"


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
            warnings=["Small sample.", "Small sample.", "Check independence."],
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

    result = ReportToolResult.model_validate_json(
        tool.func(spec.model_dump_json(), runtime)
    )
    artifact = reports.get(
        result.report.report_id,
        "thread-1",
        source_id="source-1",
    )
    assert result.report.title == "Statistical report"
    assert stored.analysis.analysis_id == stored.analysis_id
    assert "data:image/png;base64,aW1hZ2U=" in artifact.html
    assert "8.5" in artifact.html
    assert "Analysis notes and limitations (2)" in artifact.html
    assert artifact.html.count("Small sample.") == 1


def test_authoritative_report_tool_result_preserves_ordinary_chart() -> None:
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

    answer = _apply_report(
        FinalAnswer.model_validate(
            {
                "answer": "Ready.",
                "primary_result_id": "result-1",
                "results": [
                    {
                        "result_id": "result-1",
                        "executed_sql": "SELECT category, amount FROM metrics",
                        "originating_question": "Compare categories",
                        "short_label": "Category comparison",
                    }
                ],
                "chart": {
                    "result_id": "result-1",
                    "chart_type": "bar",
                    "title": "Redundant top-level chart",
                    "x": "category",
                    "y": ["amount"],
                },
            }
        ),
        output,
    )

    assert answer.report == artifact.reference()
    assert answer.chart is not None
    assert answer.chart.result_id == "result-1"


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
    view = client.get(f"/api/reports/{artifact.report_id}/view")
    download = client.get(f"/api/reports/{artifact.report_id}/download")

    assert preview.status_code == 200
    assert view.status_code == 200
    assert view.content == download.content
    assert preview.json()["html"].encode("utf-8") == download.content
    assert view.headers["etag"] == f'"{artifact.html_sha256}"'
    assert "inline" in view.headers["content-disposition"]
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

    def report_view_url(self, report_id):
        return f"http://api.test/api/reports/{{report_id}}/view"

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
    assert len(app.get("link_button")) == 1
    assert app.get("link_button")[0].label == "Open full report"
    assert [panel.label for panel in app.get("status")] == ["Report preview"]
