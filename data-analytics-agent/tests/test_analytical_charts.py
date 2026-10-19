"""Numerical and lifecycle checks for saved waterfall/funnel evidence."""

from decimal import Decimal
import re
from types import SimpleNamespace

import pytest

from data_analytics_agent.presentation_edits import (
    ChartPresentationEdit,
    edit_chart_presentation,
)
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChartDataPreparation, ChatTurn, FinalAnswer
from data_analytics_agent.stores import ResultStore
from data_analytics_agent.visualization.renderer import build_chart
from data_analytics_agent.visualization.schemas import ChartSpec
from data_analytics_agent.visualization.tools import create_chart_tool
from data_analytics_agent.visualization.validation import validate_chart_spec


def _waterfall_rows():
    return [
        {"stage": "Baseline", "amount": Decimal("100.10"), "measure": "absolute"},
        {"stage": "New customers", "amount": Decimal("30.20"), "measure": "relative"},
        {"stage": "Returns", "amount": Decimal("-20.10"), "measure": "relative"},
        {"stage": "Ending", "amount": Decimal("110.20"), "measure": "total"},
    ]


def _funnel_rows():
    # Deliberately unlike both the process order and a lexical stage ordering.
    return [
        {"stage": "Purchase", "amount": 20},
        {"stage": "Visit", "amount": 100},
        {"stage": "Sign up", "amount": 60},
    ]


def _spec(chart_type, result_id="saved", **updates):
    values = dict(
        result_id=result_id,
        chart_type=chart_type,
        title="Saved analytical chart",
        x="stage",
        y=["amount"],
    )
    values.update(
        waterfall_measure="measure" if chart_type == "waterfall" else None,
        stage_order=["Visit", "Sign up", "Purchase"]
        if chart_type == "funnel"
        else None,
    )
    return ChartSpec(**{**values, **updates})


def _save(rows, **kwargs):
    return ResultStore().save(
        thread_id="thread",
        source_id="source",
        columns=list(rows[0]),
        rows=rows,
        executed_sql="SELECT explicitly_prepared_evidence",
        **kwargs,
    )


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_waterfall_preserves_baseline_relative_and_computed_total(orientation):
    saved = _save(_waterfall_rows())
    spec = _spec("waterfall", saved.result_id, orientation=orientation)
    validate_chart_spec(spec, saved)
    rendered = build_chart(spec, saved.rows)
    trace = rendered.figure.data[0]
    assert trace.type == "waterfall"
    assert list(trace.measure) == ["absolute", "relative", "relative", "total"]
    values = list(trace.x if orientation == "horizontal" else trace.y)
    labels = list(trace.y if orientation == "horizontal" else trace.x)
    assert labels == ["Baseline", "New customers", "Returns", "Ending"]
    # Plotly computes its total; its final zero contributes nothing to the sum.
    assert values == [100.1, 30.2, -20.1, 0]
    assert sum(values) == pytest.approx(110.2)
    assert list(trace.customdata) == [100.1, 30.2, -20.1, 110.2]
    assert not rendered.warnings


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_funnel_uses_declared_process_order_without_sorting_counts(orientation):
    saved = _save(_funnel_rows())
    spec = _spec("funnel", saved.result_id, orientation=orientation)
    validate_chart_spec(spec, saved)
    figure = build_chart(spec, saved.rows).figure
    trace = figure.data[0]
    assert trace.type == "funnel"
    assert list(trace.y if orientation == "horizontal" else trace.x) == [
        "Visit",
        "Sign up",
        "Purchase",
    ]
    assert list(trace.x if orientation == "horizontal" else trace.y) == [100, 60, 20]
    assert trace.textinfo == "value"
    axis = figure.layout.yaxis if orientation == "horizontal" else figure.layout.xaxis
    assert list(axis.categoryarray) == ["Visit", "Sign up", "Purchase"]
    if orientation == "horizontal":
        assert axis.autorange == "reversed"


@pytest.mark.parametrize(
    "chart_type,updates",
    [
        ("waterfall", {"waterfall_measure": None}),
        ("funnel", {"stage_order": None}),
        ("funnel", {"stage_order": ["Visit", "Visit"]}),
        ("funnel", {"stage_order": ["Visit", " "]}),
        ("waterfall", {"color": "stage"}),
        ("funnel", {"sort_by": "amount"}),
        ("waterfall", {"sort_by": "amount", "category_limit": 2}),
        ("funnel", {"y": ["amount", "other"]}),
        ("bar", {"waterfall_measure": "measure"}),
        ("bar", {"stage_order": ["Visit", "Purchase"]}),
    ],
)
def test_analytical_chart_contract_rejects_implicit_or_conflicting_semantics(
    chart_type, updates
):
    with pytest.raises(ValueError):
        _spec(chart_type, **updates)


@pytest.mark.parametrize(
    "change,message",
    [
        ({"amount": Decimal("111.20")}, "ending total must equal"),
        ({"measure": "relative"}, "absolute baseline"),
        ({"stage": "Baseline"}, "categories must be unique"),
        ({"amount": None}, "finite numeric"),
        ({"amount": float("inf")}, "finite numeric"),
    ],
)
def test_waterfall_rejects_unreconciled_or_incomplete_values(change, message):
    rows = _waterfall_rows()
    if isinstance(change.get("amount"), float):
        rows = [{**row, "amount": float(row["amount"])} for row in rows]
    rows[-1].update(change)
    saved = _save(rows)
    with pytest.raises(ValueError, match=message):
        validate_chart_spec(_spec("waterfall", saved.result_id), saved)


