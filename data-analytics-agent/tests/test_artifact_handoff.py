"""Artifact identity belongs to saved evidence, not model transcription."""

import pytest
from langchain_core.tools import ToolException
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.agents.text_to_sql.tools import (
    create_query_saved_results_tool,
)
from data_analytics_agent.reporting.tools import (
    create_inspect_conversation_analysis_tool,
)


def test_investigation_has_no_artifact_arguments(workspace):
    w = workspace
    _, tool = create_presentation_tools(
        w.results, w.analyses, w.runs, w.conversations, source_id="test"
    )
    assert "artifact_ids" not in tool.args
    assert tool.func(
        objective="Continue saved work",
        completed_steps=["Analysis done"],
        findings=["Ready to report"],
        unresolved_questions=[],
        runtime=w.runtime("notes"),
    ) == {"ok": True}
    assert "artifact_ids" not in w.conversations.investigation(w.thread)


def test_unknown_saved_sql_reference_is_recoverable(workspace):
    w = workspace
    tool = create_query_saved_results_tool(w.results, w.runs, source_id="test")
    with pytest.raises(ToolException, match="list_conversation_results"):
        tool.func(
            query="SELECT amount FROM source",
            bindings={"source": "unknown"},
            purpose="Inspect",
            runtime=w.runtime("bad"),
        )
    assert tool.handle_tool_error


def test_unknown_analysis_reference_is_recoverable(workspace):
    w = workspace
    tool = create_inspect_conversation_analysis_tool(w.analyses, source_id="test")
    result = tool.func(analysis_id="unknown", runtime=w.runtime("bad"))
    assert result["ok"] is False and "list_conversation_analyses" in result["error"]


def test_sql_receipts_isolate_replayed_call_ids_and_support_reuse(
    workspace, test_settings
):
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_execute_sql_tool,
        create_inspect_conversation_result_tool,
    )
    from data_analytics_agent.backends.sqlite import SQLiteBackend
    from data_analytics_agent.stores import RunStore
    from data_analytics_agent.persistence import LocalStorage

    w = workspace
    source = test_settings.load_catalog().get("test")
    tool = create_execute_sql_tool(
        source,
        SQLiteBackend(test_settings.project_root / source.target["path"]),
        w.results,
        w.runs,
    )
    runtime = w.runtime("same-call")
    first = tool.func(
        query="SELECT 1 AS value", purpose="First result", runtime=runtime
    )
    assert (
        tool.func(query="SELECT 1 AS value", purpose="First result", runtime=runtime)
        == first
    )
    w.runs.begin_assignment(w.run, "second", "text-to-sql", "Second assignment")
    runtime.state["assignment_id"] = "second"
    second = tool.func(
        query="SELECT 2 AS value", purpose="Second result", runtime=runtime
    )
    assert first["result_id"] != second["result_id"]
    inspect = create_inspect_conversation_result_tool(
        w.results, source_id="test", run_store=w.runs
    )
    inspect.func(result_id=first["result_id"], runtime=runtime)
    reopened = RunStore(LocalStorage(w.storage.root))
    assert set(reopened.assignment(w.run, "test-assignment").datasets) == {
        first["result_id"]
    }
    assert set(reopened.assignment(w.run, "second").datasets) == {
        first["result_id"],
        second["result_id"],
    }
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 2


def test_analysis_completion_cannot_claim_another_assignments_execution(workspace):
    from data_analytics_agent.agents.data_analysis.schemas import PythonExecutionResult
    from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
    from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits

    w = workspace
    w.runs.record_python_execution(
        w.run,
        PythonExecutionResult(
            execution_id="other-execution",
            assignment_id="other",
            inputs={},
            executed_python="pass",
            attempt=1,
        ),
    )
    _, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    response = finish.func(
        outcome="analysis_completed", answer="Finished", runtime=w.runtime("finish")
    )
    assert response["ok"] is False
    assert not w.analyses.list_for_conversation(w.thread, source_id="test")
    assert w.runs.assignment(w.run, "test-assignment").completion is None


def test_analysis_synthesis_omits_code_and_logs_but_keeps_evidence():
    from data_analytics_agent.agents.data_analysis.schemas import (
        DataAnalysisResult,
        PythonExecutionResult,
        AnalysisOutput,
    )

    saved = DataAnalysisResult(
        outcome="analysis_completed",
        input_result_ids=["input"],
        answer="Mean is 3",
        executions=[
            PythonExecutionResult(
                execution_id="execution",
                inputs={"data": "input"},
                executed_python="secret_code()",
                stdout="verbose output",
                stderr="diagnostics",
                attempt=1,
                output_datasets={"means": "derived"},
                outputs=[AnalysisOutput(name="mean", kind="scalar", value=3)],
            )
        ],
    )
    view = saved.model_facing()
    assert (
        "secret_code" not in str(view)
        and "verbose output" not in str(view)
        and "diagnostics" not in str(view)
    )
    assert view["executions"][0]["output_datasets"] == {"means": "derived"}
    assert view["executions"][0]["outputs"][0]["value"] == 3
    assert saved.executions[0].executed_python == "secret_code()"


