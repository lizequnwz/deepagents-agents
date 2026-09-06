from __future__ import annotations

import pytest
from types import SimpleNamespace

from data_analytics_agent.agents.text_to_sql.tools import (
    create_inspect_conversation_result_tool,
    create_list_conversation_results_tool,
)
from data_analytics_agent.schemas import ApprovalRequest, FinalAnswer
from data_analytics_agent.stores import ResultStore, RunStore, StoreNotFound


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_run_diagnostics_aggregate_tokens_agents_and_timing() -> None:
    clock = FakeClock()
    store = RunStore(clock=clock)
    run_id = store.create("thread-a", "source-a", "Question", model="test")

    clock.advance(1)
    store.start_active(run_id)
    clock.advance(1)
    store.start_model_call(run_id, "model-1", agent="text-to-sql")
    assert store.diagnostics(run_id).token_usage_partial is True

    clock.advance(2)
    store.finish_model_call(
        run_id,
        "model-1",
        usage={
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
            "input_token_details": {"cache_read": 40},
            "output_token_details": {"reasoning": 10},
        },
    )
    store.start_model_call(run_id, "model-2", agent="unknown")
    clock.advance(1)
    store.finish_model_call(run_id, "model-2", usage=None)
    store.start_tool_call(run_id, "tool-1", agent="text-to-sql")
    clock.advance(0.5)
    duration_ms = store.finish_tool_call(
        run_id,
        "tool-1",
        agent="text-to-sql",
        failed=False,
    )
    assert duration_ms == 500

    approval = ApprovalRequest(
        interrupt_id="review-1",
        action_name="execute_sql",
        query="SELECT 1",
        allowed_decisions=["approve"],
    )
    store.require_approval(run_id, approval)
    clock.advance(3)
    assert store.claim_approval(run_id, approval) == 3_000
    store.start_active(run_id)
    clock.advance(2)
    store.complete(run_id, FinalAnswer(answer="Done"))

    diagnostics = store.diagnostics(run_id)
    assert diagnostics.model == "test"
    assert diagnostics.tokens.model_dump() == {
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
        "cached_input_tokens": 40,
        "reasoning_output_tokens": 10,
    }
    assert diagnostics.token_usage_partial is True
    assert diagnostics.model_calls == 2
    assert diagnostics.model_calls_missing_usage == 1
    assert diagnostics.model_ms == 3_000
    assert diagnostics.max_model_call_ms == 2_000
    assert diagnostics.tool_calls == 1
    assert diagnostics.tool_ms == 500
    assert diagnostics.elapsed_ms == 10_500
    assert diagnostics.active_ms == 6_500
    assert diagnostics.approval_wait_ms == 3_000
    assert [agent.agent for agent in diagnostics.agents] == [
        "text-to-sql",
        "unknown",
    ]

    conversation = store.conversation_diagnostics([run_id, "missing"])
    assert conversation.run_count == 1
    assert conversation.tokens.total_tokens == 125
    assert conversation.elapsed_ms == 10_500
    assert conversation.has_active_run is False


def test_result_pagination_and_thread_isolation() -> None:
    store = ResultStore()
    saved = store.save(
        thread_id="thread-a",
        source_id="source-a",
        executed_sql="SELECT value FROM numbers",
        columns=["value"],
        rows=[{"value": index} for index in range(25)],
        truncated=False,
        elapsed_ms=1.5,
    )
    page = store.page(
        saved.result_id,
        "thread-a",
        source_id="source-a",
        offset=10,
        limit=10,
    )
    assert [row["value"] for row in page.rows] == list(range(10, 20))
    assert page.row_count == 25
    with pytest.raises(StoreNotFound):
        store.get(saved.result_id, "thread-b")
    with pytest.raises(StoreNotFound):
        store.get(
            saved.result_id,
            "thread-a",
            source_id="source-b",
        )


def test_result_ids_are_unique() -> None:
    store = ResultStore()
    first = store.save(
        thread_id="t",
        source_id="source",
        executed_sql="SELECT 1",
        columns=["value"],
        rows=[{"value": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    second = store.save(
        thread_id="t",
        source_id="source",
        executed_sql="SELECT 2",
        columns=["value"],
        rows=[{"value": 2}],
        truncated=False,
        elapsed_ms=1,
    )
    assert first.result_id != second.result_id


def test_agent_result_discovery_exposes_profiles_and_only_head_ten() -> None:
    store = ResultStore()
    saved = store.save(
        thread_id="thread-a",
        source_id="source-a",
        executed_sql="SELECT value FROM numbers",
        columns=["value"],
        rows=[{"value": index} for index in range(25)],
        truncated=True,
        elapsed_ms=1,
        originating_question="Show every number",
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-a",
            "run_id": "run-a",
            "source_id": "source-a",
            "question": "Inspect it",
        }
    )

    list_tool = create_list_conversation_results_tool(store, source_id="source-a")
    listed = list_tool.func(runtime)
    assert listed["results"][0]["result_id"] == saved.result_id
    assert listed["results"][0]["purpose"] == "Show every number"
    assert "rows" not in listed["results"][0]

    inspect_tool = create_inspect_conversation_result_tool(
        store,
        source_id="source-a",
        model_sample_rows=10,
    )
    inspected = inspect_tool.func(saved.result_id, runtime)
    assert len(inspected["sample_rows"]) == 10
    assert inspected["row_count"] == 25
    assert inspected["truncated"] is True
