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
    current_activity,
    prose_markdown,
    render_activity,
    render_answer,
    render_approval,
    render_empty_state,
    render_page_header,
    render_pending_user_message,
    render_sidebar,
    render_turn,
)

from data_analytics_agent.ui.uploads import (
    chat_submission,
    stage_attachment,
    render_upload_review,
    render_uploaded_source,
    render_workbook_selection,
)
from data_analytics_agent.ui.workspace import render_workspace_documents
from data_analytics_agent.ui.dashboards import render_dashboards

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
    st.session_state.setdefault("conversation_notice", None)
    st.session_state.setdefault("review_notice", None)


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
        "review_choice_",
        "starter_question_",
        "chat_input_",
        "voice_",
    )
    for key in list(st.session_state):
        if key.startswith(removable_prefixes):
            del st.session_state[key]
    st.session_state["active_run_id"] = None
    st.session_state["review_notice"] = None
    st.session_state.pop("pending_file_conversation", None)
    for key in ("draft_source", "draft_question", "draft_error", "source_prompt"):
        st.session_state.pop(key, None)


def open_attachment(submission, *, target_thread_id=None):
    try:
        with st.spinner("Opening your file…"):
            uploaded = stage_attachment(
                client, submission, upload_max_bytes, thread_id=target_thread_id
            )
    except APIError as exc:
        st.error(str(exc))
        return
    st.session_state.pop("pending_file_conversation", None)
    if uploaded is None:
        st.rerun()
    new_thread = uploaded["thread_id"]
    if new_thread != target_thread_id:
        clear_conversation_state()
    st.session_state.setdefault("upload_questions", {})[new_thread] = submission.text
    st.session_state["conversation_notice"] = "Attachment added to this conversation."
    st.query_params["thread_id"] = new_thread
    st.rerun()


def new_conversation_draft() -> None:
    clear_conversation_state()
    st.query_params.pop("thread_id", None)


def load_conversation(
    client: AgentAPIClient,
) -> tuple[str | None, dict[str, Any] | None]:
    thread_id = st.query_params.get("thread_id")
    if thread_id:
        try:
            thread_id = str(thread_id)
            return thread_id, client.get_conversation(thread_id)
        except APIError as exc:
            if exc.status_code != 404:
                raise
            new_conversation_draft()
            st.session_state["conversation_notice"] = (
                "The previous local conversation is no longer available."
            )
    return None, None


def choose_draft_source(source_id: str, question: str | None = None) -> None:
    st.session_state["draft_source"] = source_id
    if question is not None:
        st.session_state["draft_question"] = question
        st.session_state.pop("draft_error", None)


def render_draft_sources(ready_sources: dict[str, Any]) -> None:
    if not ready_sources:
        return
    st.markdown("**Available data sources**")
    if any(source["examples"] for source in ready_sources.values()):
        st.caption("Choose an example to fill the message box, then edit or send it.")
    with st.container(horizontal=True):
        for source_id, source in ready_sources.items():
            with st.container(border=True, width=340, gap="small"):
                st.markdown(f"**{source['name']}**")
                st.caption(source["description"])
                with st.container(horizontal=True):
                    for index, example in enumerate(source["examples"]):
                        st.button(
                            example["question"],
                            key=f"draft_example_{source_id}_{index}",
                            on_click=choose_draft_source,
                            args=(source_id, example["question"]),
                        )
                if st.session_state.get("draft_source") == source_id:
                    st.caption(":material/check: Selected for your next message")
                else:
                    st.button(
                        f"Use {source['name']}",
                        key=f"draft_use_{source_id}",
                        type="tertiary",
                        on_click=choose_draft_source,
                        args=(source_id,),
                    )


