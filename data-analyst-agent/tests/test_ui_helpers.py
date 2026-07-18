from __future__ import annotations

from text2sql_agent.ui.components import conversation_url, rows_to_csv


def test_conversation_url_replaces_existing_thread_and_preserves_query() -> None:
    url = conversation_url(
        "http://127.0.0.1:8501/?mode=review&thread_id=old",
        "new-thread",
    )

    assert url == (
        "http://127.0.0.1:8501/?mode=review&thread_id=new-thread"
    )


def test_rows_to_csv_uses_declared_column_order_and_escaping() -> None:
    content = rows_to_csv(
        ["artist", "revenue"],
        [
            {"revenue": 12.5, "artist": "AC/DC"},
            {"artist": 'Miles, "Davis"', "revenue": 9.25},
        ],
    )

    assert content.splitlines() == [
        "artist,revenue",
        "AC/DC,12.5",
        '"Miles, ""Davis""",9.25',
    ]
