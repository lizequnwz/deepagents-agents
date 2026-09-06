"""Streamlit chat UI for the local Data Analytics Agent API."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from data_analytics_agent.ui.api_client import (
    APIError,
    AgentAPIClient,
    api_contract_error,
)
from data_analytics_agent.ui.components import (
    clear_artifact_cache,
    render_activity_timeline,
    render_activity_summary,
    render_approval,
    render_empty_state,
    render_page_header,
    render_pending_user_message,
    render_run_diagnostics,
    render_run_diagnostics_content,
    render_sidebar,
    render_turn,
)

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8501").rstrip("/")

st.set_page_config(
    page_title="Data Analytics Agent",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def initialize_session_state() -> None:
    st.session_state.setdefault("active_run_id", None)
    st.session_state.setdefault("last_run_error", None)
    st.session_state.setdefault("last_run_diagnostics", None)
    st.session_state.setdefault("last_run_activities", None)
    st.session_state.setdefault("last_run_debug_states", None)
    st.session_state.setdefault("last_run_metrics", None)
    st.session_state.setdefault("conversation_notice", None)
    st.session_state.setdefault("review_notice", None)
    st.session_state.setdefault("source_selector", None)
    st.session_state.setdefault("current_thread_id", None)


def clear_conversation_state() -> None:
    """Clear per-conversation widget and polling state."""

    removable_prefixes = (
        "event_cursor_",
        "event_activities_",
        "debug_states_",
        "sql_review_",
        "python_review_",
        "rejection_feedback_",
        "review_feedback_",
        "review_phase_",
        "starter_question_",
        "chat_input_",
    )
    for key in list(st.session_state):
        if key.startswith(removable_prefixes):
            del st.session_state[key]
    st.session_state["active_run_id"] = None
    st.session_state["last_run_error"] = None
    st.session_state["last_run_diagnostics"] = None
    st.session_state["last_run_activities"] = None
    st.session_state["last_run_debug_states"] = None
    st.session_state["last_run_metrics"] = None
    st.session_state["review_notice"] = None


def create_conversation(
    client: AgentAPIClient,
    source_id: str,
    *,
    sync_source_selector: bool = True,
) -> str:
    thread_id = client.create_conversation(source_id)
    clear_conversation_state()
    st.query_params["thread_id"] = thread_id
    st.session_state["current_thread_id"] = thread_id
    if sync_source_selector:
        st.session_state["source_selector"] = source_id
    return thread_id


def get_or_create_conversation(
    client: AgentAPIClient,
    *,
    default_source_id: str,
    ready_source_ids: set[str],
) -> tuple[str, dict[str, Any]]:
    thread_id = st.query_params.get("thread_id")
    if thread_id:
        try:
            thread_id = str(thread_id)
            conversation = client.get_conversation(thread_id)
            if st.session_state.get("current_thread_id") != thread_id:
                st.session_state["current_thread_id"] = thread_id
                st.session_state["source_selector"] = conversation["source_id"]
            elif (
                st.session_state.get("source_selector")
                and st.session_state["source_selector"] != conversation["source_id"]
            ):
                switched_source = st.session_state["source_selector"]
                new_thread_id = create_conversation(
                    client,
                    switched_source,
                )
                st.session_state["conversation_notice"] = (
                    "The data source changed, so a new conversation was started."
                )
                return (
                    new_thread_id,
                    client.get_conversation(new_thread_id),
                )
            return thread_id, conversation
        except APIError as exc:
            if exc.status_code != 404:
                raise
            st.query_params.pop("thread_id", None)
            st.session_state["conversation_notice"] = (
                "The previous local conversation is no longer available. "
                "A new conversation was started."
            )

    selected_source = st.session_state.get("source_selector")
    if selected_source not in ready_source_ids:
        selected_source = default_source_id
    thread_id = create_conversation(client, selected_source)
    return thread_id, client.get_conversation(thread_id)


def request_history_deletion(target: str) -> None:
    st.session_state.pop("history_deletion_error", None)
    st.session_state["history_deletion"] = target
    st.session_state["history_deletion_scope"] = "This conversation"


def cancel_history_deletion() -> None:
    st.session_state.pop("history_deletion", None)


def confirm_history_deletion(client: AgentAPIClient, target: str) -> None:
    try:
        if target == "all":
            client.clear_history()
        else:
            client.delete_conversation(target)
        st.session_state.pop("history_deletion", None)
        st.session_state.pop("history_deletion_error", None)
        clear_artifact_cache()
        clear_conversation_state()
        st.query_params.pop("thread_id", None)
        st.session_state["current_thread_id"] = None
        st.session_state["conversation_notice"] = (
            "History deleted. A new empty conversation is ready."
        )
    except APIError as exc:
        st.session_state["history_deletion_error"] = str(exc)


def clear_completed_run(run_id: str) -> None:
    st.session_state["active_run_id"] = None
    st.session_state.pop(f"event_cursor_{run_id}", None)
    st.session_state.pop(f"event_activities_{run_id}", None)
    st.session_state.pop(f"debug_states_{run_id}", None)
    st.session_state.pop(f"review_feedback_{run_id}", None)
    st.session_state.pop(f"review_phase_{run_id}", None)


def render_execution_diagnostics(diagnostics: dict[str, Any]) -> None:
    """Render bounded diagnostics for an execution-budget failure."""

    with st.expander("Execution diagnostics", expanded=False):
        safe_details = {
            key: value
            for key, value in diagnostics.items()
            if key != "recent_tool_calls"
        }
        st.json(safe_details)
        recent = diagnostics.get("recent_tool_calls") or []
        if recent:
            st.warning(
                "Debug details may contain sensitive business data. "
                "Credentials and recognized secrets are redacted."
            )
            st.json(recent)


@st.fragment(run_every="1s")
def render_active_run(
    client: AgentAPIClient, run_id: str, thread_id: str, source_id: str
):
    try:
        run = client.get_run(run_id)
        state = run["status"]
        if state == "completed":
            clear_completed_run(run_id)
            st.rerun()
        phases = {
            "understanding": "Understanding",
            "retrieving_data": "Retrieving data",
            "analyzing": "Analyzing",
            "findings_ready": "Findings ready",
            "preparing_report": "Preparing report",
        }
        label = (
            "Stopping"
            if state == "stopping"
            else phases.get(run.get("phase"), "Understanding")
        )
        if state in {"paused", "failed"}:
            label = f"{state.capitalize()} · {label}"
        st.markdown(f"**{label}**")
        render_activity_summary(run.get("events") or [])
        if run.get("findings"):
            render_turn(
                client,
                {"user_message": run["question"], "answer": run["findings"]},
                turn_key=f"pending_{run_id}",
                source_id=source_id,
            )
        else:
            render_pending_user_message(run["question"])
        if state in {"running", "queued", "approval_required"}:
            if st.button("Stop", key=f"stop_{run_id}"):
                client.stop_run(run_id)
                st.rerun()
        if state == "approval_required":
            decision = render_approval(run)
            if decision:
                client.submit_decision(run_id, decision)
                st.rerun()
        elif state in {"paused", "failed"}:
            # Re-run once to release the chat input after a stop.
            if st.session_state.get("active_run_id"):
                st.session_state["active_run_id"] = None
                st.rerun()
            if run.get("error"):
                st.error(run["error"])
            st.info(
                "Work is saved. Resume this investigation or send a correction below."
            )
            if st.button("Resume", key=f"resume_{run_id}"):
                client.resume_run(run_id)
                st.session_state["active_run_id"] = run_id
                st.rerun()
            if run.get("findings") and st.button(
                "Retry report", key=f"retry_report_{run_id}"
            ):
                client.retry_report(run_id)
                st.session_state["active_run_id"] = run_id
                st.rerun()
        with st.expander(
            "Execution details", expanded=False, key=f"execution_details_{run_id}"
        ):
            render_activity_timeline(
                run.get("events") or [], key_prefix=f"live_{run_id}"
            )
            with st.expander("Run diagnostics", expanded=False):
                render_run_diagnostics_content(
                    run.get("run_diagnostics") or {}, activities=run.get("events") or []
                )
    except APIError as exc:
        st.error(str(exc))


initialize_session_state()
client = AgentAPIClient(API_BASE_URL)

try:
    health = client.health()
    health_error = None
except APIError as exc:
    health = None
    health_error = str(exc)

if health is not None and (contract_error := api_contract_error(health)):
    render_page_header()
    st.error(contract_error, icon=":material/restart_alt:")
    st.caption("Saved conversations and artifacts will remain available after restart.")
    st.stop()

try:
    data_sources = client.get_data_sources()
except APIError as exc:
    render_page_header()
    st.error(str(exc), icon=":material/cloud_off:")
    st.caption(
        "Run `./scripts/start.sh` from the project directory, then refresh this page."
    )
    st.stop()

sources_by_id = {source["source_id"]: source for source in data_sources["sources"]}
ready_source_ids = {
    source_id for source_id, source in sources_by_id.items() if source["ready"]
}
if not ready_source_ids:
    render_page_header()
    st.error(
        "No configured data source is ready.",
        icon=":material/database_off:",
    )
    for source in data_sources["sources"]:
        for error in source.get("errors", []):
            st.caption(f"{source['name']}: {error}")
    st.stop()

default_source_id = data_sources["default_source_id"]
if default_source_id not in ready_source_ids:
    default_source_id = next(iter(ready_source_ids))

try:
    thread_id, conversation = get_or_create_conversation(
        client,
        default_source_id=default_source_id,
        ready_source_ids=ready_source_ids,
    )
except APIError as exc:
    render_page_header()
    st.error(str(exc), icon=":material/cloud_off:")
    st.stop()

source = sources_by_id[conversation["source_id"]]
active_run_id = conversation.get("active_run_id") or st.session_state.get(
    "active_run_id"
)

new_conversation, conversation_diagnostics_slot = render_sidebar(
    thread_id=thread_id,
    app_base_url=APP_BASE_URL,
    health=health,
    health_error=health_error,
    data_sources=data_sources,
    source_switch_disabled=bool(active_run_id),
    diagnostics=conversation.get("diagnostics") or {},
)
if new_conversation:
    try:
        # The selector widget already exists on this run. Its value is already
        # the conversation's source, so do not mutate the widget-backed key.
        create_conversation(
            client,
            conversation["source_id"],
            sync_source_selector=False,
        )
        st.rerun()
    except APIError as exc:
        st.sidebar.error(str(exc), icon=":material/error:")

with st.sidebar:
    with st.expander("Saved conversations", expanded=True):
        for saved in reversed(client.list_conversations()):
            if st.button(
                saved["title"],
                key=f"saved_{saved['thread_id']}",
                disabled=saved["thread_id"] == thread_id,
            ):
                clear_conversation_state()
                st.query_params["thread_id"] = saved["thread_id"]
                st.session_state["current_thread_id"] = None
                st.rerun()

    with st.expander("Manage history", expanded=False):
        st.button(
            "Delete history",
            key=f"delete_{thread_id}",
            disabled=bool(active_run_id),
            on_click=request_history_deletion,
            args=(thread_id,),
        )
        if active_run_id:
            st.caption("Stop active work before deleting its conversation.")
        pending = st.session_state.get("history_deletion")
        if pending and pending != thread_id:
            st.session_state.pop("history_deletion", None)
            pending = None
        if pending:
            selected_scope = st.radio(
                "Delete which history?",
                ["This conversation", "All conversations"],
                key="history_deletion_scope",
            )
            target = "all" if selected_scope == "All conversations" else pending
            scope = (
                "all saved conversations" if target == "all" else "this conversation"
            )
            st.warning(
                f"Permanently delete {scope}, including datasets, Python code and outputs, charts, reports, and pending approvals? This cannot be undone."
            )
            st.button(
                "Confirm deletion",
                key=f"confirm_delete_{target}",
                type="primary",
                on_click=confirm_history_deletion,
                args=(client, target),
            )
            if st.session_state.get("history_deletion_error"):
                st.error(st.session_state["history_deletion_error"])
            st.button(
                "Cancel",
                key="cancel_history_deletion",
                on_click=cancel_history_deletion,
            )

render_page_header(source)

if st.session_state.get("conversation_notice"):
    st.toast(
        st.session_state.pop("conversation_notice"),
        icon=":material/info:",
    )

if st.session_state.get("review_notice"):
    st.toast(
        st.session_state.pop("review_notice"),
        icon=":material/info:",
    )

for turn_index, completed_turn in enumerate(conversation["turns"]):
    render_turn(
        client,
        completed_turn,
        turn_key=f"{thread_id}_{turn_index}",
        source_id=conversation["source_id"],
    )

if st.session_state.get("last_run_error"):
    st.error(
        st.session_state["last_run_error"],
        icon=":material/error:",
    )
    if st.session_state.get("last_run_diagnostics"):
        render_execution_diagnostics(st.session_state["last_run_diagnostics"])
    failed_activities = st.session_state.get("last_run_activities") or []
    failed_debug_states = st.session_state.get("last_run_debug_states") or []
    if failed_activities or failed_debug_states:
        with st.status(
            "How this run progressed",
            expanded=False,
            state="error",
        ):
            render_activity_timeline(
                failed_activities,
                debug_states=failed_debug_states,
                key_prefix="last_failed_run",
            )
    if st.session_state.get("last_run_metrics"):
        render_run_diagnostics(
            st.session_state["last_run_metrics"],
            key="last_failed_run_metrics",
        )

latest_run_id = (conversation.get("run_ids") or [None])[-1]
if active_run_id:
    st.session_state["active_run_id"] = active_run_id
    render_active_run(client, active_run_id, thread_id, conversation["source_id"])
elif latest_run_id:
    latest_run = client.get_run(latest_run_id)
    if latest_run["status"] in {"paused", "failed"}:
        render_active_run(client, latest_run_id, thread_id, conversation["source_id"])

if not active_run_id:
    chat_input_key = f"chat_input_{thread_id}"
    if not conversation["turns"] and not conversation.get("run_ids"):
        render_empty_state(
            thread_id,
            source,
            chat_input_key=chat_input_key,
        )

    typed_question = st.chat_input(
        f"Ask a business question about {source['name']}",
        key=chat_input_key,
        submit_mode="disable",
    )
    if typed_question:
        try:
            st.session_state["last_run_error"] = None
            st.session_state["last_run_diagnostics"] = None
            st.session_state["last_run_activities"] = None
            st.session_state["last_run_debug_states"] = None
            st.session_state["last_run_metrics"] = None
            run = client.send_message(thread_id, typed_question)
            st.session_state["active_run_id"] = run["run_id"]
            st.rerun()
        except APIError as exc:
            st.error(str(exc), icon=":material/error:")
