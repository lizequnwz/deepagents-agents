from __future__ import annotations

from streamlit.testing.v1 import AppTest
from data_analytics_agent.schemas import API_CONTRACT_VERSION

from data_analytics_agent.ui.components import (
    consolidate_activity_events,
    conversation_url,
    rows_to_csv,
    python_review_decision,
    sql_review_decision,
)
from data_analytics_agent.ui.api_client import (
    api_contract_error,
)


def test_conversation_url_replaces_existing_thread_and_preserves_query() -> None:
    url = conversation_url(
        "http://127.0.0.1:8501/?mode=review&thread_id=old",
        "new-thread",
    )
    assert url == ("http://127.0.0.1:8501/?mode=review&thread_id=new-thread")


def test_example_question_prefills_chat_input_without_submitting() -> None:
    app = AppTest.from_string(
        """
import streamlit as st
from data_analytics_agent.ui.components import render_empty_state

render_empty_state(
    "thread-1",
    {
        "examples": [{
            "label": "Compare regions",
            "question": "Which regions grew fastest?",
        }]
    },
    chat_input_key="chat_input_thread-1",
)
submitted = st.chat_input(
    "Ask a question",
    key="chat_input_thread-1",
)
if submitted:
    st.write(f"submitted: {submitted}")
"""
    ).run()

    app.pills[0].set_value(":material/lightbulb: Compare regions").run()

    assert app.chat_input[0].value == "Which regions grew fastest?"
    assert not any("submitted:" in item.value for item in app.markdown)

    app.chat_input[0].set_value("Which regions grew fastest last year?").run()

    assert any(
        "submitted: Which regions grew fastest last year?" in item.value
        for item in app.markdown
    )


def test_api_contract_mismatch_requires_service_restart() -> None:
    assert api_contract_error({"api_contract_version": API_CONTRACT_VERSION}) is None
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

    assert sql_review_decision(generated, generated) == {"action": "approve"}


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
            "label": "Loading skill · data-analysis",
            "phase": "started",
            "agent": "text-to-sql",
            "duration_ms": 250,
            "tool": {
                "call_id": "call-1",
                "name": "read_file",
                "input": {"file_path": "SKILL.md"},
                "output": None,
            },
        },
        {
            "id": 2,
            "kind": "skill",
            "label": "Loaded skill · data-analysis",
            "phase": "completed",
            "agent": "text-to-sql",
            "tool": {
                "call_id": "call-1",
                "name": "read_file",
                "input": None,
                "output": {"content": "skill text"},
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
                "input": {"file_path": "SCHEMA.md"},
                "output": None,
            },
        },
    ]

    consolidated = consolidate_activity_events(events)

    assert len(consolidated) == 2
    assert consolidated[0]["phase"] == "completed"
    assert consolidated[0]["label"] == "Loaded skill · data-analysis"
    assert consolidated[0]["tool"]["input"] == {"file_path": "SKILL.md"}
    assert consolidated[0]["tool"]["output"] == {"content": "skill text"}
    assert consolidated[0]["duration_ms"] == 250
    assert consolidated[1]["tool"]["call_id"] == "call-2"


def test_activity_renderer_shows_collapsed_tool_io_and_debug_state() -> None:
    app = AppTest.from_string(
        """
from data_analytics_agent.ui.components import render_activity_timeline

render_activity_timeline(
    [{
        "id": 1,
        "kind": "skill",
        "label": "Loaded skill · data-analysis",
        "phase": "completed",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "call-1",
            "name": "read_file",
            "input": {"file_path": "SKILL.md"},
            "output": {"content": "skill text"},
        },
    }, {
        "id": 2,
        "kind": "skill",
        "label": "Loading skill · schema-exploration",
        "phase": "started",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "call-2",
            "name": "read_file",
            "input": None,
            "output": None,
        },
    }, {
        "id": 3,
        "kind": "skill",
        "label": "Loaded skill · report-design",
        "phase": "completed",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "call-3",
            "name": "read_file",
            "input": {"file_path": "CHART.md"},
            "output": None,
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
"""
    ).run()

    assert not app.exception
    assert any(
        "Reference material loaded · Text-to-SQL" in caption.value
        for caption in app.caption
    )
    panels = app.get("status")
    assert [panel.label for panel in panels] == [
        "read_file · call 1",
        "read_file · call 2",
        "read_file · call 3",
        "Agent state (debug)",
    ]
    assert all(panel.proto.expanded is False for panel in panels)
    captions = [caption.value for caption in app.caption]
    assert any("Waiting for tool output" in value for value in captions)
    assert any("This tool call has no input" in value for value in captions)
    assert any("The tool returned no value" in value for value in captions)


