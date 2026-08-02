from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.run_manager import RunManager
from general_agent.schemas import RunStatus
from general_agent.store import Store
from general_agent.workspace import Workspace
from tests.fakes import FakeGraph


def make_manager(settings, graph):
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    return RunManager(
        settings=settings,
        store=store,
        workspace=workspace,
        backend=backend,
        graph=graph,
    ), store


@pytest.mark.asyncio
async def test_v3_events_project_root_tools_plans_and_usage(settings) -> None:
    graph = FakeGraph()
    manager, store = make_manager(settings, graph)
    conversation = store.create_conversation()
    run_id = manager.create_run("A123456", conversation.conversation_id, "Do the task")
    manager.start(run_id, "A123456", [])
    await asyncio.wait_for(manager._tasks[run_id], timeout=3)

    run = store.get_run(run_id)
    assert run.status == RunStatus.COMPLETED
    assert run.assistant_text == "Finished"
    assert graph.calls[0][2] == "v3"
    kinds = [event.kind for event in run.events]
    assert "assistant_delta" not in kinds
    assert "plan_updated" in kinds
    assert "tool_started" in kinds and "tool_finished" in kinds
    tool_start = next(event for event in run.events if event.kind == "tool_started")
    assert tool_start.agent == "advisor-match-agent"
    assert tool_start.data["input"]["attachment_id"] == "att_test"
    tool_finish = next(event for event in run.events if event.kind == "tool_finished")
    assert tool_finish.data["output"]["match_session_id"] == "ams_test"
    assert run.diagnostics.tokens.total_tokens == 10
    assert run.diagnostics.model_calls_missing_usage == 0
    assert run.diagnostics.token_usage_partial is False
    assert {usage.agent for usage in run.diagnostics.agents} == {"advisor-match-agent"}
    turn = store.get_conversation(conversation.conversation_id).turns[0]
    assert [event.kind for event in turn.events] == kinds
    store.close()


@pytest.mark.asyncio
async def test_stop_aborts_stream_and_partial_turn_is_not_future_history(settings) -> None:
    graph = FakeGraph(blocked=True)
    manager, store = make_manager(settings, graph)
    conversation = store.create_conversation()
    run_id = manager.create_run("A123456", conversation.conversation_id, "Wait")
    manager.start(run_id, "A123456", [])
    for _ in range(100):
        if graph.streams:
            break
        await asyncio.sleep(0.01)
    assert await manager.stop(run_id, "A123456") is True
    await asyncio.gather(*manager._tasks.values(), return_exceptions=True)
    assert store.get_run(run_id).status == RunStatus.STOPPED
    assert store.completed_history(conversation.conversation_id) == []
    assert graph.streams[0].aborted.is_set()
    store.close()


@pytest.mark.asyncio
async def test_provider_reported_run_token_budget_stops_the_graph(settings) -> None:
    constrained = replace(settings, max_run_tokens=5)
    graph = FakeGraph()
    manager, store = make_manager(constrained, graph)
    conversation = store.create_conversation()
    run_id = manager.create_run(
        "A123456", conversation.conversation_id, "Use too many tokens"
    )
    manager.start(run_id, "A123456", [])
    await asyncio.wait_for(manager._tasks[run_id], timeout=3)
    run = store.get_run(run_id)
    assert run.status == RunStatus.FAILED
    assert "token limit of 5" in (run.error or "")
    assert graph.streams[0].aborted.is_set()
    store.close()