@pytest.mark.parametrize(
    "rows,message",
    [
        (
            [
                {"stage": "Visit", "amount": 100},
                {"stage": "Sign up", "amount": 110},
                {"stage": "Purchase", "amount": 20},
            ],
            "must not increase",
        ),
        (
            [
                {"stage": "Visit", "amount": 100},
                {"stage": "Sign up", "amount": -1},
                {"stage": "Purchase", "amount": 0},
            ],
            "nonnegative integers",
        ),
        (
            [
                {"stage": "Visit", "amount": 100},
                {"stage": "Sign up", "amount": 1.5},
                {"stage": "Purchase", "amount": 0},
            ],
            "nonnegative integers",
        ),
        (
            [{"stage": "Visit", "amount": 100}, {"stage": "Purchase", "amount": 20}],
            "cover every",
        ),
        (
            [
                {"stage": "Visit", "amount": 100},
                {"stage": "Sign up", "amount": None},
                {"stage": "Purchase", "amount": 0},
            ],
            "finite numeric",
        ),
    ],
)
def test_funnel_rejects_invalid_saved_stage_populations(rows, message):
    saved = _save(rows)
    with pytest.raises(ValueError, match=message):
        validate_chart_spec(_spec("funnel", saved.result_id), saved)


@pytest.mark.parametrize(
    "chart_type,rows", [("waterfall", _waterfall_rows()), ("funnel", _funnel_rows())]
)
def test_analytical_charts_reject_truncated_or_sampled_inputs(chart_type, rows):
    saved = _save(rows, truncated=True)
    spec = _spec(chart_type, saved.result_id)
    with pytest.raises(ValueError, match="complete unsampled"):
        validate_chart_spec(spec, saved)
    sampled = saved.model_copy(
        update={
            "truncated": False,
            "chart_preparation": ChartDataPreparation(
                selected_columns=saved.columns,
                input_row_count=100,
                output_row_count=len(rows),
                sampling="reservoir",
                seed=0,
            ),
        }
    )
    with pytest.raises(ValueError, match="complete unsampled"):
        validate_chart_spec(spec, sampled)


@pytest.mark.parametrize(
    "chart_type,rows", [("waterfall", _waterfall_rows()), ("funnel", _funnel_rows())]
)
def test_analytical_charts_use_existing_saved_report_and_presentation_revisions(
    workspace, chart_type, rows
):
    w = workspace
    rows = [{**row, "unused": "not charted"} for row in rows]
    saved = w.results.save(
        thread_id=w.thread,
        source_id="test",
        columns=list(rows[0]),
        rows=rows,
        executed_sql="SELECT final_evidence",
    )
    tool = create_chart_tool(w.results, w.runs, source_id="test")
    output = tool.func(
        spec=_spec(chart_type, saved.result_id), runtime=w.runtime("chart")
    )
    assert output["ok"], output
    assert (
        tool.func(spec=_spec(chart_type, saved.result_id), runtime=w.runtime("chart"))
        == output
    )
    chart = ChartSpec.model_validate(output["chart"])
    presented = w.results.get(chart.result_id, w.thread)
    assert presented.parent_result_ids == [saved.result_id]
    assert presented.row_count == saved.row_count
    if chart_type == "waterfall":
        assert "measure" in presented.columns
    report = generate_report(
        ReportSpec(
            title="Checked evidence",
            blocks=[
                {"type": "chart", "chart_id": chart.chart_id, "summary": chart.title}
            ],
        ),
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
    )
    assert chart_type in report.html
    assert re.search(r"<script\b[^>]*\bsrc=[\"\']https?://", report.html) is None
    answer = FinalAnswer(
        answer="Saved evidence", charts=[chart], report=report.reference()
    )
    w.runs.publish(w.run, answer)
    w.runs.attach_report(w.run, report.reference())
    w.runs.complete(w.run, answer)
    w.conversations.complete_run(
        w.thread,
        w.run,
        ChatTurn(run_id=w.run, user_message="Chart saved evidence", answer=answer),
    )
    services = SimpleNamespace(**vars(w))
    revised = edit_chart_presentation(
        services,
        w.run,
        ChartPresentationEdit(
            report_id=report.report_id,
            chart_id=chart.chart_id,
            title="Revised display title",
            palette="teal",
        ),
    )
    updated = revised.charts[0]
    assert updated.previous_chart_id == chart.chart_id
    assert updated.result_id == chart.result_id
    assert updated.waterfall_measure == chart.waterfall_measure
    assert updated.stage_order == chart.stage_order
    assert revised.report.previous_report_id == report.report_id
    assert w.reports.get(report.report_id, w.thread).html == report.html


def test_zero_funnel_counts_do_not_invent_percentage_denominators():
    rows = [{**row, "amount": 0} for row in _funnel_rows()]
    saved = _save(rows)
    spec = _spec("funnel", saved.result_id)
    validate_chart_spec(spec, saved)
    trace = build_chart(spec, saved.rows).figure.data[0]
    assert list(trace.y) == [0, 0, 0]
    assert trace.textinfo == "value"