def test_activity_renderer_omits_agent_state_when_not_supplied() -> None:
    app = AppTest.from_string(
        """
from data_analytics_agent.ui.components import render_activity_timeline

render_activity_timeline(
    [{
        "id": 1,
        "kind": "semantic",
        "label": "Searched the semantic model",
        "phase": "completed",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "call-1",
            "name": "get_semantic_context",
            "input": {"query": "Revenue"},
            "output": {"matches": []},
        },
    }],
    key_prefix="normal",
)
"""
    ).run()

    assert not app.exception
    assert [panel.label for panel in app.get("status")] == ["get_semantic_context"]


def test_run_diagnostics_renderer_shows_operational_summary() -> None:
    app = AppTest.from_string(
        """
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
"""
    ).run()

    assert not app.exception
    assert [metric.label for metric in app.metric] == [
        "Tokens",
        "Elapsed",
        "Active",
        "Approval wait",
    ]
    assert any("token total is partial" in caption.value for caption in app.caption)


def test_live_diagnostics_update_inside_one_persistent_expander() -> None:
    app = AppTest.from_string(
        """
import streamlit as st
from data_analytics_agent.ui.components import render_run_diagnostics_content

with st.expander("Run diagnostics", key="live_run"):
    slot = st.empty()

for total_tokens in (100, 125):
    slot.empty()
    with slot.container():
        render_run_diagnostics_content({
            "tokens": {"total_tokens": total_tokens},
        })
"""
    ).run()

    assert not app.exception
    assert [panel.label for panel in app.get("expander")] == ["Run diagnostics"]
    assert app.metric[0].value == "125"


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
    assert app.success[0].value == ("Revised SQL is ready for another review.")
    assert any(
        caption.value == "Your feedback: Let's make it top 10."
        for caption in app.caption
    )


def test_python_review_shows_complete_code_and_dataset_provenance() -> None:
    app = AppTest.from_string(
        """
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
"""
    ).run()

    assert not app.exception
    assert app.subheader[0].value == "Review Python before execution"
    assert app.text_area[0].value == (
        "analysis_outputs = {'Mean': float(df.value.mean())}"
    )
    assert any(
        "exact code that will execute" in caption.value for caption in app.caption
    )


def test_current_activity_prefers_leaf_and_preserves_report_failure():
    from data_analytics_agent.ui.components import current_activity

    events = [
        {
            "phase": "started",
            "label": "Delegating",
            "tool": {"call_id": "1", "name": "task"},
        },
        {
            "phase": "started",
            "tool": {
                "call_id": "2",
                "name": "execute_sql",
                "input": {"purpose": "Count artists"},
            },
        },
    ]
    assert current_activity(events) == "Retrieving data · Count artists"
    assert (
        current_activity(events, status="failed", findings=True)
        == "Findings saved · Report generation failed"
    )


def test_activity_disclosure_is_keyed_and_lazy():
    app = AppTest.from_string("""
from data_analytics_agent.ui.components import render_activity
render_activity([], {}, key="stable")
""").run()
    assert not app.exception
    assert [e.label for e in app.expander] == ["Activity"]


