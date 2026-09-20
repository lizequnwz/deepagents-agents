from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.utils.function_calling import convert_to_openai_tool
import pytest

from data_analytics_agent.reporting.renderer import render_report
from data_analytics_agent.reporting.schemas import (
    ReportBrief,
    ReportSpec,
)
from data_analytics_agent.reporting.tools import create_create_report_tool
from data_analytics_agent.stores import (
    ReportStore,
    ResultStore,
    RunStore,
    DataAnalysisStore,
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
        DataAnalysisStore(),
        RunStore(),
        ReportStore(),
        source_id="source-1",
    )
    parameters = convert_to_openai_tool(tool, strict=True)["function"]["parameters"]

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


def test_report_rejects_conflicting_metric_labels_for_one_saved_cell(workspace):
    from data_analytics_agent.presentation import resolve_answer
    from data_analytics_agent.schemas import CoordinatorResponse
    from tests.test_persistent_analyst import save

    w = workspace
    result = save(
        w, [{"region": "East", "amount": 40}, {"region": "West", "amount": 60}]
    )
    w.runs.publish(
        w.run,
        resolve_answer(
            CoordinatorResponse(
                answer="Total 100: East 40, West 60.",
                primary_result_id=result.result_id,
            ),
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=w.runs,
        ),
    )
    tool = create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    )

    def metric(label, row_index):
        return {
            "label": label,
            "result_id": result.result_id,
            "column": "amount",
            "row_index": row_index,
        }

    # Conflicting bindings are rejected across report sections as well as within one block.
    spec = ReportSpec(
        title="Sales",
        blocks=[
            {"type": "metrics", "metrics": [metric("Overall sales", 0)]},
            {
                "type": "metrics",
                "metrics": [metric("East sales", 0), metric("West sales", 1)],
            },
        ],
    )
    failed = tool.func(report_json=spec.model_dump_json(), runtime=w.runtime("report"))
    assert not failed["ok"] and failed["retryable"]
    assert "group row is not an overall total" in failed["error"]
    assert not w.runs.report_reference(w.run)
    assert not w.storage.load("reports", dict)
    # Correct the presentation without changing findings or querying data again.
    repaired_spec = spec.model_dump()
    repaired_spec["blocks"][0] = {"type": "narrative", "body": "Total sales were 100."}
    spec = ReportSpec.model_validate(repaired_spec)
    repaired = tool.func(
        report_json=spec.model_dump_json(), runtime=w.runtime("report")
    )
    assert repaired["ok"], repaired
    html = w.reports.get_unscoped(repaired["report"]["report_id"]).html
    assert "Overall sales" not in html and "Total sales were 100." in html
    assert "East sales" in html and "40.00" in html and "60.00" in html
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 1
