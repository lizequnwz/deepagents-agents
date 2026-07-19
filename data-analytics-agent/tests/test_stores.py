from __future__ import annotations

import pytest
from types import SimpleNamespace

from data_analytics_agent.agents.text_to_sql.tools import (
    create_inspect_conversation_result_tool,
    create_list_conversation_results_tool,
)
from data_analytics_agent.stores import ResultStore, StoreNotFound


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

    list_tool = create_list_conversation_results_tool(
        store, source_id="source-a"
    )
    listed = list_tool.func(runtime)
    assert listed["results"][0]["result_id"] == saved.result_id
    assert listed["results"][0]["originating_question"] == "Show every number"
    assert "rows" not in listed["results"][0]
    assert listed["results"][0]["profile"]["scope"] == "stored_rows"

    inspect_tool = create_inspect_conversation_result_tool(
        store,
        source_id="source-a",
        model_sample_rows=10,
    )
    inspected = inspect_tool.func(saved.result_id, runtime)
    assert len(inspected["sample_rows"]) == 10
    assert inspected["row_count"] == 25
    assert inspected["truncated"] is True
