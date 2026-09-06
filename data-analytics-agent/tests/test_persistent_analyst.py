from decimal import Decimal
import pyarrow as pa
from types import SimpleNamespace
import sqlite3
import pytest
from fastapi.testclient import TestClient
from data_analytics_agent.persistence import LocalStorage
from data_analytics_agent.stores import (
    ResultStore,
    RunStore,
    ConversationStore,
    DataAnalysisStore,
    ReportStore,
)
from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.agents.text_to_sql.tools import (
    create_query_saved_results_tool,
    create_inspect_conversation_result_tool,
    create_execute_sql_tool,
)
from data_analytics_agent.visualization.tools import create_chart_tool
from data_analytics_agent.visualization.schemas import ChartSpec
from data_analytics_agent.reporting.tools import create_create_report_tool
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.schemas import (
    CoordinatorResponse,
    RunStatus,
    ApprovalRequest,
    Decision,
)
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.backends.sqlite import SQLiteBackend
from data_analytics_agent.approvals import decisions_to_command


@pytest.fixture
def workspace(tmp_path):
    storage = LocalStorage(tmp_path / "workspace")
    results, runs, conversations, analyses, reports = (
        ResultStore(storage),
        RunStore(storage),
        ConversationStore(storage),
        DataAnalysisStore(storage),
        ReportStore(storage),
    )
    thread = conversations.create("test")
    run = runs.create(thread, "test", "Analyze sales")
    conversations.begin_run(thread, run)

    def runtime(call):
        return SimpleNamespace(
            state={
                "thread_id": thread,
                "run_id": run,
                "source_id": "test",
                "question": "Analyze sales",
            },
            tool_call_id=call,
        )

    return SimpleNamespace(
        storage=storage,
        results=results,
        runs=runs,
        conversations=conversations,
        analyses=analyses,
        reports=reports,
        thread=thread,
        run=run,
        runtime=runtime,
    )


def save(w, rows, **kwargs):
    return w.results.save(
        columns=list(rows[0]), rows=rows, thread_id=w.thread, source_id="test", **kwargs
    )


def test_large_typed_extraction_python_pagination_download_and_restart(
    workspace, test_settings, tmp_path
):
    w = workspace
    path = tmp_path / "large.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE facts (n INTEGER, amount REAL)")
        db.executemany(
            "INSERT INTO facts VALUES (?, ?)", ((i, i / 100) for i in range(100000))
        )
    from dataclasses import replace
    from data_analytics_agent.data_sources import ExecutionLimits

    source = replace(
        test_settings.load_catalog().get("test"),
        limits=ExecutionLimits(30, 1000000, 10),
    )
    tool = create_execute_sql_tool(source, SQLiteBackend(path), w.results, w.runs)
    output = tool.func(
        query="SELECT * FROM facts",
        purpose="Complete population",
        runtime=w.runtime("source"),
    )
    result = w.results.get_unscoped(output["result_id"])
    assert (
        result.row_count == 100000
        and not result.truncated
        and len(result.preview) == 10
    )
    assert (
        tool.func(
            query="SELECT * FROM facts",
            purpose="Complete population",
            runtime=w.runtime("source"),
        )
        == output
    )
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 1
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    step = execute.func(
        inputs={"facts": result.result_id},
        code="analysis_outputs={'count':len(datasets['facts'])}; output_datasets={'copy':datasets['facts'].copy()}",
        runtime=w.runtime("python"),
    )
    assert step["ok"], step
    derived = w.results.get_unscoped(step["output_datasets"]["copy"])
    assert derived.row_count == 100000 and derived.parent_result_ids == [
        result.result_id
    ]
    assert (
        w.results.page_unscoped(derived.result_id, offset=99990, limit=10).rows[-1]["n"]
        == 99999
    )
    services = Services(
        settings=test_settings,
        storage=w.storage,
        results=w.results,
        runs=w.runs,
        conversations=w.conversations,
        analyses=w.analyses,
        reports=w.reports,
    )
    with TestClient(create_app(services)) as client:
        export = client.get(f"/api/results/{derived.result_id}/download?format=csv")
        assert export.status_code == 200 and len(export.text.splitlines()) == 100001
        parquet = client.get(
            f"/api/results/{derived.result_id}/download?format=parquet"
        )
        assert parquet.content[:4] == b"PAR1"
    reopened = ResultStore(LocalStorage(w.storage.root))
    assert reopened.get_unscoped(derived.result_id).row_count == 100000


