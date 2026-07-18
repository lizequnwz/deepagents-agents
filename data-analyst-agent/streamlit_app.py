"""Streamlit chat UI for the local Chinook Deep Agent API."""

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from text2sql_agent.ui.api_client import APIError, AgentAPIClient
from text2sql_agent.ui.components import (
    render_approval,
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
    page_title="Chinook Analyst",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def initialize_session_state() -> None:
    st.session_state.setdefault("active_run_id", None)
    st.session_state.setdefault("last_run_error", None)
    st.session_state.setdefault("conversation_notice", None)
    st.session_state.setdefault("review_notice", None)


def clear_conversation_state() -> None:
    """Clear per-conversation widget and polling state."""

    removable_prefixes = (
        "event_cursor_",
        "event_labels_",
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
    st.session_state["review_notice"] = None


def create_conversation(client: AgentAPIClient) -> str:
    thread_id = client.create_conversation()
    clear_conversation_state()
    st.query_params["thread_id"] = thread_id
    return thread_id


def get_or_create_conversation(
    client: AgentAPIClient,
) -> tuple[str, dict[str, Any]]:
    thread_id = st.query_params.get("thread_id")
    if thread_id:
        try:
            return str(thread_id), client.get_conversation(str(thread_id))
        except APIError as exc:
            if exc.status_code != 404:
                raise
            st.query_params.pop("thread_id", None)
            st.session_state["conversation_notice"] = (
                "The previous local conversation is no longer available. "
                "A new conversation was started."
            )

    thread_id = create_conversation(client)
    return thread_id, client.get_conversation(thread_id)


def clear_completed_run(run_id: str) -> None:
    st.session_state["active_run_id"] = None
    st.session_state.pop(f"event_cursor_{run_id}", None)
    st.session_state.pop(f"event_labels_{run_id}", None)
    st.session_state.pop(f"review_feedback_{run_id}", None)
    st.session_state.pop(f"review_phase_{run_id}", None)


def poll_run(
    client: AgentAPIClient,
    run_id: str,
    initial_run: dict[str, Any],
) -> dict[str, Any]:
    cursor_key = f"event_cursor_{run_id}"
    labels_key = f"event_labels_{run_id}"
    cursor = int(st.session_state.get(cursor_key, 0))
    labels: list[str] = st.session_state.setdefault(labels_key, [])
    run = initial_run if cursor == 0 else client.get_run(
        run_id, after_event_id=cursor
    )
    review_phase = st.session_state.get(f"review_phase_{run_id}")
    initial_status = (
        "Feedback sent—revising SQL…"
        if review_phase == "revising"
        else "Executing reviewed SQL…"
        if review_phase == "executing"
        else "Agent is working…"
    )

    with st.status(
        initial_status,
        expanded=True,
        state="running",
    ) as status_panel:
        for label in labels:
            st.caption(f":material/check: {label}")

        while True:
            for event in run["events"]:
                label = event["label"]
                labels.append(label)
                st.caption(f":material/check: {label}")
                status_panel.update(label=label, state="running", expanded=True)

            cursor = int(run["next_event_id"])
            st.session_state[cursor_key] = cursor
            state = run["status"]

            if state == "approval_required":
                revised = review_phase == "revising"
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
    thread_id, conversation = get_or_create_conversation(client)
except APIError as exc:
    render_page_header()
    st.error(str(exc), icon=":material/cloud_off:")
    st.caption(
        "Run `./scripts/start.sh` from the project directory, then refresh "
        "this page."
    )
    st.stop()

if render_sidebar(
    thread_id=thread_id,
    app_base_url=APP_BASE_URL,
    health=health,
    health_error=health_error,
):
    try:
        create_conversation(client)
        st.rerun()
    except APIError as exc:
        st.sidebar.error(str(exc), icon=":material/error:")

render_page_header()

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
    )

if st.session_state.get("last_run_error"):
    st.error(
        st.session_state["last_run_error"],
        icon=":material/error:",
    )

active_run_id = (
    conversation.get("active_run_id")
    or st.session_state.get("active_run_id")
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
                    ] = "revising"
                else:
                    st.session_state.pop(
                        f"review_feedback_{active_run_id}",
                        None,
                    )
                    st.session_state[
                        f"review_phase_{active_run_id}"
                    ] = "executing"
                st.rerun()
            except APIError as exc:
                st.error(str(exc), icon=":material/error:")
    elif active_run and active_run["status"] == "failed":
        st.session_state["last_run_error"] = (
            active_run.get("error") or "The agent run failed."
        )
        clear_completed_run(active_run_id)
        st.rerun()
    elif active_run and active_run["status"] == "completed":
        clear_completed_run(active_run_id)
        st.rerun()

if not active_run_id:
    starter_question = None
    if not conversation["turns"]:
        starter_question = render_empty_state(thread_id)

    typed_question = st.chat_input(
        "Ask about customers, music, sales, employees, or playlists",
        submit_mode="disable",
    )
    question = starter_question or typed_question
    if question:
        try:
            st.session_state["last_run_error"] = None
            run = client.send_message(thread_id, question)
            st.session_state["active_run_id"] = run["run_id"]
            st.rerun()
        except APIError as exc:
            st.error(str(exc), icon=":material/error:")