def render_conversation_draft(
    client: AgentAPIClient, data_sources: dict[str, Any], upload_max_bytes: int
) -> None:
    render_page_header(
        subtitle="Ask a data question and Automatic will look for a matching source. "
        "You can choose one yourself or attach a file."
    )
    if notice := st.session_state.pop("conversation_notice", None):
        st.toast(notice, icon=":material/info:")
    for error in data_sources.get("errors", []):
        st.caption(f"Source configuration: {error}")
    ready_sources = {
        item["source_id"]: item for item in data_sources["sources"] if item["ready"]
    }
    if source_prompt := st.session_state.get("source_prompt"):
        choices = {choice["source_id"] for choice in source_prompt["choices"]}
        ready_sources = {
            source_id: source
            for source_id, source in ready_sources.items()
            if source_id in choices
        }
        with st.chat_message("user"):
            st.markdown(prose_markdown(source_prompt["question"]))
        with st.chat_message("assistant"):
            st.markdown(source_prompt["prompt"])
            render_draft_sources(ready_sources)
    elif ready_sources:
        render_draft_sources(ready_sources)
    else:
        st.info("No configured data sources are ready. Use + in the message box to attach a file.")

    selected_source = ""
    if ready_sources:
        selected_source = st.selectbox(
            "Data source",
            options=["", *ready_sources],
            format_func=lambda source_id: (
                ready_sources[source_id]["name"] if source_id else "Automatic"
            ),
            key="draft_source",
            width=340,
        )
    if error := st.session_state.get("draft_error"):
        st.error(error)

    chat_key = "chat_input_draft"
    if question := st.session_state.pop("draft_question", None):
        st.session_state[chat_key] = question
    submission = chat_submission(
        "Ask a question or attach a file",
        key=chat_key,
        max_bytes=upload_max_bytes,
        client=client,
    )
    if not submission:
        return
    if submission.files:
        open_attachment(submission)
        return
    question = submission.text.strip()
    if not question:
        return
    st.session_state.pop("source_prompt", None)
    st.session_state.pop("draft_error", None)
    try:
        status = "Starting your conversation…" if selected_source else "Checking available data sources…"
        with st.spinner(status):
            result = client.start_conversation(question, source_id=selected_source or None)
    except APIError as exc:
        st.session_state["draft_question"] = question
        st.session_state["draft_error"] = str(exc)
    else:
        if result["status"] == "needs_source":
            st.session_state["source_prompt"] = {**result, "question": question}
            if result["reason"] == "ambiguous":
                st.session_state["draft_question"] = question
        else:
            clear_conversation_state()
            st.query_params["thread_id"] = result["thread_id"]
    st.rerun()


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
        new_conversation_draft()
        st.session_state["conversation_notice"] = "History deleted."
    except APIError as exc:
        st.session_state["history_deletion_error"] = str(exc)


def clear_completed_run(run_id: str) -> None:
    st.session_state["active_run_id"] = None
    st.session_state.pop(f"event_cursor_{run_id}", None)
    st.session_state.pop(f"event_activities_{run_id}", None)
    st.session_state.pop(f"debug_states_{run_id}", None)
    st.session_state.pop(f"review_feedback_{run_id}", None)
    st.session_state.pop(f"review_phase_{run_id}", None)