async def test_failed_run_continuation_includes_committed_work_after_restart(workspace):
    import json
    from tests.test_run_manager import Graph, Stream, manager
    from tests.test_persistent_analyst import save
    from data_analytics_agent.schemas import CoordinatorResponse
    from data_analytics_agent.stores import RunStore
    from data_analytics_agent.persistence import LocalStorage

    w = workspace
    dataset = save(w, [{"amount": 4}])
    receipt = {
        "answer": "Saved evidence",
        "datasets": [{"result_id": dataset.result_id}],
    }
    w.runs.finish_assignment(w.run, "test-assignment", receipt)
    w.runs.add_chart(
        w.run,
        {
            "chart_id": "saved-chart",
            "result_id": dataset.result_id,
            "title": "Saved chart",
        },
    )
    w.runs.fail(w.run, "Interrupted before publication")
    w.conversations.fail_run(w.thread, w.run)
    w.runs = RunStore(LocalStorage(w.storage.root))
    next_run = w.runs.create(w.thread, "test", "Continue the unfinished work")
    w.conversations.begin_run(w.thread, next_run)
    graph = Graph(
        [Stream(CoordinatorResponse(answer="The previous evidence is available."))]
    )
    await manager(w, graph).start(next_run)
    history = json.dumps(graph.inputs[0]["messages"])
    assert dataset.result_id in history and "saved-chart" in history
    assert "Interrupted before publication" in history
    assert "Analyze sales" in history
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 1


def test_report_cannot_change_published_evidence(workspace):
    from tests.test_persistent_analyst import save
    from data_analytics_agent.schemas import CoordinatorResponse
    from data_analytics_agent.reporting.tools import create_create_report_tool
    from data_analytics_agent.reporting.schemas import ReportSpec

    w = workspace
    selected = save(w, [{"amount": 4}])
    unrelated = save(w, [{"amount": 100}])
    publish, _ = create_presentation_tools(
        w.results, w.analyses, w.runs, w.conversations, source_id="test"
    )
    publish.func(
        findings=CoordinatorResponse(
            answer="Four", primary_result_id=selected.result_id
        ),
        runtime=w.runtime("publish"),
    )
    report = create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    )
    spec = ReportSpec(
        title="Four",
        blocks=[
            {"type": "table", "title": "Wrong scope", "result_id": unrelated.result_id}
        ],
    )
    failed = report.func(
        report_json=spec.model_dump_json(), runtime=w.runtime("report")
    )
    assert not failed["ok"] and "not selected" in failed["error"]
    assert not w.storage.load("reports", dict)


