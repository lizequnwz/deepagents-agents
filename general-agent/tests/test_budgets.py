from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware import SummarizationMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
from pydantic import Field

from general_agent.agent import build_agent, configure_harness_profile
from general_agent.budgets import (
    RunBudget,
    RunBudgetCallback,
    RunBudgetExceeded,
    run_budget_scope,
)
from general_agent.workspace import Workspace


class ScriptedModel(FakeMessagesListChatModel):
    """Exercise the real model callback boundary without a provider."""

    model_name: str = Field(default_factory=lambda: f"budget-{uuid4().hex}")
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        return {"ls_provider": "test", "ls_model_name": self.model_name}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _budget(*, models: int = 10, tools: int = 10, tasks: int = 5) -> RunBudget:
    return RunBudget(
        max_model_calls=models, max_tool_calls=tools, max_task_calls=tasks
    )


def _callbacks() -> dict[str, Any]:
    return {"callbacks": [RunBudgetCallback()], "recursion_limit": 30}


def _tool_message(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def _delegated_responses() -> list[AIMessage]:
    return [
        _tool_message(
            "task",
            {"description": "Write the result", "subagent_type": "general-purpose"},
            "delegation",
        ),
        _tool_message(
            "write_file", {"file_path": "/result.txt", "content": "written"}, "write"
        ),
        AIMessage(content="Subagent finished"),
        AIMessage(content="Parent finished"),
    ]


def _graph(settings: Any, tmp_path: Path, model: ScriptedModel) -> tuple[Any, Path]:
    source = tmp_path / "source"
    (source / "skills").mkdir(parents=True)
    backend = FilesystemBackend(root_dir=source, virtual_mode=True)
    graph = build_agent(
        settings,
        workspace=Workspace(settings.workspace_root, settings.data_root),
        backend=backend,
        checkpointer=None,
        model=model,
    )
    return graph, source


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_limits_must_be_positive_integers(invalid: Any) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        _budget(models=invalid)


def test_parallel_reservations_stop_at_the_ceiling_and_stay_exhausted() -> None:
    budget = _budget(models=7)

    def reserve() -> bool:
        try:
            budget.reserve_model_call()
        except RunBudgetExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as executor:
        admitted = list(executor.map(lambda _: reserve(), range(80)))
    assert sum(admitted) == 7
    assert budget.snapshot() == {"model_calls": 7, "tool_calls": 0, "task_calls": 0}
    with pytest.raises(RunBudgetExceeded, match="model-call limit of 7"):
        budget.reserve_tool_call("write_file")
    with pytest.raises(RunBudgetExceeded, match="model-call limit of 7"):
        budget.raise_if_exceeded()


def test_task_admission_reserves_tool_and_task_atomically() -> None:
    budget = _budget(tasks=1)
    budget.reserve_tool_call("task")
    budget.reserve_tool_call("read_file")
    with pytest.raises(RunBudgetExceeded, match="task-call limit of 1"):
        budget.reserve_tool_call("task")
    assert budget.snapshot() == {"model_calls": 0, "tool_calls": 2, "task_calls": 1}


class StartObserver(BaseCallbackHandler):
    def __init__(self) -> None:
        self.starts = 0

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self.starts += 1


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_model_admission_propagates_before_execution_and_observers(
    asynchronous: bool,
) -> None:
    model = ScriptedModel(responses=[AIMessage(content="ok")])
    observer = StartObserver()
    config = {"callbacks": [RunBudgetCallback(), observer]}
    budget = _budget(models=1)
    with run_budget_scope(budget):
        if asynchronous:
            await model.ainvoke("one", config)
            with pytest.raises(RunBudgetExceeded):
                await model.ainvoke("two", config)
        else:
            model.invoke("one", config)
            with pytest.raises(RunBudgetExceeded):
                model.invoke("two", config)
    assert len(model.calls) == 1
    assert observer.starts == 1
    # Missing token usage does not invent tokens or weaken invocation limits.
    assert model.responses[0].usage_metadata is None
    assert budget.snapshot()["model_calls"] == 1


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_admission_without_run_scope_fails_closed(asynchronous: bool) -> None:
    model = ScriptedModel(responses=[AIMessage(content="must not execute")])
    with pytest.raises(RuntimeError, match="active run budget"):
        if asynchronous:
            await model.ainvoke("outside a run", _callbacks())
        else:
            model.invoke("outside a run", _callbacks())
    assert model.calls == []


async def test_budget_scope_isolated_between_concurrent_runs_and_reset_after_exit(
) -> None:
    shared_handler = RunBudgetCallback()
    budgets = [_budget(models=1), _budget(models=2)]

    async def invoke(budget: RunBudget, count: int) -> None:
        model = ScriptedModel(responses=[AIMessage(content="ok")])
        with run_budget_scope(budget):
            for _ in range(count):
                await model.ainvoke("hello", {"callbacks": [shared_handler]})
                await asyncio.sleep(0)

    await asyncio.gather(invoke(budgets[0], 1), invoke(budgets[1], 2))
    assert [budget.snapshot()["model_calls"] for budget in budgets] == [1, 2]
    with pytest.raises(RuntimeError, match="active run budget"):
        shared_handler.on_chat_model_start({}, [[]])


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_tool_admission_precedes_side_effects_and_uses_canonical_name(
    asynchronous: bool,
) -> None:
    side_effects: list[int] = []

    @tool
    def task(value: int) -> str:
        """A delegation-shaped tool with an observable effect."""
        side_effects.append(value)
        return "ok"

    budget = _budget(tasks=1)
    config = {**_callbacks(), "run_name": "not-task"}
    with run_budget_scope(budget):
        if asynchronous:
            await task.ainvoke({"value": 1}, config)
            with pytest.raises(RunBudgetExceeded, match="task-call"):
                await task.ainvoke({"value": 2}, config)
        else:
            task.invoke({"value": 1}, config)
            with pytest.raises(RunBudgetExceeded, match="task-call"):
                task.invoke({"value": 2}, config)
    assert side_effects == [1]
    assert budget.snapshot() == {"model_calls": 0, "tool_calls": 1, "task_calls": 1}


async def test_parallel_tool_starts_cannot_overspend_or_execute_denied_calls() -> None:
    side_effects: list[int] = []

    @tool
    async def record(value: int) -> str:
        """Record an admitted invocation."""
        side_effects.append(value)
        await asyncio.sleep(0)
        return "ok"

    budget = _budget(tools=3)
    with run_budget_scope(budget):
        results = await asyncio.gather(
            *(record.ainvoke({"value": i}, _callbacks()) for i in range(20)),
            return_exceptions=True,
        )
    assert len(side_effects) == 3
    assert results.count("ok") == 3
    assert sum(isinstance(result, RunBudgetExceeded) for result in results) == 17
    assert budget.snapshot()["tool_calls"] == 3


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_real_general_purpose_graph_uses_whole_run_model_limit(
    settings: Any, tmp_path: Path, asynchronous: bool
) -> None:
    model = ScriptedModel(responses=_delegated_responses())
    graph, source = _graph(settings, tmp_path, model)
    budget = _budget(models=2)
    with run_budget_scope(budget), pytest.raises(RunBudgetExceeded, match="model-call"):
        if asynchronous:
            await graph.ainvoke(
                {"messages": [HumanMessage(content="Delegate")]}, _callbacks()
            )
        else:
            graph.invoke(
                {"messages": [HumanMessage(content="Delegate")]}, _callbacks()
            )
    assert len(model.calls) == 2
    assert (source / "result.txt").read_text() == "written"
    assert budget.snapshot() == {"model_calls": 2, "tool_calls": 2, "task_calls": 1}


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_real_general_purpose_tool_denial_prevents_delegated_write(
    settings: Any, tmp_path: Path, asynchronous: bool
) -> None:
    model = ScriptedModel(responses=_delegated_responses())
    graph, source = _graph(settings, tmp_path, model)
    budget = _budget(tools=1)
    with run_budget_scope(budget), pytest.raises(RunBudgetExceeded, match="tool-call"):
        if asynchronous:
            await graph.ainvoke(
                {"messages": [HumanMessage(content="Delegate")]}, _callbacks()
            )
        else:
            graph.invoke(
                {"messages": [HumanMessage(content="Delegate")]}, _callbacks()
            )
    assert not (source / "result.txt").exists()
    assert len(model.calls) == 2
    assert budget.snapshot() == {"model_calls": 2, "tool_calls": 1, "task_calls": 1}


async def test_declarative_reviewer_with_a_different_model_shares_parent_budget(
    tmp_path: Path,
) -> None:
    parent = ScriptedModel(
        responses=[
            _tool_message(
                "task", {"description": "Review", "subagent_type": "review"}, "review"
            ),
            AIMessage(content="must not execute"),
        ]
    )
    reviewer = ScriptedModel(responses=[AIMessage(content="review findings")])
    configure_harness_profile(parent)
    graph = create_deep_agent(
        model=parent,
        backend=FilesystemBackend(root_dir=tmp_path, virtual_mode=True),
        subagents=[
            {
                "name": "review",
                "description": "Review source",
                "system_prompt": "Review",
                "model": reviewer,
                "tools": [],
            }
        ],
    )
    budget = _budget(models=2)
    with run_budget_scope(budget), pytest.raises(RunBudgetExceeded, match="model-call"):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Review")]}, _callbacks()
        )
    assert len(parent.calls) == len(reviewer.calls) == 1
    assert budget.snapshot() == {"model_calls": 2, "tool_calls": 1, "task_calls": 1}


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_summarization_model_call_shares_budget_before_ordinary_model_call(
    settings: Any, tmp_path: Path, monkeypatch: Any, asynchronous: bool
) -> None:
    model = ScriptedModel(
        responses=[AIMessage(content="summary"), AIMessage(content="answer")]
    )
    monkeypatch.setattr(
        "deepagents.graph.create_summarization_middleware",
        lambda model, backend: SummarizationMiddleware(
            model=model, backend=backend, trigger=("messages", 2), keep=("messages", 1)
        ),
    )
    graph, _ = _graph(settings, tmp_path, model)
    budget = _budget(models=1)
    messages = [
        HumanMessage(content="earlier"),
        AIMessage(content="earlier answer"),
        HumanMessage(content="new task"),
    ]
    with run_budget_scope(budget), pytest.raises(RunBudgetExceeded, match="model-call"):
        if asynchronous:
            await graph.ainvoke({"messages": messages}, _callbacks())
        else:
            graph.invoke({"messages": messages}, _callbacks())
    assert len(model.calls) == 1
    assert "earlier answer" in model.calls[0][0].content
    assert budget.snapshot() == {"model_calls": 1, "tool_calls": 0, "task_calls": 0}


