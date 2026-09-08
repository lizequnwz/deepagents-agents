"""Installed-framework probe: nested specialists accept input between tool cycles."""

import asyncio
import pytest
from data_analytics_agent.steering import SteeringMiddleware
from data_analytics_agent.stores import RunStore
from data_analytics_agent.agents.text_to_sql.tools import AnalyticsAgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain.tools import tool
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver


@pytest.mark.parametrize("operation", ["execute_sql", "execute_analysis_python"])
async def test_nested_specialist_receives_correction_after_slow_tool(
    monkeypatch, operation
):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    observed = []
    runs = RunStore()
    run_id = runs.create("thread", "source", "Original")
    started, release = asyncio.Event(), asyncio.Event()

    @tool(operation)
    async def slow_step() -> str:
        """Execute an isolated slow step."""
        started.set()
        await release.wait()
        return "Saved original-scope evidence"

    class Model(BaseChatModel):
        role: str

        @property
        def _llm_type(self):
            return "steering-probe"

        def bind_tools(self, *args, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            completed = any(isinstance(m, ToolMessage) for m in messages)
            if self.role == "coordinator":
                response = (
                    AIMessage(content="Finished")
                    if completed
                    else AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "task",
                                "args": {
                                    "subagent_type": "worker",
                                    "description": "Work",
                                },
                                "id": "assignment",
                            }
                        ],
                    )
                )
            elif completed:
                observed.extend(
                    str(m.content) for m in messages if isinstance(m, HumanMessage)
                )
                response = AIMessage(content="Corrected analysis")
            else:
                response = AIMessage(
                    content="",
                    tool_calls=[{"name": operation, "args": {}, "id": "slow"}],
                )
            return ChatResult(generations=[ChatGeneration(message=response)])

    graph = create_deep_agent(
        model=Model(role="coordinator"),
        middleware=[SteeringMiddleware(runs, "coordinator")],
        subagents=[
            {
                "name": "worker",
                "description": "Worker",
                "system_prompt": "Work",
                "model": Model(role="worker"),
                "tools": [slow_step],
                "middleware": [SteeringMiddleware(runs, "worker")],
            }
        ],
        checkpointer=InMemorySaver(),
        state_schema=AnalyticsAgentState,
    )
    task = asyncio.create_task(
        graph.ainvoke(
            {
                "messages": [HumanMessage("Original")],
                "run_id": run_id,
                "thread_id": "thread",
                "source_id": "source",
                "question": "Original",
            },
            config={"configurable": {"thread_id": "probe"}},
        )
    )
    await asyncio.wait_for(started.wait(), 10)
    correction = runs.accept_correction(run_id, "Use the revised population")
    release.set()
    await asyncio.wait_for(task, 10)
    assert sum("Use the revised population" in text for text in observed) == 1
    assert runs.get(run_id).corrections[0].message_id == correction.message_id
    assert set(runs.get(run_id).corrections[0].delivered_to) == {
        "worker",
        "coordinator",
    }