@st.fragment(run_every="1s")
def render_active_run(
    client: AgentAPIClient, run_id: str, thread_id: str, source_id: str
):
    try:
        cursor = st.session_state.get(f"event_cursor_{run_id}", 0)
        run = client.get_run(run_id, after_event_id=cursor)
        events = st.session_state.get(f"event_activities_{run_id}", []) + (
            run.get("events") or []
        )
        st.session_state[f"event_activities_{run_id}"] = events
        st.session_state[f"event_cursor_{run_id}"] = run.get("next_event_id", cursor)
        run["events"] = events
        state = run["status"]
        if state == "completed":
            clear_completed_run(run_id)
            st.rerun()
        render_pending_user_message(run["question"])
        with st.chat_message("assistant", avatar=":material/query_stats:"):
            elapsed = (run.get("run_diagnostics") or {}).get("elapsed_ms", 0) / 1000
            label = current_activity(
                run.get("events") or [],
                status=state,
                findings=bool(run.get("findings")),
                active_model_agent=run.get("active_model_agent"),
                report_ready=run.get("report_ready", False),
                approval=run.get("approval"),
                source_id=source_id,
            )
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(prose_markdown(f"**{label}** · {elapsed:.0f}s"))
                if state in {
                    "running",
                    "queued",
                    "approval_required",
                    "clarification_required",
                }:
                    if st.button("Stop", key=f"stop_{run_id}"):
                        client.stop_run(run_id)
                        st.rerun()
            if state == "clarification_required":
                clarification = run["clarification"]
                st.markdown(clarification["question"])
                for choice in clarification.get("choices") or []:
                    st.caption(choice)
                with st.form(f"clarification_{run_id}"):
                    answer = st.text_input(
                        "Your answer", key=f"clarification_answer_{run_id}"
                    )
                    if st.form_submit_button("Continue") and answer.strip():
                        client.answer_clarification(
                            run_id,
                            answer,
                            interrupt_id=clarification["interrupt_id"],
                        )
                        st.rerun()
            if state == "approval_required":
                decisions = render_approval(run)
                if decisions:
                    client.submit_decisions(
                        run_id, run["approval"]["interrupt_id"], decisions
                    )
                    st.rerun()
            elif state in {"paused", "failed"}:
                # Re-run once to release the chat input after a stop.
                if st.session_state.get("active_run_id") == run_id:
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
            render_activity(
                run.get("events") or [], run.get("run_diagnostics") or {}, key=run_id
            )
            if run.get("findings"):
                render_answer(
                    client,
                    run["findings"],
                    turn_key=run_id,
                    source_id=source_id,
                    analysis_download_available=False,
                )
                st.caption(
                    "Report: retry available"
                    if state == "failed"
                    else "Report: preparing"
                )
            for correction in run.get("corrections") or []:
                applied = "coordinator" in correction.get("delivered_to", [])
                st.caption(
                    f"{'Applied' if applied else 'Received; applying after the current step'} · {correction['message']}"
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

upload_max_bytes = (health or {}).get("upload_max_bytes", 33_554_432)
react_ui_enabled = (health or {}).get("react_ui_enabled", False)

if st.session_state.get("pending_workbook"):
    render_workbook_selection(client)
    st.stop()

sources_by_id = {source["source_id"]: source for source in data_sources["sources"]}

try:
    thread_id, conversation = load_conversation(client)
except APIError as exc:
    render_page_header()
    st.error(str(exc), icon=":material/cloud_off:")
    st.stop()

if conversation and conversation["source_id"] not in sources_by_id:
    try:
        saved_source = client.get_conversation_source(thread_id)
    except APIError as exc:
        render_page_header()
        st.error(f"This conversation's source is unavailable. {exc}")
        st.caption(
            "Saved answers remain available. Restore the source configuration and refresh this page before starting new analysis."
        )
        for turn in conversation["turns"]:
            render_turn(
                client,
                turn,
                turn_key=turn["run_id"],
                source_id=conversation["source_id"],
            )
        st.stop()
    sources_by_id[saved_source["source_id"]] = saved_source
    data_sources["sources"].append(saved_source)

source = sources_by_id[conversation["source_id"]] if conversation else None
active_run_id = (conversation or {}).get("active_run_id")
st.session_state["active_run_id"] = active_run_id

new_conversation, conversation_diagnostics_slot = render_sidebar(
    thread_id=thread_id,
    app_base_url=APP_BASE_URL,
    health=health,
    health_error=health_error,
    data_sources=data_sources,
    source=source,
    diagnostics=(conversation or {}).get("diagnostics") or {},
)
if new_conversation:
    new_conversation_draft()
    st.rerun()

with st.sidebar:
    saved_conversations = client.list_conversations()
    with st.expander("Saved conversations", expanded=False):
        for saved in reversed(saved_conversations):
            if st.button(
                saved["title"],
                key=f"saved_{saved['thread_id']}",
                disabled=saved["thread_id"] == st.query_params.get("thread_id"),
            ):
                clear_conversation_state()
                st.query_params["thread_id"] = saved["thread_id"]
                st.rerun()

    with st.expander("Manage history", expanded=False):
        history_target = thread_id or "all"
        st.button(
            "Delete history",
            key=f"delete_{history_target}",
            disabled=bool(active_run_id) or not saved_conversations,
            on_click=request_history_deletion,
            args=(history_target,),
        )
        if active_run_id:
            st.caption("Stop active work before deleting its conversation.")
        pending = st.session_state.get("history_deletion")
        if pending and pending != history_target:
            st.session_state.pop("history_deletion", None)
            pending = None
        if pending:
            target = pending
            if thread_id:
                selected_scope = st.radio(
                    "Delete which history?",
                    ["This conversation", "All conversations"],
                    key="history_deletion_scope",
                )
                if selected_scope == "All conversations":
                    target = "all"
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

if conversation is None:
    render_conversation_draft(client, data_sources, upload_max_bytes)
    st.stop()

render_page_header(source)
if react_ui_enabled:
    st.link_button(
        "Open full workspace",
        f"{API_BASE_URL}/workspace/?thread={thread_id}",
        icon=":material/open_in_new:",
    )

pending_file = st.session_state.get("pending_file_conversation")
if pending_file and pending_file["thread_id"] == thread_id:
    st.info(
        "This conversation uses a warehouse. Analyze the attached table in a new "
        "file conversation; your existing conversation will stay available."
    )
    with st.container(horizontal=True):
        if st.button("Start file conversation", disabled=bool(active_run_id)):
            open_attachment(pending_file["submission"])
        if st.button("Cancel attachment"):
            st.session_state[f"chat_input_{thread_id}"] = pending_file["submission"].text
            st.session_state.pop("pending_file_conversation")
            st.rerun()

if source["backend_type"] == "upload":
    uploaded_files = client.get_uploads(thread_id)
    pending_upload = next((item for item in uploaded_files if not item["confirmed"]), None)
    if pending_upload:
        pending_question = st.session_state.get("upload_questions", {}).get(thread_id)
        if pending_question:
            st.info("After you confirm the data, I’ll answer: " + pending_question)
        render_upload_review(client, pending_upload)
        st.stop()
    for uploaded_file in uploaded_files:
        render_uploaded_source(client, uploaded_file)

pending_question = st.session_state.get("upload_questions", {}).pop(thread_id, None)
if pending_question:
    try:
        client.send_message(thread_id, pending_question)
        conversation = client.get_conversation(thread_id)
        active_run_id = conversation.get("active_run_id")
        st.session_state["active_run_id"] = active_run_id
    except APIError as exc:
        st.session_state[f"chat_input_{thread_id}"] = pending_question
        st.error(str(exc))

render_workspace_documents(
    client, thread_id, is_file=source["backend_type"] == "upload", disabled=bool(active_run_id)
)

render_dashboards(
    client,
    thread_id,
    conversation,
    react_ui_enabled=react_ui_enabled,
    disabled=bool(active_run_id),
)


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

completed_turns = {turn["run_id"]: turn for turn in conversation["turns"]}
for saved_run_id in conversation.get("run_ids") or []:
    if saved_run_id in completed_turns:
        render_turn(
            client,
            completed_turns[saved_run_id],
            turn_key=saved_run_id,
            source_id=conversation["source_id"],
        )
    else:
        if saved_run_id == active_run_id:
            st.session_state["active_run_id"] = active_run_id
        render_active_run(client, saved_run_id, thread_id, conversation["source_id"])

chat_input_key = f"chat_input_{thread_id}"
if not conversation["turns"] and not conversation.get("run_ids"):
    render_empty_state(
        thread_id,
        source,
        chat_input_key=chat_input_key,
    )

submission = chat_submission(
    "Add context or correct the current request"
    if active_run_id
    else f"Ask a business question about {source['name']}",
    key=chat_input_key,
    max_bytes=upload_max_bytes,
    client=client,
)
if submission and submission.files:
    if active_run_id:
        st.error("Wait for the current work to finish or stop it before attaching a file.")
    else:
        is_document = submission.files[0].name.lower().endswith((".pdf", ".txt", ".md"))
        if source["backend_type"] == "upload" or is_document:
            open_attachment(submission, target_thread_id=thread_id)
        elif conversation["turns"] or conversation.get("run_ids"):
            st.session_state["pending_file_conversation"] = {
                "thread_id": thread_id,
                "submission": submission,
            }
            st.rerun()
        else:
            open_attachment(submission)
if submission and not submission.files and submission.text.strip():
    typed_question = submission.text
    try:
        if active_run_id:
            if client.get_run(active_run_id)["status"] == "clarification_required":
                run = client.answer_clarification(active_run_id, typed_question)
                st.session_state["conversation_notice"] = (
                    "Answer received; continuing the investigation."
                )
            else:
                run = client.send_correction(active_run_id, typed_question)
                st.session_state["conversation_notice"] = run["message"]
        else:
            run = client.send_message(
                thread_id,
                typed_question,
            )
        st.session_state["active_run_id"] = active_run_id or run["run_id"]
        st.rerun()
    except APIError as exc:
        st.error(str(exc), icon=":material/error:")