async def test_v3_event_stream_enforces_budget_before_delegated_write(
    settings: Any, tmp_path: Path,
) -> None:
    model = ScriptedModel(responses=_delegated_responses())
    graph, source = _graph(settings, tmp_path, model)
    budget = _budget(tools=1)
    with run_budget_scope(budget):
        stream = await graph.astream_events(
            {"messages": [HumanMessage(content="Delegate")]},
            config=_callbacks(),
            version="v3",
        )
        try:
            with pytest.raises(RunBudgetExceeded, match="tool-call"):
                async for _ in stream:
                    pass
                await stream.output()
        finally:
            await stream.abort()
    assert not (source / "result.txt").exists()
    assert len(model.calls) == 2
    assert budget.snapshot() == {"model_calls": 2, "tool_calls": 1, "task_calls": 1}


async def test_shared_graph_has_no_budget_state_between_runs(
    settings: Any, tmp_path: Path,
) -> None:
    model = ScriptedModel(responses=[AIMessage(content="answer")])
    graph, _ = _graph(settings, tmp_path, model)
    budgets = [_budget(models=1), _budget(models=1)]
    for budget in budgets:
        with run_budget_scope(budget):
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="hello")]}, _callbacks()
            )
            budget.raise_if_exceeded()
        assert result["messages"][-1].content == "answer"
    assert len(model.calls) == 2
    assert [budget.snapshot()["model_calls"] for budget in budgets] == [1, 1]


def test_swallowed_admission_error_still_rejects_run_finalization() -> None:
    budget = _budget(models=1)
    budget.reserve_model_call()
    with run_budget_scope(budget):
        try:
            RunBudgetCallback().on_chat_model_start({}, [[]])
        except RunBudgetExceeded:
            pass
    with pytest.raises(RunBudgetExceeded):
        budget.raise_if_exceeded()
