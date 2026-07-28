from __future__ import annotations

from streamlit.testing.v1 import AppTest

from data_analytics_agent.ui.components import (
    consolidate_activity_events,
    conversation_url,
    rows_to_csv,
    python_review_decision,
    sql_review_decision,
)
from data_analytics_agent.ui.api_client import (
    AgentAPIClient,
    api_contract_error,
)


def test_conversation_url_replaces_existing_thread_and_preserves_query() -> None:
    url = conversation_url(
        "http://127.0.0.1:8501/?mode=review&thread_id=old",
        "new-thread",
    )
    assert url == (
        "http://127.0.0.1:8501/?mode=review&thread_id=new-thread"
    )


def test_api_contract_mismatch_requires_service_restart() -> None:
    assert api_contract_error({"api_contract_version": 5}) is None
    missing = api_contract_error({})
    stale = api_contract_error({"api_contract_version": 2})

    assert missing is not None
    assert "contract missing" in missing
    assert stale is not None
    assert "contract 2" in stale
    assert "restart `./scripts/start.sh`" in stale

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


def test_any_exact_python_editor_change_is_authoritative() -> None:
    generated = 'analysis_outputs = {"Mean": df.value.mean()}'
    reviewed = f"{generated}\n"

    assert python_review_decision(generated, reviewed) == {
        "action": "edit",
        "edited_python": reviewed,
    }


def test_tool_lifecycle_consolidation_preserves_details_and_repeated_calls() -> None:
    events = [
        {
            "id": 1,
            "kind": "skill",
            "label": "Loading skill · query-writing",
            "phase": "started",
            "agent": "text-to-sql",
            "duration_ms": 250,
            "tool": {
                "call_id": "call-1",
                "name": "read_file",
                "arguments": {"skill": "query-writing"},
                "debug_input": {"file_path": "SKILL.md"},
            },
        },
        {
            "id": 2,
            "kind": "skill",
            "label": "Loaded skill · query-writing",
            "phase": "completed",
            "agent": "text-to-sql",
            "tool": {
                "call_id": "call-1",
                "name": "read_file",
                "arguments": {"skill": "query-writing"},
            },
        },
        {
            "id": 3,
            "kind": "skill",
            "label": "Loading skill · schema-exploration",
            "phase": "started",
            "agent": "text-to-sql",
            "tool": {
                "call_id": "call-2",
                "name": "read_file",
                "arguments": {"skill": "schema-exploration"},
            },
        },
    ]

    consolidated = consolidate_activity_events(events)

    assert len(consolidated) == 2
    assert consolidated[0]["phase"] == "completed"
    assert consolidated[0]["label"] == "Loaded skill · query-writing"
    assert consolidated[0]["tool"]["debug_input"] == {
        "file_path": "SKILL.md"
    }
    assert consolidated[0]["duration_ms"] == 250
    assert consolidated[1]["tool"]["call_id"] == "call-2"


def test_activity_renderer_shows_arguments_and_debug_state() -> None:
    app = AppTest.from_string(
        '''
from data_analytics_agent.ui.components import render_activity_timeline

render_activity_timeline(
    [{
        "id": 1,
        "kind": "skill",
        "label": "Loaded skill · query-writing",
        "phase": "completed",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "call-1",
            "name": "read_file",
            "arguments": {"skill": "query-writing"},
            "debug_input": {"file_path": "SKILL.md"},
        },
    }],
    debug_states=[{
        "agent": "text-to-sql",
        "namespace": ["text-to-sql:abc"],
        "captured_at": "2026-07-22T12:00:00Z",
        "state": {"todos": [{"content": "Write SQL"}]},
        "truncated": False,
        "omitted_items": 0,
        "omitted_messages": 0,
    }],
    key_prefix="test",
)
'''
    ).run()

    assert not app.exception
    assert any(
        "Loaded skill · query-writing · Text-to-SQL" in caption.value
        for caption in app.caption
    )
    assert [panel.label for panel in app.get("status")] == [
        "read_file",
        "Agent state (debug)",
    ]


def test_run_diagnostics_renderer_shows_operational_summary() -> None:
    app = AppTest.from_string(
        '''
from data_analytics_agent.ui.components import render_run_diagnostics

render_run_diagnostics({
    "tokens": {
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
    },
    "token_usage_partial": True,
    "model_calls": 2,
    "tool_calls": 1,
    "elapsed_ms": 2500,
    "active_ms": 2000,
    "approval_wait_ms": 500,
    "agents": [{
        "agent": "text-to-sql",
        "tokens": {"total_tokens": 125},
        "model_calls": 2,
        "model_ms": 1500,
        "max_model_call_ms": 900,
        "tool_calls": 1,
        "tool_ms": 300,
    }],
}, key="test")
'''
    ).run()

    assert not app.exception
    assert [metric.label for metric in app.metric] == [
        "Tokens",
        "Elapsed",
        "Active",
        "Approval wait",
    ]
    assert any(
        "token total is partial" in caption.value
        for caption in app.caption
    )


