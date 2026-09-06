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
