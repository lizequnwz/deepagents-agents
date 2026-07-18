from __future__ import annotations

import pytest

from text2sql_agent.stores import ResultStore, StoreNotFound


def test_result_pagination_and_thread_isolation() -> None:
    store = ResultStore()
    saved = store.save(
        thread_id="thread-a",
        executed_sql="SELECT value FROM numbers",
        columns=["value"],
        rows=[{"value": index} for index in range(25)],
        truncated=False,
        elapsed_ms=1.5,
    )
    page = store.page(
        saved.result_id, "thread-a", offset=10, limit=10
    )
    assert [row["value"] for row in page.rows] == list(range(10, 20))
    assert page.row_count == 25
    with pytest.raises(StoreNotFound):
        store.get(saved.result_id, "thread-b")


def test_result_ids_are_unique() -> None:
    store = ResultStore()
    first = store.save(
        thread_id="t",
        executed_sql="SELECT 1",
        columns=["value"],
        rows=[{"value": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    second = store.save(
        thread_id="t",
        executed_sql="SELECT 2",
        columns=["value"],
        rows=[{"value": 2}],
        truncated=False,
        elapsed_ms=1,
    )
    assert first.result_id != second.result_id