async def test_chart_typo_is_repaired_without_recomputation(test_settings, monkeypatch):
    import json
    import shutil
    from pathlib import Path
    from dataclasses import replace
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatResult, ChatGeneration
    from tests.test_agent_workflow import AnalystModel
    from data_analytics_agent.api import Services
    from data_analytics_agent import coordinator

    class ChartRecoveryModel(AnalystModel):
        dataset: str

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            tools = [m for m in messages if isinstance(m, ToolMessage)]
            chart = next((m for m in tools if m.name == "create_chart"), None)
            discovery = next(
                (m for m in tools if m.name == "list_conversation_charts"), None
            )
            publications = [m for m in tools if m.name == "publish_findings"]
            if chart is None:
                name, args = (
                    "create_chart",
                    {
                        "spec": {
                            "result_id": self.dataset,
                            "chart_type": "bar",
                            "title": "Amounts",
                            "x": "category",
                            "y": ["amount"],
                        }
                    },
                )
            elif not publications:
                saved = json.loads(chart.content)["chart_id"]
                typo = saved[:-1] + ("0" if saved[-1] != "0" else "1")
                name, args = (
                    "publish_findings",
                    {
                        "findings": {
                            "answer": "Amounts by category",
                            "primary_result_id": self.dataset,
                            "chart_ids": [typo],
                        }
                    },
                )
            elif discovery is None:
                assert publications[-1].status == "error"
                name, args = "list_conversation_charts", {}
            elif len(publications) == 1:
                saved = json.loads(discovery.content)["charts"][0]["chart_id"]
                name, args = (
                    "publish_findings",
                    {
                        "findings": {
                            "answer": "Amounts by category",
                            "primary_result_id": self.dataset,
                            "chart_ids": [saved],
                        }
                    },
                )
            elif not any(m.name == "create_report" for m in tools):
                name, args = (
                    "create_report",
                    {
                        "report_json": json.dumps(
                            {
                                "title": "Amounts",
                                "blocks": [
                                    {"type": "narrative", "body": "Amounts by category"}
                                ],
                            }
                        )
                    },
                )
            else:
                raise AssertionError(
                    "A completed report must not require another model call"
                )
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {"name": name, "args": args, "id": f"call-{len(tools)}"}
                            ],
                        )
                    )
                ]
            )

    root = Path(__file__).resolve().parents[1]
    shutil.copy(root / "AGENTS.md", test_settings.project_root / "AGENTS.md")
    shutil.copytree(root / "skills", test_settings.project_root / "skills")
    services = Services(
        settings=replace(
            test_settings, require_sql_approval=False, require_python_approval=False
        )
    )
    thread = services.conversations.create("test")
    saved = services.results.save(
        thread_id=thread,
        source_id="test",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 4}, {"category": "B", "amount": 5}],
    )
    monkeypatch.setattr(
        coordinator,
        "_build_chat_model",
        lambda *a, **k: ChartRecoveryModel(dataset=saved.result_id),
    )
    run = services.runs.create(thread, "test", "Chart the saved amounts")
    services.conversations.begin_run(thread, run)
    await services.manager().start(run)
    state = services.runs.get(run)
    assert state.status == "completed", state.error
    assert state.answer.report and len(state.answer.charts) == 1
    names = [e.tool.name for e in state.events if e.tool]
    assert "list_conversation_charts" in names
    assert not {"execute_sql", "query_saved_results", "execute_analysis_python"} & set(
        names
    )
    assert len(services.storage.load("charts", dict)) == 1
    assert len(services.storage.load("reports", dict)) == 1


def test_completed_assignment_is_invalidated_by_new_correction(workspace):
    from data_analytics_agent.handoff import AssignmentMiddleware

    w = workspace
    receipt = {"analysis_id": "saved-analysis", "answer": "Original scope"}
    w.runs.finish_assignment(w.run, "test-assignment", receipt)
    middleware = AssignmentMiddleware(w.runs, "data-analysis")
    state = w.runtime("finish").state
    assert middleware.before_model(state, None)["structured_response"] == receipt
    w.runs.accept_correction(w.run, "Use a different population")
    assert middleware.before_model(state, None) is None
    assert w.runs.assignment(w.run, "test-assignment").completion is None


def test_chart_discovery_and_resolution_preserve_scope(workspace):
    from data_analytics_agent.presentation import create_list_conversation_charts_tool
    from data_analytics_agent.evidence import EvidenceResolver
    from data_analytics_agent.datasets import StoreNotFound

    w = workspace
    for key, thread, source in [
        ("own", w.thread, "test"),
        ("other-thread", "foreign", "test"),
        ("other-source", w.thread, "foreign"),
    ]:
        w.storage.put(
            "charts",
            key,
            {
                "thread_id": thread,
                "source_id": source,
                "spec": {"chart_id": key, "title": key},
            },
            dict,
        )
    tool = create_list_conversation_charts_tool(w.runs, source_id="test")
    assert [c["chart_id"] for c in tool.func(runtime=w.runtime("list"))["charts"]] == [
        "own"
    ]
    resolver = EvidenceResolver(
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    for key in ("other-thread", "other-source"):
        with pytest.raises(StoreNotFound):
            resolver.chart(key)


def test_sql_handoff_attaches_all_saved_results_without_model_ids(workspace):
    from data_analytics_agent.handoff import AssignmentMiddleware
    from data_analytics_agent.schemas import SQLAnalysisResponse
    from tests.test_persistent_analyst import save

    w = workspace
    ids = []
    for n in (1, 2):
        result = save(w, [{"amount": n}])
        ids.append(result.result_id)
        w.runs.record_assignment_dataset(
            w.run,
            "test-assignment",
            {
                "result_id": result.result_id,
                "label": f"Result {n}",
                "columns": result.columns,
                "row_count": result.row_count,
                "truncated": result.truncated,
            },
        )
    state = {
        **w.runtime("done").state,
        "structured_response": SQLAnalysisResponse(answer="Two saved results"),
    }
    completed = AssignmentMiddleware(w.runs, "text-to-sql").after_agent(state, None)[
        "structured_response"
    ]
    assert [r["result_id"] for r in completed["datasets"]] == ids
    assert (
        "result_id" not in SQLAnalysisResponse.model_fields
        and "sql" not in SQLAnalysisResponse.model_fields
    )
    assert completed["answer"] == "Two saved results"