def test_subagent_activity_identifies_specialist_and_assignment():
    from data_analytics_agent.ui.components import activity_label, current_activity

    event = {
        "phase": "started",
        "label": "Task",
        "tool": {
            "call_id": "assignment",
            "name": "task",
            "input": {
                "subagent_type": "data-analysis",
                "description": "Forecast monthly sales with uncertainty.",
            },
        },
    }
    assert current_activity([event]) == (
        "Analyzing data · Forecast monthly sales with uncertainty."
    )
    assert "Finished" in activity_label({**event, "phase": "completed"})
    assert "Assignment failed" in activity_label({**event, "phase": "failed"})


def test_provenance_renders_python_sql_and_presentation_without_empty_code():
    app = AppTest.from_string("""
from data_analytics_agent.ui.components import render_dataset_provenance
base = {"source_id": "sales", "result_id": "derived", "parent_result_ids": ["input-1"]}
render_dataset_provenance({**base, "kind": "python", "execution_id": "exec-1"},
    executions={"exec-1": {"executed_python": "output = df.mean()"}})
render_dataset_provenance({**base, "kind": "saved_sql", "executed_sql": "SELECT SUM(value) FROM input"})
render_dataset_provenance({**base, "kind": "presentation"})
render_dataset_provenance({**base, "kind": "python", "execution_id": "unattached"})
""").run()
    assert not app.exception
    assert [code.value for code in app.code] == [
        "output = df.mean()",
        "SELECT SUM(value) FROM input",
    ]
    assert any("not attached" in item.value for item in app.caption)
    assert any("Based on" in item.value for item in app.markdown)


def test_answer_connects_python_evidence_to_executed_code():
    app = AppTest.from_string("""
from unittest.mock import patch
from data_analytics_agent.ui.components import render_answer
from data_analytics_agent.ui.api_client import AgentAPIClient
result = {
    "result_id": "forecast", "source_id": "sales", "kind": "python",
    "short_label": "Sales forecast", "originating_question": "Forecast sales",
    "parent_result_ids": ["monthly-sales"], "execution_id": "exec-1",
    "executed_sql": "", "rows": [{"forecast": 42}], "columns": ["forecast"],
    "row_count": 1, "elapsed_ms": 2, "truncated": False,
}
with patch("data_analytics_agent.ui.components._saved_result", return_value=result):
    render_answer(AgentAPIClient("http://localhost:8000"), {
        "answer": "Forecast ready", "results": [{"result_id": "forecast"}],
        "analyses": [{"executions": [{"execution_id": "exec-1",
            "executed_python": "forecast = model.predict()"}]}],
    }, turn_key="test", source_id="sales")
""").run()
    assert not app.exception
    assert any(
        "Sales forecast · Python-derived dataset" in panel.label for panel in app.status
    )
    assert all(code.value for code in app.code)
    assert app.code[-1].value == "forecast = model.predict()"


def test_status_does_not_reuse_retrieval_phase_and_prioritizes_wait_states():
    from data_analytics_agent.ui.components import current_activity, activity_label

    event = {
        "phase": "completed",
        "agent": "text-to-sql",
        "tool": {
            "call_id": "sql",
            "name": "execute_sql",
            "input": {"purpose": "Count artists"},
        },
    }
    assert current_activity([event]) == "Preparing next step"
    assert (
        current_activity([event], active_model_agent="text-to-sql")
        == "Reviewing retrieved data · Count artists"
    )
    for findings in (False, True):
        assert (
            current_activity(
                [event],
                findings=findings,
                status="approval_required",
                approval={"review_type": "python"},
            )
            == "Waiting for Python review"
        )
        assert current_activity([event], findings=findings, status="paused") == "Paused"
        assert (
            current_activity(
                [event], findings=findings, status="clarification_required"
            )
            == "Waiting for your clarification"
        )
    assert current_activity([], findings=True) == "Findings saved · Preparing report"
    assert activity_label(event) == "SQL query finished · Count artists"
    assert (
        activity_label({**event, "phase": "failed"})
        == "SQL query failed · Count artists"
    )
    assert (
        current_activity([{**event, "phase": "started"}], source_id="Chinook")
        == "Retrieving data from Chinook · Count artists"
    )


