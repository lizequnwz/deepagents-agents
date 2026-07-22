"""Streamlit chat UI for the local Data Analytics Agent API."""

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from data_analytics_agent.ui.api_client import APIError, AgentAPIClient
from data_analytics_agent.ui.components import (
    render_activity_timeline,
    render_approval,
    render_debug_states,
    render_empty_state,
    render_page_header,
    render_pending_user_message,
    render_sidebar,
    render_turn,
)

load_dotenv()
API_BASE_URL = os.getenv(
    "API_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")
APP_BASE_URL = os.getenv(
    "APP_BASE_URL", "http://127.0.0.1:8501"
).rstrip("/")

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
    st.session_state.setdefault("last_run_debug_states", None)
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
        "rejection_feedback_",
        "review_feedback_",
        "review_phase_",
        "starter_question_",
    )
    for key in list(st.session_state):
        if key.startswith(removable_prefixes):
            del st.session_state[key]
    st.session_state["active_run_id"] = None
    st.session_state["last_run_error"] = None
    st.session_state["last_run_diagnostics"] = None
    st.session_state["last_run_debug_states"] = None
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
                and st.session_state["source_selector"]
                != conversation["source_id"]
            ):
                switched_source = st.session_state["source_selector"]
                new_thread_id = create_conversation(
                    client,
                    switched_source,
                )
                st.session_state["conversation_notice"] = (
                    "The data source changed, so a new conversation was "
                    "started."
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


def poll_run(
    client: AgentAPIClient,
    run_id: str,
    initial_run: dict[str, Any],
) -> dict[str, Any]:
    cursor_key = f"event_cursor_{run_id}"
    activities_key = f"event_activities_{run_id}"
    debug_states_key = f"debug_states_{run_id}"
    cursor = int(st.session_state.get(cursor_key, 0))
    activities: list[dict[str, Any]] = st.session_state.setdefault(
        activities_key, []
    )
    debug_states: list[dict[str, Any]] = st.session_state.setdefault(
        debug_states_key, []
    )
    run = initial_run if cursor == 0 else client.get_run(
        run_id, after_event_id=cursor
    )
    review_phase = st.session_state.get(f"review_phase_{run_id}")
    status_by_phase = {
        "revising_sql": "Feedback sent—revising SQL…",
        "executing_sql": "Executing reviewed SQL…",
    }
    initial_status = status_by_phase.get(
        review_phase,
        "Agent is working…",
    )

    with st.status(
        initial_status,
        expanded=True,
        state="running",
    ) as status_panel:
        timeline_slot = st.empty()
        render_version = 0

        while True:
            timeline_changed = render_version == 0
            for event in run["events"]:
                activities.append(event)
                timeline_changed = True
                status_panel.update(
                    label=event["label"], state="running", expanded=True
                )
            latest_debug_states = run.get("debug_states") or []
            if latest_debug_states != debug_states:
                debug_states[:] = latest_debug_states
                timeline_changed = True
            if timeline_changed:
                render_version += 1
                timeline_slot.empty()
                with timeline_slot.container():
                    render_activity_timeline(
                        activities,
                        debug_states=debug_states,
                        key_prefix=f"live_{run_id}_{render_version}",
                    )

            cursor = int(run["next_event_id"])
            st.session_state[cursor_key] = cursor
            state = run["status"]

            if state == "approval_required":
                revised = review_phase == "revising_sql"
                status_panel.update(
                    label=(
                        "Revised SQL is ready for review"
                        if revised
                        else "SQL is ready for review"
                    ),
                    state="complete",
                    expanded=False,
                )
                if revised:
                    st.session_state[
                        f"review_phase_{run_id}"
                    ] = "revision_ready"
                return run
            if state == "completed":
                status_panel.update(
                    label="Analysis complete",
                    state="complete",
                    expanded=False,
                )
                return run
            if state == "failed":
                status_panel.update(
                    label="Analysis failed",
                    state="error",
                    expanded=True,
                )
                return run

            time.sleep(0.6)
            run = client.get_run(run_id, after_event_id=cursor)


initialize_session_state()
client = AgentAPIClient(API_BASE_URL)

try:
    health = client.health()
    health_error = None
except APIError as exc:
    health = None
    health_error = str(exc)

try:
    data_sources = client.get_data_sources()
except APIError as exc:
    render_page_header()
    st.error(str(exc), icon=":material/cloud_off:")
    st.caption(
        "Run `./scripts/start.sh` from the project directory, then refresh "
        "this page."
    )
    st.stop()

sources_by_id = {
    source["source_id"]: source for source in data_sources["sources"]
}
ready_source_ids = {
    source_id
    for source_id, source in sources_by_id.items()
    if source["ready"]
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
active_run_id = (
    conversation.get("active_run_id")
    or st.session_state.get("active_run_id")
)

if render_sidebar(
    thread_id=thread_id,
    app_base_url=APP_BASE_URL,
    health=health,
    health_error=health_error,
    data_sources=data_sources,
    source_switch_disabled=bool(active_run_id),
):
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
        render_execution_diagnostics(
            st.session_state["last_run_diagnostics"]
        )
    if st.session_state.get("last_run_debug_states"):
        render_debug_states(
            st.session_state["last_run_debug_states"],
            key_prefix="last_failed_run",
        )

if active_run_id:
    st.session_state["active_run_id"] = active_run_id
    try:
        initial_run = client.get_run(active_run_id)
        render_pending_user_message(initial_run["question"])
        active_run = poll_run(client, active_run_id, initial_run)
    except APIError as exc:
        st.error(str(exc), icon=":material/error:")
        active_run = None

    if active_run and active_run["status"] == "approval_required":
        revision_feedback = (
            st.session_state.get(f"review_feedback_{active_run_id}")
            if st.session_state.get(f"review_phase_{active_run_id}")
            == "revision_ready"
            else None
        )
        decision = render_approval(
            active_run,
            revision_feedback=revision_feedback,
        )
        if decision:
            is_rejection = decision["action"] == "reject"
            spinner_text = (
                "Sending feedback to the analyst…"
                if is_rejection
                else "Submitting the reviewed SQL…"
            )
            status_text = (
                "Feedback sent—revising SQL."
                if is_rejection
                else "Executing reviewed SQL."
            )
            try:
                with st.spinner(spinner_text):
                    client.submit_decision(active_run_id, decision)
                st.session_state["active_run_id"] = active_run_id
                st.session_state["review_notice"] = status_text
                if is_rejection:
                    st.session_state[
                        f"review_feedback_{active_run_id}"
                    ] = decision["feedback"]
                    st.session_state[
                        f"review_phase_{active_run_id}"
                    ] = "revising_sql"
                else:
                    st.session_state.pop(
                        f"review_feedback_{active_run_id}",
                        None,
                    )
                    st.session_state[
                        f"review_phase_{active_run_id}"
                    ] = "executing_sql"
                st.rerun()
            except APIError as exc:
                st.error(str(exc), icon=":material/error:")
    elif active_run and active_run["status"] == "failed":
        st.session_state["last_run_error"] = (
            active_run.get("error") or "The agent run failed."
        )
        st.session_state["last_run_diagnostics"] = active_run.get(
            "diagnostics"
        )
        st.session_state["last_run_debug_states"] = active_run.get(
            "debug_states"
        )
        clear_completed_run(active_run_id)
        st.rerun()
    elif active_run and active_run["status"] == "completed":
        clear_completed_run(active_run_id)
        st.rerun()

if not active_run_id:
    starter_question = None
    if not conversation["turns"]:
        starter_question = render_empty_state(thread_id, source)

    typed_question = st.chat_input(
        f"Ask a business question about {source['name']}",
        submit_mode="disable",
    )
    question = starter_question or typed_question
    if question:
        try:
            st.session_state["last_run_error"] = None
            st.session_state["last_run_diagnostics"] = None
            st.session_state["last_run_debug_states"] = None
            run = client.send_message(thread_id, question)
            st.session_state["active_run_id"] = run["run_id"]
            st.rerun()
        except APIError as exc:
            st.error(str(exc), icon=":material/error:")
