from decimal import Decimal
import pytest
from data_analytics_agent.reporting.comparisons import (
    PeriodComparison,
    resolve_comparison,
)
from data_analytics_agent.reporting.schemas import ReportMetric, ReportMetricsBlock
from data_analytics_agent.reporting.renderer import _metrics


def evidence(workspace, rows=None, **kw):
    return workspace.results.save(
        thread_id=workspace.thread,
        source_id="test",
        columns=["year", "region", "revenue"],
        rows=rows
        or [
            {"year": 2024, "region": "all", "revenue": 100},
            {"year": 2025, "region": "all", "revenue": 125},
        ],
        **kw,
    )


def metric(result):
    return ReportMetric(
        label="Revenue",
        result_id=result.result_id,
        column="revenue",
        row_index=1,
        comparison=PeriodComparison(
            metric_ref="invoice_revenue",
            population="All billing countries",
            grain=["year", "region"],
            period_column="year",
            current_period="2025",
            baseline_period="2024",
            baseline_row_index=0,
        ),
    )


def test_comparison_uses_saved_values_and_discloses_calculation(workspace):
    result = evidence(workspace)
    spec = metric(result)
    values = resolve_comparison(spec, result)
    assert values["delta"] == Decimal(25)
    assert values["percentage_change"] == Decimal(25)
    html = _metrics(ReportMetricsBlock(metrics=[spec]), {result.result_id: result})
    assert "How calculated?" in html and "+25.00%" in html
    assert "completeness is unknown" in html and result.result_id in html


@pytest.mark.parametrize(
    "defect", ["duplicate", "scope", "period", "truncated", "denominator", "missing"]
)
def test_rejects_incompatible_comparisons(workspace, defect):
    rows = [
        {"year": 2024, "region": "all", "revenue": 100},
        {"year": 2025, "region": "all", "revenue": 125},
    ]
    if defect == "duplicate":
        rows.append(rows[0].copy())
    if defect == "scope":
        rows[1]["region"] = "subset"
    if defect == "missing":
        rows[0]["revenue"] = None
    result = evidence(workspace, rows, truncated=defect == "truncated")
    spec = metric(result)
    if defect == "period":
        spec.comparison.current_period = "2026"
    if defect == "denominator":
        spec.comparison.denominator_column = "missing_denominator"
    with pytest.raises(ValueError):
        resolve_comparison(spec, result)


def test_zero_baseline_and_false_completeness(workspace):
    result = evidence(
        workspace,
        [
            {"year": 2024, "region": "all", "revenue": 0},
            {"year": 2025, "region": "all", "revenue": 5},
        ],
    )
    spec = metric(result)
    assert resolve_comparison(spec, result)["percentage_change"] is None
    with pytest.raises(ValueError):
        PeriodComparison.model_validate(
            {**spec.comparison.model_dump(), "completeness": "complete"}
        )


def test_unit_and_rate_evidence_must_reconcile(workspace):
    rows = [
        {
            "year": 2024,
            "region": "all",
            "revenue": 25,
            "n": 1,
            "d": 4,
            "unit": "percent",
        },
        {
            "year": 2025,
            "region": "all",
            "revenue": 50,
            "n": 2,
            "d": 4,
            "unit": "percent",
        },
    ]

    def stored():
        return workspace.results.save(
            thread_id=workspace.thread,
            source_id="test",
            columns=list(rows[0]),
            rows=rows,
        )

    result = stored()
    spec = metric(result)
    spec.comparison.unit_column = "unit"
    spec.comparison.numerator_column = "n"
    spec.comparison.denominator_column = "d"
    spec.comparison.rate_scale = 100
    assert resolve_comparison(spec, result)["denominators"] == [Decimal(4), Decimal(4)]
    rows[1]["unit"] = "USD"
    with pytest.raises(ValueError, match="units"):
        resolve_comparison(spec, stored())
    rows[1]["unit"] = "percent"
    rows[1]["d"] = 5
    with pytest.raises(ValueError, match="denominator"):
        resolve_comparison(spec, stored())


def test_canonical_metric_binding_rejects_mislabelled_measure(workspace):
    result = evidence(workspace, metric_columns={"revenue": "total_revenue"})
    spec = metric(result)
    with pytest.raises(ValueError, match="metric_ref"):
        resolve_comparison(spec, result)
    spec.comparison.metric_ref = "total_revenue"
    assert resolve_comparison(spec, result)["metric_binding_verified"]


def test_report_tool_publishes_comparison_from_evidence(workspace):
    import json
    from pathlib import Path
    from data_analytics_agent.reporting.tools import create_create_report_tool
    from data_analytics_agent.schemas import FinalAnswer, ResultReference
    from data_analytics_agent.semantic import load_semantic_catalog

    w = workspace
    result = evidence(w, metric_columns={"revenue": "total_revenue"})
    card = metric(result)
    card.comparison.metric_ref = "total_revenue"
    w.runs.publish(
        w.run,
        FinalAnswer(
            answer="Revenue grew.",
            results=[
                ResultReference(
                    result_id=result.result_id,
                    executed_sql="",
                    originating_question="compare",
                    short_label="Annual totals",
                )
            ],
        ),
    )
    tool = create_create_report_tool(
        w.results,
        w.analyses,
        w.runs,
        w.reports,
        source_id="test",
        semantic_catalog=load_semantic_catalog(
            Path("semantic/chinook.osi.yaml"), dialect="sqlite"
        ).catalog,
    )
    response = tool.func(
        report_json=json.dumps(
            {
                "title": "Comparison",
                "blocks": [{"type": "metrics", "metrics": [card.model_dump()]}],
            }
        ),
        runtime=w.runtime("comparison"),
    )
    assert response["ok"], response
    report = w.reports.get(response["report"]["report_id"], w.thread)
    assert "Verified canonical output column" in report.html
    assert "How calculated?" in report.html and "+25.00%" in report.html
    assert report.input_result_ids == [result.result_id]