def test_chart_data_inspector_navigates_to_parent_sql():
    app = AppTest.from_string("""
from unittest.mock import patch
from data_analytics_agent.ui.components import _dataset_inspector
from data_analytics_agent.ui.api_client import AgentAPIClient
base = {"source_id": "sales", "rows": [{"value": 42}], "columns": ["value"],
        "row_count": 1, "truncated": False, "execution_id": None}
items = {
    "chart": {**base, "result_id": "chart", "kind": "presentation", "short_label": "Chart data", "parent_result_ids": ["sql"]},
    "sql": {**base, "result_id": "sql", "kind": "source_sql", "short_label": "Revenue by genre", "parent_result_ids": [], "executed_sql": "SELECT value FROM sales"},
}
with patch("data_analytics_agent.ui.components._saved_result", side_effect=lambda url, key, limit: items[key]):
    _dataset_inspector(AgentAPIClient("http://localhost:8000"), "chart", {})
""").run()
    assert not app.exception
    assert "Revenue by genre · Source SQL" in app.selectbox[0].options
    app.selectbox[0].set_value("sql").run()
    assert not app.exception
    # Streamlit exposes segmented_control through the button_group test element.
    app.get("button_group")[0].set_value("Source").run()
    assert not app.exception
    assert app.code[0].value == "SELECT value FROM sales"


def test_shared_chart_dataset_has_one_evidence_panel():
    app = AppTest.from_string("""
from unittest.mock import patch
from data_analytics_agent.ui.components import render_answer
from data_analytics_agent.ui.api_client import AgentAPIClient
result = {"result_id": "data", "source_id": "sales", "kind": "source_sql", "short_label": "Revenue",
    "columns": [], "rows": [], "row_count": 0, "elapsed_ms": 1, "truncated": False,
    "parent_result_ids": [], "executed_sql": "SELECT revenue FROM sales"}
with patch("data_analytics_agent.ui.components._saved_result", return_value=result):
    render_answer(AgentAPIClient("http://localhost:8000"), {
        "answer": "Ready", "charts": [{"result_id": "data"}, {"result_id": "data"}],
        "results": [{"result_id": "data"}, {"result_id": "data"}],
    }, turn_key="shared", source_id="sales")
""").run()
    assert not app.exception
    panels = [panel for panel in app.status if "Data and provenance" in panel.label]
    assert len(panels) == 1


def test_ready_report_does_not_show_generation_in_progress():
    from data_analytics_agent.ui.components import current_activity

    assert (
        current_activity([], findings=True, report_ready=True)
        == "Findings saved · Finalizing answer"
    )
    assert (
        current_activity([], findings=True, report_ready=True, status="failed")
        == "Report ready · Finalizing answer failed"
    )


def test_model_status_keeps_assignment_and_completed_tool_context():
    from data_analytics_agent.ui.components import current_activity

    assignment = {
        "agent": "coordinator",
        "phase": "started",
        "tool": {
            "name": "task",
            "call_id": "assignment",
            "input": {
                "subagent_type": "data-analysis",
                "description": "Forecast monthly sales",
            },
        },
    }
    events = [assignment]
    assert current_activity(events, active_model_agent="data-analysis") == (
        "Planning analysis · Forecast monthly sales"
    )
    events += [
        {
            "agent": "data-analysis",
            "phase": "started",
            "tool": {
                "name": "execute_analysis_python",
                "call_id": "python",
                "input": {"purpose": "Evaluate forecast uncertainty"},
            },
        },
        {
            "agent": "data-analysis",
            "phase": "completed",
            "tool": {
                "name": "execute_analysis_python",
                "call_id": "python",
                "output": {"ok": True},
            },
        },
    ]
    assert current_activity(events, active_model_agent="data-analysis") == (
        "Reviewing analysis results · Evaluate forecast uncertainty"
    )
    events.append(
        {
            "agent": "coordinator",
            "phase": "completed",
            "tool": {"name": "task", "call_id": "assignment", "output": {"ok": True}},
        }
    )
    assert current_activity(events, active_model_agent="coordinator") == (
        "Reviewing findings · Forecast monthly sales"
    )
    events.append(
        {
            **assignment,
            "tool": {
                **assignment["tool"],
                "call_id": "new-assignment",
                "input": {
                    "subagent_type": "data-analysis",
                    "description": "Check regional differences",
                },
            },
        }
    )
    assert current_activity(events, active_model_agent="data-analysis") == (
        "Planning analysis · Check regional differences"
    )


