import asyncio
from data_analytics_agent.run_manager import RunManager
from data_analytics_agent.schemas import CoordinatorResponse, RunStatus
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from tests.test_persistent_analyst import save


class Stream:
    def __init__(self, response, delay=0):
        self.response = response
        self.delay = delay

    async def __aiter__(self):
        await asyncio.sleep(self.delay)
        if False:
            yield {}

    async def interrupted(self):
        return False

    async def output(self):
        return {"structured_response": self.response}


class Graph:
    def __init__(self, streams):
        self.streams = iter(streams)
        self.inputs = []

    async def astream_events(self, input, **kwargs):
        self.inputs.append(input)
        return next(self.streams)


def manager(w, graph):
    return RunManager(
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
        agent=graph,
    )


def test_direct_evidence_resolution_uses_saved_sql_and_lineage(workspace):
    w = workspace
    r = save(w, [{"value": 2}], executed_sql="SELECT 2 AS value")
    derived = save(w, [{"value": 4}], parent_result_ids=[r.result_id], kind="python")
    answer = resolve_answer(
        CoordinatorResponse(
            answer="Four",
            primary_result_id=derived.result_id,
            supporting_result_ids=[derived.result_id],
        ),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    assert [r.result_id for r in answer.results] == [derived.result_id, r.result_id]
    assert answer.results[1].executed_sql == "SELECT 2 AS value"


async def test_greeting_completes_without_report(workspace):
    w = workspace
    await manager(w, Graph([Stream(CoordinatorResponse(answer="Hello"))])).start(w.run)
    assert w.runs.get(w.run).status == RunStatus.COMPLETED
    assert w.conversations.get(w.thread).turns[0].answer.report is None


async def test_findings_remain_visible_report_failure_retry_does_not_recompute(
    workspace,
):
    w = workspace
    r = save(w, [{"value": 7}])
    response = CoordinatorResponse(
        answer="Seven",
        primary_result_id=r.result_id,
        supporting_result_ids=[r.result_id],
    )
    w.runs.publish(
        w.run,
        resolve_answer(
            response,
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=w.runs,
        ),
    )
    graph = Graph([Stream(response, 0.05)])
    m = manager(w, graph)
    task = asyncio.create_task(m.start(w.run))
    await asyncio.sleep(0.01)
    assert w.runs.get(w.run).findings.answer == "Seven"
    await task
    assert w.runs.get(w.run).status == RunStatus.FAILED
    spec = ReportSpec(
        title="Seven",
        blocks=[{"type": "table", "title": "Evidence", "result_id": r.result_id}],
    )
    w.runs.save_report_spec(w.run, spec.model_dump(mode="json"))
    w.conversations.begin_run(w.thread, w.run)
    await m.retry_report(w.run)
    assert w.runs.get(w.run).status == RunStatus.COMPLETED
    assert w.runs.get(w.run).answer.report is not None
    assert len(graph.inputs) == 1 and not w.runs.get_python_execution(w.run)


async def test_stop_waits_for_execution_exit_before_paused(workspace):
    w = workspace
    graph = Graph([Stream(CoordinatorResponse(answer="Unfinished"), 5)])
    m = manager(w, graph)
    task = asyncio.create_task(m.start(w.run))
    await asyncio.sleep(0.01)
    with w.runs.worker(w.run):
        await m.stop(w.run)
        await asyncio.sleep(0.02)
        assert w.runs.get(w.run).status == RunStatus.STOPPING
    await task
    assert w.runs.get(w.run).status == RunStatus.PAUSED
    assert not w.conversations.get(w.thread).active_run_id
    assert not w.conversations.get(w.thread).turns


async def test_analysis_budget_reserves_presentation_phase(workspace):
    w = workspace
    w.runs.analysis_budget_seconds = 0.01
    # minimum one second remaining in manager; stream stalls beyond it.
    graph = Graph(
        [
            Stream(CoordinatorResponse(answer="not returned"), 5),
            Stream(
                CoordinatorResponse(
                    answer="No completed data available.",
                    partial=True,
                    unresolved_questions=["Retrieve data"],
                )
            ),
        ]
    )
    await manager(w, graph).start(w.run)
    run = w.runs.get(w.run)
    assert run.status == RunStatus.COMPLETED and run.answer.partial
    assert (
        len(graph.inputs) == 2 and "budget" in graph.inputs[1]["messages"][0]["content"]
    )


async def test_queued_follow_up_runs_after_report_failure_and_preserves_parent(
    workspace,
):
    w = workspace
    result = save(w, [{"value": 7}])
    response = CoordinatorResponse(answer="Seven", primary_result_id=result.result_id)
    w.runs.publish(
        w.run,
        resolve_answer(
            response,
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=w.runs,
        ),
    )
    follow_up = w.runs.create(w.thread, "test", "Explain the saved result")
    w.runs.add_follow_up(w.run, follow_up)
    w.conversations.queue_run(w.thread, follow_up)
    graph = Graph([Stream(response), Stream(CoordinatorResponse(answer="Explanation"))])
    await manager(w, graph).start(w.run)
    assert w.runs.get(w.run).status == RunStatus.FAILED  # Required report missing.
    assert w.runs.get(w.run).findings.answer == "Seven"
    assert w.runs.get(follow_up).status == RunStatus.COMPLETED
    assert w.conversations.get(w.thread).turns[0].run_id == follow_up
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 1
    assert any("Seven" in message["content"] for message in graph.inputs[1]["messages"])


def publish_test_findings(w):
    result = save(w, [{"value": 7}])
    response = CoordinatorResponse(answer="Seven", primary_result_id=result.result_id)
    w.runs.publish(
        w.run,
        resolve_answer(
            response,
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=w.runs,
        ),
    )
    return response, ReportSpec(
        title="Seven",
        blocks=[{"type": "table", "title": "Evidence", "result_id": result.result_id}],
    )


async def test_report_retry_reuses_valid_artifact_after_final_response_failure(
    workspace,
):
    from data_analytics_agent.reporting.tools import generate_report

    w = workspace
    _, spec = publish_test_findings(w)
    artifact = generate_report(
        spec,
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
        findings=w.runs.get(w.run).findings,
    )
    w.runs.attach_report(w.run, artifact.reference())
    w.runs.fail(w.run, "Invalid final response")
    graph = Graph([])
    await manager(w, graph).retry_report(w.run)
    state = w.runs.get(w.run)
    assert state.status == RunStatus.COMPLETED and state.error is None
    assert state.answer.report.report_id == artifact.report_id
    assert not graph.inputs
    assert len(w.storage.load("reports", dict)) == 1
    assert len(w.conversations.get(w.thread).turns) == 1


import pytest


@pytest.mark.parametrize("invalid_spec", [False, True])
async def test_report_retry_repairs_missing_or_invalid_spec_without_analysis(
    workspace, monkeypatch, invalid_spec
):
    from data_analytics_agent.reporting.tools import generate_report

    w = workspace
    response, good_spec = publish_test_findings(w)
    if invalid_spec:
        w.runs.save_report_spec(
            w.run,
            {
                "title": "Invalid",
                "blocks": [
                    {"type": "table", "title": "Missing", "result_id": "wrong-id"}
                ],
            },
        )
    w.runs.fail(w.run, "Report interrupted")
    w.runs.cancel_event(w.run).set()
    graph = Graph([Stream(response)])
    original = graph.astream_events

    async def repair(input, **kwargs):
        assert not w.runs.cancel_event(w.run).is_set()
        assert "Do not rerun SQL or Python" in input["messages"][0]["content"]
        assert response.primary_result_id in input["messages"][0]["content"]
        if invalid_spec:
            assert "wrong-id" in input["messages"][0]["content"]
        artifact = generate_report(
            good_spec,
            thread_id=w.thread,
            source_id="test",
            result_store=w.results,
            analysis_store=w.analyses,
            run_store=w.runs,
            report_store=w.reports,
            findings=w.runs.get(w.run).findings,
        )
        w.runs.attach_report(w.run, artifact.reference())
        return await original(input, **kwargs)

    monkeypatch.setattr(graph, "astream_events", repair)
    await manager(w, graph).retry_report(w.run)
    assert w.runs.get(w.run).status == RunStatus.COMPLETED
    assert w.runs.get(w.run).error is None
    assert len(graph.inputs) == 1
    assert len(w.results.list_for_conversation(w.thread, source_id="test")) == 1
    assert not w.runs.get_python_execution(w.run)


async def test_report_retry_recreates_missing_html(workspace):
    from pathlib import Path
    from data_analytics_agent.reporting.tools import generate_report

    w = workspace
    _, spec = publish_test_findings(w)
    w.runs.save_report_spec(w.run, spec.model_dump(mode="json"))
    artifact = generate_report(
        spec,
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
        findings=w.runs.get(w.run).findings,
    )
    w.runs.attach_report(w.run, artifact.reference())
    Path(artifact.html_path).unlink()
    w.runs.fail(w.run, "Report file missing")
    graph = Graph([])
    await manager(w, graph).retry_report(w.run)
    state = w.runs.get(w.run)
    assert state.status == RunStatus.COMPLETED
    assert state.answer.report.report_id != artifact.report_id
    assert w.reports.get_unscoped(state.answer.report.report_id).html
    assert not graph.inputs
