from __future__ import annotations

import pytest

from general_agent.advisor_repository import AdvisorRepository
from general_agent.runtime_store import ActiveRunError, RuntimeStore
from general_agent.schemas import RunStatus


def test_runtime_allows_different_conversations_but_serializes_each_thread() -> None:
    runtime = RuntimeStore()
    first = runtime.create_conversation("First")
    second = runtime.create_conversation("Second")
    first_run, _ = runtime.create_run(first.conversation_id, "one")
    second_run, _ = runtime.create_run(second.conversation_id, "two")
    with pytest.raises(ActiveRunError):
        runtime.create_run(first.conversation_id, "collision")
    runtime.finish_run(first_run, RunStatus.COMPLETED, assistant_text="done")
    runtime.finish_run(second_run, RunStatus.COMPLETED, assistant_text="done")


def test_runtime_state_is_not_recovered_after_restart() -> None:
    runtime = RuntimeStore()
    conversation = runtime.create_conversation()
    assert RuntimeStore().list_conversations() == []
    assert runtime.get_conversation(conversation.conversation_id)


def test_runtime_aggregates_provider_reported_model_usage() -> None:
    runtime = RuntimeStore()
    conversation = runtime.create_conversation()
    run_id, _ = runtime.create_run(conversation.conversation_id, "hello")

    runtime.record_model_call(
        run_id,
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 2},
            "output_token_details": {"reasoning": 1},
        },
    )
    runtime.record_model_call(
        run_id,
        {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    )
    runtime.finish_run(run_id, RunStatus.COMPLETED, assistant_text="Hi!")

    diagnostics = runtime.get_run(run_id).diagnostics
    assert diagnostics.model_calls == 2
    assert diagnostics.model_calls_missing_usage == 0
    assert diagnostics.tokens.input_tokens == 13
    assert diagnostics.tokens.output_tokens == 6
    assert diagnostics.tokens.total_tokens == 19
    assert diagnostics.tokens.cached_input_tokens == 2
    assert diagnostics.tokens.reasoning_output_tokens == 1
    assert diagnostics.token_usage_partial is False
    assert diagnostics.agents[0].agent == "advisor-match-graph"
    assert diagnostics.agents[0].tokens.total_tokens == 19


def test_repository_uses_separate_durable_database(settings) -> None:
    repository = AdvisorRepository(settings.advisor_repository_db)
    assert repository.path.name == "advisor_repository.sqlite3"
    repository.close()
    assert settings.advisor_repository_db.is_file()