def test_model_status_uses_completion_order_and_reports_failed_tools():
    from data_analytics_agent.ui.components import current_activity

    def event(call, phase, purpose=None):
        return {
            "agent": "text-to-sql",
            "phase": phase,
            "tool": {
                "name": "execute_sql",
                "call_id": call,
                "input": {"purpose": purpose} if purpose else None,
            },
        }

    events = [
        event("first", "started", "Revenue"),
        event("second", "started", "Units"),
        event("second", "completed"),
        event("first", "completed"),
    ]
    assert (
        current_activity(events, active_model_agent="text-to-sql")
        == "Reviewing retrieved data · Revenue"
    )
    events[-1] = event("first", "failed")
    assert "Responding to error · SQL query failed · Revenue" in current_activity(
        events, active_model_agent="text-to-sql"
    )


def test_answer_currency_is_literal_markdown_in_all_prose_fields():
    app = AppTest.from_string(r"""
from data_analytics_agent.ui.components import render_answer
render_answer(None, {
    "answer": "**Revenue** was $138.60 versus $105.93; already escaped \\$81.59.",
    "assumptions": ["Use $10 and $20 as thresholds."],
    "interpretation": "The gap is $32.67, above $30.",
}, turn_key="currency", source_id="test")
""").run()
    assert not app.exception
    text = "\n".join(item.value for item in app.markdown)
    assert r"**Revenue** was \$138.60 versus \$105.93; already escaped \$81.59." in text
    assert r"Use \$10 and \$20 as thresholds." in text
    assert r"The gap is \$32.67, above \$30." in text


def test_main_evidence_preview_is_ten_rows_without_changing_saved_data():
    app = AppTest.from_string("""
from data_analytics_agent.ui.components import _render_dataset_table
from data_analytics_agent.ui.api_client import AgentAPIClient
result = {"result_id": "sample", "rows": [{"value": n} for n in range(60)],
          "columns": ["value"], "row_count": 60}
_render_dataset_table(AgentAPIClient("http://localhost:8000"), result)
assert len(result["rows"]) == 60
""").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 10
    assert any(item.value == "Preview: 10 of 60 saved rows." for item in app.caption)


def test_reused_chart_forms_are_scoped_to_turn_and_report():
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.components import _render_chart_editor
class Client:
    def edit_chart(self, run_id, payload):
        st.session_state.saved = (run_id, payload)
chart = {"chart_id": "shared", "title": "Revenue", "chart_type": "line"}
for run, report in [("first", "report-1"), ("second", "report-1"), ("second", "report-2")]:
    _render_chart_editor(Client(), run, {"report_id": report}, chart)
""").run()
    assert not app.exception
    assert len(app.button) == 3
    app.text_input[6].set_value("Revised revenue")
    app.button[2].click().run()
    assert not app.exception
    run_id, payload = app.session_state.saved
    assert run_id == "second" and payload["report_id"] == "report-2"
    assert payload["title"] == "Revised revenue" and payload["chart_id"] == "shared"


def test_assumptions_collapse_but_partial_and_analysis_warnings_stay_visible():
    app = AppTest.from_string("""
