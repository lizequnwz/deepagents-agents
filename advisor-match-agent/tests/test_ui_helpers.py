from __future__ import annotations

from general_agent.ui import components
from general_agent.ui.components import _markdown_text, reduce_live_events


def test_event_reduction_ignores_model_text_and_tracks_event_lifecycle() -> None:
    state = {}
    reduce_live_events(
        state,
        [
            {"id": 1, "kind": "assistant_delta", "data": {"text": "Hel"}},
            {"id": 2, "kind": "assistant_delta", "data": {"text": "lo"}},
            {
                "id": 3,
                "kind": "plan_updated",
                "agent": "advisor-match-agent",
                "data": {"todos": [{"content": "Test", "status": "in_progress"}]},
            },
            {
                "id": 4,
                "kind": "tool_started",
                "phase": "started",
                "data": {"call_id": "c1", "tool_name": "list_advisor_match_results", "input": {"match_session_id": "ams_test"}},
            },
            {
                "id": 5,
                "kind": "tool_finished",
                "phase": "completed",
                "data": {"call_id": "c1", "output": "/workspace", "duration_ms": 8},
            },
        ],
    )
    assert "text" not in state
    assert state["todos"][0]["content"] == "Test"
    assert state["tools"]["c1"]["data"]["input"]["match_session_id"] == "ams_test"
    assert state["tools"]["c1"]["data"]["output"] == "/workspace"
    assert state["activities"].count(("tool", "c1")) == 1


def test_currency_markdown_does_not_turn_into_math() -> None:
    rendered = _markdown_text("Assets are **$28.2 million**; formula is $x+y$.")
    assert "**\\$28.2 million**" in rendered
    assert "$x+y$" in rendered


def test_tool_arguments_and_results_render_only_in_debug_mode(monkeypatch) -> None:
    rendered = []
    monkeypatch.setattr(components.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(components, "_render_tool", rendered.append)
    state = {
        "activities": [("tool", "c1")],
        "tools": {
            "c1": {
                "id": 1,
                "kind": "tool_finished",
                "phase": "completed",
                "label": "Completed tool · inspect_advisor_upload",
                "data": {
                    "call_id": "c1",
                    "tool_name": "inspect_advisor_upload",
                    "input": {"attachment_id": "att_test"},
                    "output": {"format": "csv"},
                },
            }
        },
    }

    components.render_activity_timeline(state)
    assert rendered == []

    components.render_activity_timeline(state, debug_mode=True)
    assert rendered == [state["tools"]["c1"]]