def test_api_client_fetches_every_result_page() -> None:
    class Client(AgentAPIClient):
        paths: list[str] = []

        def request(self, method, path, **kwargs):
            del method, kwargs
            self.paths.append(path)
            offset = int(path.split("offset=", 1)[1].split("&", 1)[0])
            all_rows = [{"value": value} for value in range(5)]
            return {
                "result_id": "result-1",
                "source_id": "test",
                "executed_sql": "SELECT value FROM numbers",
                "columns": ["value"],
                "rows": all_rows[offset : offset + 2],
                "profile": {"scope": "stored_rows"},
                "row_count": 5,
                "truncated": False,
                "elapsed_ms": 1,
                "offset": offset,
                "limit": 2,
            }

    client = Client("http://example.test")
    result = client.get_result("result-1", page_size=2)

    assert result["rows"] == [{"value": value} for value in range(5)]
    assert len(client.paths) == 3
def test_revised_sql_review_has_persistent_context() -> None:
    app = AppTest.from_string(
        """
from data_analytics_agent.ui.components import render_approval

render_approval(
    {
        "run_id": "run-1",
        "next_event_id": 8,
        "approval": {
            "query": "SELECT 1 LIMIT 10",
            "dialect": "sqlite",
            "timeout_seconds": 10,
            "max_result_rows": 500,
        },
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


def test_python_review_shows_complete_code_and_dataset_provenance() -> None:
    app = AppTest.from_string(
        '''
from data_analytics_agent.ui.components import render_approval

render_approval({
    "run_id": "run-python",
    "next_event_id": 12,
    "approval": {
        "review_type": "python",
        "query": "analysis_outputs = {'Mean': float(df.value.mean())}",
        "source_id": "test",
        "parent_result_id": "result-12345678",
        "originating_question": "Return all values",
        "executed_sql": "SELECT value FROM measurements",
        "columns": ["value"],
        "sample_rows": [{"value": 1}, {"value": 2}],
        "profile": {"scope": "stored_rows", "row_count": 2, "columns": []},
        "row_count": 2,
        "truncated": False,
        "timeout_seconds": 30,
    },
})
'''
    ).run()

    assert not app.exception
    assert app.subheader[0].value == "Review Python before execution"
    assert app.text_area[0].value == (
        "analysis_outputs = {'Mean': float(df.value.mean())}"
    )
    assert any(
        "exact code that will execute" in caption.value
        for caption in app.caption
    )


def test_completed_statistical_turn_renders_compact_outputs_and_code() -> None:
    app = AppTest.from_string(
        '''
from data_analytics_agent.ui.components import render_turn

class Client:
    def get_result(self, _result_id):
        return {
            "result_id": "result-1",
            "executed_sql": "SELECT value FROM measurements",
            "columns": ["value"],
            "rows": [{"value": 1}, {"value": 2}],
            "row_count": 2,
            "truncated": False,
            "elapsed_ms": 1.0,
        }

render_turn(
    Client(),
    {
        "user_message": "Estimate the mean",
        "answer": {
            "answer": "The estimated mean is 1.5.",
            "result_id": "result-1",
            "sql": "SELECT value FROM measurements",
            "assumptions": [],
            "interpretation": "",
            "statistical_analysis": {
                "outcome": "analysis_completed",
                "parent_result_id": "result-1",
                "executed_python": (
                    "analysis_outputs = {'Mean': float(df.value.mean())}"
                ),
                "answer": "The mean is 1.5.",
                "method": "Arithmetic mean with a 95% confidence target.",
                "assumptions": ["Two-sided alpha = 0.05."],
                "interpretation": "The sample center is 1.5.",
                "warnings": [
                    "The largest market has a small sample.",
                    "The largest market has a small sample.",
                    "Treat the comparison as exploratory.",
                ],
                "outputs": [{"name": "Mean", "kind": "scalar", "value": 1.5}],
            },
        },
        "activities": [],
    },
    turn_key="turn-statistics",
    source_id="test",
)
'''
    ).run()

    assert not app.exception
    assert any("Mean:** 1.5" in markdown.value for markdown in app.markdown)
    assert len(app.get("code")) == 2
    assert any(
        panel.label == "Statistical notes and limitations (2)"
        for panel in app.get("status")
    )
    assert not app.warning
    assert sum(
        "The largest market has a small sample." in markdown.value
        for markdown in app.markdown
    ) == 1


def test_reused_result_has_unique_widgets_in_each_turn() -> None:
    app = AppTest.from_string(
        """
from data_analytics_agent.ui.components import render_turn

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
render_turn(Client(), turn, turn_key="turn-1", source_id="test")
render_turn(Client(), turn, turn_key="turn-2", source_id="test")
"""
    ).run()

    assert not app.exception
    assert len(app.get("download_button")) == 2


def test_completed_chart_turn_renders_plotly_and_underlying_data() -> None:
    app = AppTest.from_string(
        """
from data_analytics_agent.ui.components import render_turn

class Client:
    def get_result(self, _result_id):
        return {
            "result_id": "result-1",
            "executed_sql": "SELECT category, amount FROM metrics",
            "columns": ["category", "amount"],
            "rows": [{"category": "A", "amount": 10}],
            "row_count": 1,
            "truncated": False,
            "elapsed_ms": 1.0,
        }

render_turn(
    Client(),
    {
        "user_message": "Chart it",
        "answer": {
            "answer": "One chart.",
            "result_id": "result-1",
            "sql": "SELECT category, amount FROM metrics",
            "assumptions": [],
            "interpretation": "",
            "chart": {
                "result_id": "result-1",
                "chart_type": "bar",
                "title": "Amount",
                "x": "category",
                "y": ["amount"],
            },
        },
        "activities": [],
    },
    turn_key="turn-chart",
    source_id="test",
)
"""
    ).run()

    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert len(app.get("download_button")) == 1