from data_analytics_agent.ui.components import render_answer
render_answer(None, {"answer":"Estimate", "assumptions":["Stable demand"],
    "interpretation":"Uncertain", "partial":True,
    "unresolved_questions":["Validate forecast"],
    "analyses":[{"warnings":["Only six observations"], "executions":[]}]},
    turn_key="test", source_id="test")
""").run()
    assert not app.exception
    assert (
        next(
            e for e in app.expander if e.label == "Assumptions and interpretation"
        ).proto.expanded
        is False
    )
    assert any("Partial findings" in w.value for w in app.warning)
    assert any("Only six observations" in w.value for w in app.warning)


def test_plan_and_parallel_status_without_duplicate_work_progress():
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.components import render_activity, current_activity
steps=[{"agent":"coordinator", "phase":"completed", "tool":{"name":"write_todos","call_id":"plan","input":{"todos":[
    {"content":"Retrieve monthly data","status":"completed"},
    {"content":"Compare trend and seasonality","status":"in_progress"},
    {"content":"Prepare report","status":"pending"}]}}},
    {"agent":"coordinator","phase":"started","tool":{"name":"task","call_id":"same","invocation_id":"a","input":{"subagent_type":"data-analysis","description":"Investigate trend. Business brief: use 12345678-1234-1234-1234-123456789abc"}}},
    {"agent":"coordinator","phase":"started","tool":{"name":"task","call_id":"same","invocation_id":"b","input":{"subagent_type":"data-analysis","description":"Investigate seasonality"}}}]
st.markdown(current_activity(steps))
render_activity(steps,{},key="work")
""").run()
    assert not app.exception
    assert any("Analysis plan" in m.value for m in app.markdown)
    assert any("Retrieve monthly data" in m.value for m in app.markdown)
    assert any("2 analyses running" in m.value for m in app.markdown)
    assert not any("Work progress" in m.value for m in app.markdown)
    assert not app.caption
    assert app.expander[0].proto.expanded is False
    assert not any("Business brief" in c.value for c in app.caption)


def test_completed_plan_collapses_and_preserves_steps_and_activity_state():
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.components import render_activity
st.session_state.setdefault("finished", False)
st.session_state.setdefault("partial", False)
st.session_state.setdefault("step_status", "in_progress")
steps = [{"agent": "coordinator", "phase": "completed", "tool": {
    "name": "write_todos", "call_id": "plan", "input": {"todos": [
        {"content": "Compare regional sales", "status": st.session_state.step_status}
    ]}}}]
render_activity(steps, {}, key="test", completed=st.session_state.finished,
                partial=st.session_state.partial)
if st.session_state.finished:
    st.markdown("The answer stays visible.")
""").run()
    assert not app.exception
    assert any("**Compare regional sales**" in m.value for m in app.markdown)
    activity_id = app.expander[0].proto.id
    app.session_state["activity_turn_test"] = True
    app.session_state["finished"] = True
    app.session_state["step_status"] = "completed"
    app.run()
    assert not app.exception
    plan = next(e for e in app.expander if e.label == "Analysis complete · View steps")
    assert plan.proto.expanded is False
    assert not any("Compare regional sales" in m.value for m in app.markdown)
    assert any("The answer stays visible." in m.value for m in app.markdown)
    activity = next(e for e in app.expander if e.label == "Activity")
    assert activity.proto.id == activity_id and activity.proto.expanded
    app.session_state["completed_plan_test"] = True
    app.run()
    assert not app.exception
    assert any("Compare regional sales · completed" in m.value for m in app.markdown)
    # Published partial answers and unfinished plans must never claim completion.
    for partial, step_status in [(True, "completed"), (False, "pending")]:
        app.session_state["partial"] = partial
        app.session_state["step_status"] = step_status
        app.run()
        assert not app.exception
        assert any(e.label == "Analysis plan · View steps" for e in app.expander)
        assert not any(e.label.startswith("Analysis complete") for e in app.expander)
        app.session_state["completed_plan_test"] = True
        app.run()
        assert not app.exception
        assert any(
            f"Compare regional sales · {step_status}" in m.value for m in app.markdown
        )
