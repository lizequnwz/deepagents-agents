from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from general_agent.advisor_repository import AdvisorRepository
from general_agent.run_manager import RunManager, RuntimeUsageCallback, _node_label
from general_agent.runtime_store import RuntimeStore
from general_agent.schemas import RunStatus
from general_agent.workspace import Workspace
from tests.fakes import FakeGraph


async def test_run_manager_finishes_graph_updates(settings) -> None:
    runtime = RuntimeStore()
    repository = AdvisorRepository(settings.advisor_repository_db)
    graph = FakeGraph()
    manager = RunManager(
        settings=settings,
        runtime=runtime,
        repository=repository,
        workspace=Workspace(settings.data_root),
        graph=graph,
    )
    conversation = runtime.create_conversation()
    run_id = manager.create_run("A123456", conversation.conversation_id, "what can you do")
    manager.start(run_id, "A123456", [])
    for _ in range(100):
        run = runtime.get_run(run_id)
        if run.status != RunStatus.RUNNING:
            break
        await asyncio.sleep(0.01)
    assert run.status == RunStatus.COMPLETED
    assert run.assistant_text == "Finished"
    assert any(event.kind == "node_completed" for event in run.events)
    repository.close()


def test_usage_callback_records_ai_message_metadata() -> None:
    runtime = RuntimeStore()
    conversation = runtime.create_conversation()
    run_id, _ = runtime.create_run(conversation.conversation_id, "hello")
    callback = RuntimeUsageCallback(runtime, run_id, "A123456")
    callback.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="Hi!",
                            usage_metadata={
                                "input_tokens": 8,
                                "output_tokens": 3,
                                "total_tokens": 11,
                            },
                        )
                    )
                ]
            ]
        )
    )

    diagnostics = runtime.get_run(run_id).diagnostics
    assert diagnostics.model_calls == 1
    assert diagnostics.tokens.total_tokens == 11


def test_graph_node_names_have_user_facing_progress_labels() -> None:
    assert _node_label("map_input") == "Identifying advisor columns"
    assert _node_label("confirm_manual") == "Applying the confirmed manual match"
