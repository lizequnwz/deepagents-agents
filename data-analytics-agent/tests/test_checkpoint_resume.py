"""Exercise the maintained SQLite checkpointer across real graph instances."""

from types import SimpleNamespace
import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from data_analytics_agent.agents.text_to_sql.tools import AnalyticsAgentState
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits
from data_analytics_agent.stores import RunStore, ResultStore, DataAnalysisStore
from data_analytics_agent.persistence import LocalStorage
from tests.test_persistent_analyst import save


async def test_checkpoint_restart_reuses_committed_step_and_executes_exact_edited_python(
    workspace,
):
    w = workspace
    source = save(w, [{"value": 1}, {"value": 2}])
    code = "analysis_outputs={'total':datasets['sales'].value.sum()}"
    config = {"configurable": {"thread_id": w.run}}

    def graph(saver, results, runs, analyses):
        execute, _ = create_analysis_tools(
            results, runs, analyses, source_id="test", limits=PythonExecutionLimits()
        )

        async def initial(state):
            value = await asyncio.to_thread(
                execute.func,
                inputs={"sales": source.result_id},
                code=code,
                runtime=SimpleNamespace(state=state, tool_call_id="committed"),
            )
            return {
                "messages": [
                    {"role": "assistant", "content": str(value["execution_id"])}
                ]
            }

        async def reviewed(state):
            edited = interrupt({"code": code, "inputs": {"sales": source.result_id}})
            await asyncio.to_thread(
                execute.func,
                inputs={"sales": source.result_id},
                code=edited,
                runtime=SimpleNamespace(state=state, tool_call_id="edited"),
            )
            return {}

        builder = StateGraph(AnalyticsAgentState)
        builder.add_node("initial", initial)
        builder.add_node("reviewed", reviewed)
        builder.add_edge(START, "initial")
        builder.add_edge("initial", "reviewed")
        builder.add_edge("reviewed", END)
        return builder.compile(checkpointer=saver)

    database = str(w.storage.root / "checkpoints.sqlite")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        await saver.setup()
        first = graph(saver, w.results, w.runs, w.analyses)
        result = await first.ainvoke(
            {
                "thread_id": w.thread,
                "run_id": w.run,
                "source_id": "test",
                "question": "Sum values",
                "messages": [],
            },
            config=config,
        )
        assert result["__interrupt__"] and len(w.runs.get_python_execution(w.run)) == 1
    storage = LocalStorage(w.storage.root)
    results, runs, analyses = (
        ResultStore(storage),
        RunStore(storage),
        DataAnalysisStore(storage),
    )
    edited = "analysis_outputs={'total':datasets['sales'].value.sum()*2}\n"
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        await saver.setup()
        second = graph(saver, results, runs, analyses)
        await second.ainvoke(Command(resume=edited), config=config)
    executions = runs.get_python_execution(w.run)
    assert len(executions) == 2 and executions[-1].executed_python == edited
    assert executions[-1].outputs[0].value == 6
    assert len(results.list_for_conversation(w.thread, source_id="test")) == 1
