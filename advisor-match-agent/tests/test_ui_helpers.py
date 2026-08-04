from __future__ import annotations

from general_agent.ui.components import _friendly_error, _markdown_text, reduce_live_events


def test_event_reduction_tracks_explicit_graph_events() -> None:
    state = {}
    reduce_live_events(
        state,
        [
            {"id": 1, "kind": "node_completed", "phase": "completed", "label": "Route"},
            {
                "id": 2,
                "kind": "clarification_required",
                "phase": "completed",
                "label": "Which sheet should I use?",
            },
        ],
    )
    assert [item[1]["kind"] for item in state["activities"]] == [
        "node_completed",
        "clarification_required",
    ]


def test_currency_markdown_does_not_turn_into_math() -> None:
    rendered = _markdown_text("Assets are **$28.2 million**; formula is $x+y$.")
    assert "**\\$28.2 million**" in rendered
    assert "$x+y$" in rendered


def test_generic_error_does_not_claim_hidden_details_are_openable() -> None:
    message = _friendly_error("provider exploded")
    assert "Open technical details" not in message
    assert "previous matching results were not changed" in message