def test_iterative_python_repairs_reuses_multiple_inputs_and_saves_all_steps(workspace):
    w = workspace
    r = save(w, [{"x": i, "value": Decimal("12.35")} for i in range(40)])
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    a = execute.func(
        inputs={"source": r.result_id},
        code="import pandas as pd\nf=datasets['source'].copy()\nf['numeric']=pd.to_numeric(f['value'])\nanalysis_outputs={'mean':f.numeric.mean()}\noutput_datasets={'features':f}",
        runtime=w.runtime("a"),
    )
    bad = execute.func(
        inputs={"features": a["output_datasets"]["features"]},
        code='raise ValueError("Repair this step")',
        runtime=w.runtime("bad"),
    )
    assert not bad["ok"] and "Repair this step" in bad["error"]
    b = execute.func(
        inputs={"features": a["output_datasets"]["features"], "original": r.result_id},
        code="analysis_outputs={'count':len(datasets['features'])+len(datasets['original'])}",
        runtime=w.runtime("b"),
    )
    assert b["ok"] and b["outputs"][0]["value"] == 80
    rejected = finish.func(
        outcome="analysis_completed",
        answer="Ready",
        input_result_ids=[r.result_id],
        execution_ids=["mistyped-execution-id"],
        runtime=w.runtime("typo"),
    )
    assert not rejected["ok"]
    assert a["execution_id"] in [
        e["execution_id"] for e in rejected["available_executions"]
    ]
    assert not finish.return_direct  # Errors must return to the specialist for repair.
    completed = finish.func(
        outcome="analysis_completed",
        answer="The mean is 12.35.",
        input_result_ids=[r.result_id],
        execution_ids=[a["execution_id"], bad["execution_id"], b["execution_id"]],
        method="Exploration",
        runtime=w.runtime("finish"),
    )
    assert len(completed["executions"]) == 3
    persisted = DataAnalysisStore(LocalStorage(w.storage.root)).get(
        completed["analysis_id"], w.thread, source_id="test"
    )
    assert persisted.analysis.executions[0].executed_python == a["executed_python"]
    assert w.results.get_unscoped(r.result_id).rows[0]["value"] == Decimal("12.35")


def test_saved_sql_profiles_and_incomplete_population(workspace):
    w = workspace
    r = save(
        w,
        [
            {"category": "A", "amount": 1.0},
            {"category": "A", "amount": None},
            {"category": "B", "amount": 3.0},
        ],
    )
    inspect = create_inspect_conversation_result_tool(w.results, source_id="test")
    profile = inspect.func(
        result_id=r.result_id,
        columns=["category", "amount"],
        filters={"category": "A"},
        sample="random",
        runtime=w.runtime("inspect"),
    )
    assert profile["row_count"] == 2 and profile["profile"]["amount"]["null_count"] == 1
    query = create_query_saved_results_tool(w.results, w.runs, source_id="test")
    transformed = query.func(
        query="SELECT category, SUM(amount) AS total FROM sales GROUP BY category",
        bindings={"sales": r.result_id},
        purpose="Category totals",
        runtime=w.runtime("reshape"),
    )
    assert transformed["row_count"] == 2
    capped = save(w, [{"x": i} for i in range(5)], max_rows=3)
    execute, _ = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    refused = execute.func(
        inputs={"incomplete": capped.result_id},
        code='analysis_outputs={"count":3}',
        runtime=w.runtime("capped"),
    )
    assert refused["needs_sql_reshape"] and not w.runs.get_python_execution(w.run)


def test_shared_chart_versions_uncertainty_and_report_metric_binding(workspace):
    w = workspace
    r = save(
        w,
        [
            {
                "month": f"2026-0{i}",
                "estimate": Decimal(i),
                "lower": Decimal(i) - Decimal(".2"),
                "upper": Decimal(i) + Decimal(".2"),
            }
            for i in range(1, 5)
        ],
    )
    chart = create_chart_tool(w.results, w.runs, source_id="test")
    spec = ChartSpec(
        result_id=r.result_id,
        chart_type="line",
        title="Forecast",
        x="month",
        y=["estimate"],
        lower_bound="lower",
        upper_bound="upper",
    )
    created = chart.func(spec=spec, runtime=w.runtime("chart"))
    assert created["ok"], created
    revised = chart.func(
        spec=spec.model_copy(
            update={
                "title": "Updated forecast",
                "previous_chart_id": created["chart_id"],
            }
        ),
        runtime=w.runtime("revision"),
    )
    assert (
        revised["chart"]["version"] == 2 and revised["chart_id"] != created["chart_id"]
    )
    publish, _ = create_presentation_tools(
        w.results, w.analyses, w.runs, w.conversations, source_id="test"
    )
    publish.func(
        findings=CoordinatorResponse(
            answer="Forecast with uncertainty.",
            primary_result_id=r.result_id,
            supporting_result_ids=[r.result_id],
            chart_ids=[revised["chart_id"]],
        ),
        runtime=w.runtime("publish"),
    )
    assert w.runs.get(w.run).phase == "findings_ready"
    report = create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    )
    spec = ReportSpec(
        title="Forecast",
        blocks=[
            {
                "type": "metrics",
                "metrics": [
                    {
                        "label": "First estimate",
                        "result_id": r.result_id,
                        "column": "estimate",
                        "number_format": ".2f",
                    }
                ],
            },
        ],
    )
    result = report.func(
        report_json=spec.model_dump_json(), runtime=w.runtime("report")
    )
    assert result["ok"], result
    artifact = ReportStore(LocalStorage(w.storage.root)).get(
        result["report"]["report_id"], w.thread, source_id="test"
    )
    assert "1.00" in artifact.html and "Updated forecast" in artifact.html
    assert len(w.runs.storage.load("charts", dict)) == 2


