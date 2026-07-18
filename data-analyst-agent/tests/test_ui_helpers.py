from __future__ import annotations

from streamlit.testing.v1 import AppTest

from text2sql_agent.ui.components import (
    conversation_url,
    rows_to_csv,
    sql_review_decision,
)


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


def test_unchanged_editor_contents_approve_generated_sql() -> None:
    generated = "SELECT Name FROM Artist LIMIT 5"

    assert sql_review_decision(generated, generated) == {
        "action": "approve"
    }


def test_any_exact_editor_change_submits_edited_sql() -> None:
    generated = "SELECT Name FROM Artist LIMIT 5"
    reviewed = f"{generated}\n"

    assert sql_review_decision(generated, reviewed) == {
        "action": "edit",
        "edited_sql": reviewed,
    }


def test_revised_sql_review_has_persistent_context() -> None:
    app = AppTest.from_string(
        """
from text2sql_agent.ui.components import render_approval

render_approval(
    {
        "run_id": "run-1",
        "next_event_id": 8,
        "approval": {"query": "SELECT 1 LIMIT 10"},
    },
    revision_feedback="Let's make it top 10.",
)
"""
    ).run()

    assert not app.exception
    assert app.success[0].value == (
        "Revised SQL is ready for another review."
    )
    assert any(
        caption.value == "Your feedback: Let's make it top 10."
        for caption in app.caption
    )


def test_reused_result_has_unique_widgets_in_each_turn() -> None:
    app = AppTest.from_string(
        """
from text2sql_agent.ui.components import render_turn

class Client:
    def get_result(self, _result_id):
        return {
            "result_id": "result-1",
            "executed_sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "row_count": 1,
            "truncated": False,
            "elapsed_ms": 1.0,
        }

turn = {
    "user_message": "Show the saved result",
    "answer": {
        "answer": "One row.",
        "result_id": "result-1",
        "sql": "SELECT 1",
        "assumptions": [],
        "interpretation": "",
    },
    "activities": [],
}
render_turn(Client(), turn, turn_key="turn-1")
render_turn(Client(), turn, turn_key="turn-2")
"""
    ).run()

    assert not app.exception
    assert len(app.get("download_button")) == 2