def test_restart_preserves_pending_reviews_and_pauses_computation(workspace):
    w = workspace
    w.runs.start_active(w.run)
    resumed = RunStore(LocalStorage(w.storage.root))
    resumed.recover()
    assert resumed.get(w.run).status == RunStatus.PAUSED
    approval = ApprovalRequest(
        interrupt_id="review",
        action_name="execute_analysis_python",
        query="print(1)",
        review_type="python",
        arguments={"code": "print(1)", "inputs": {"a": "one", "b": "two"}},
        allowed_decisions=["edit"],
    )
    w.runs.require_approval(w.run, approval)
    reopened = RunStore(LocalStorage(w.storage.root))
    reopened.recover()
    assert reopened.get(w.run).status == RunStatus.APPROVAL_REQUIRED
    command = decisions_to_command(
        reopened.get(w.run).approval,
        [Decision(action="edit", edited_python="print(2)\n")],
    )
    args = command.resume["review"]["decisions"][0]["edited_action"]["args"]
    assert args == {"inputs": {"a": "one", "b": "two"}, "code": "print(2)\n"}


def test_null_first_batches_and_decimal_scales_preserve_types(workspace):
    w = workspace
    batches = [
        pa.record_batch({"value": [None, None]}),
        pa.record_batch({"value": [Decimal("1.2"), Decimal("2.345")]}),
    ]
    result = w.results.save_batches(iter(batches), thread_id=w.thread, source_id="test")
    assert result.rows == [
        {"value": None},
        {"value": None},
        {"value": Decimal("1.200")},
        {"value": Decimal("2.345")},
    ]
    assert result.profile.columns[0].null_count == 2
    assert result.profile.columns[0].physical_kind == "number"


def test_restart_does_not_charge_offline_time_to_analysis_budget(workspace):
    from tests.test_stores import FakeClock

    w = workspace
    clock = FakeClock()
    runs = RunStore(w.storage, clock=clock)
    run = runs.create(w.thread, "test", "Budget")
    runs.start_active(run)
    clock.advance(2)
    runs.set_phase(run, "analyzing")
    clock.advance(10000)
    reopened = RunStore(LocalStorage(w.storage.root), clock=clock)
    reopened.recover()
    assert reopened.get(run).run_diagnostics.active_ms == 2000
    reopened.start_active(run)
    clock.advance(1)
    assert reopened.get(run).run_diagnostics.active_ms == 3000


def test_chart_sampling_is_display_only_and_payload_is_bounded(workspace):
    w = workspace
    r = save(w, [{"x": i, "y": float(i), "unused": "details"} for i in range(10001)])
    create = create_chart_tool(w.results, w.runs, source_id="test")
    response = create.func(
        spec=ChartSpec(
            result_id=r.result_id, chart_type="line", title="Trend", x="x", y=["y"]
        ),
        runtime=w.runtime("sample-chart"),
    )
    assert response["ok"], response
    chart = response["chart"]
    shown = w.results.get_unscoped(chart["result_id"])
    assert (
        shown.row_count <= 5000
        and shown.columns == ["x", "y"]
        and shown.kind == "presentation"
    )
    assert (
        shown.parent_result_ids == [r.result_id] and "Downsampled" in chart["notes"][0]
    )
    execute, _ = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    rejected = execute.func(
        inputs={"data": shown.result_id},
        code='analysis_outputs={"n":1}',
        runtime=w.runtime("reject-sample"),
    )
    assert not rejected["ok"] and "parent" in rejected["error"]


def test_inspection_invalid_column_is_repairable(workspace):
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_inspect_conversation_result_tool,
    )

    r = save(workspace, [{"revenue": 10}])
    inspect = create_inspect_conversation_result_tool(
        workspace.results, source_id="test"
    )
    bad = inspect.func(
        result_id=r.result_id, columns=["forecast"], runtime=workspace.runtime("wrong")
    )
    assert not bad["ok"] and bad["available_columns"] == ["revenue"]
    good = inspect.func(
        result_id=r.result_id,
        columns=bad["available_columns"],
        runtime=workspace.runtime("fixed"),
    )
    assert good["sample_rows"] == [{"revenue": 10}]
