"""Chat-first Streamlit frontend for Advisor Match Agent."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from general_agent.config import Settings
from general_agent.ui.api_client import APIError, AgentAPIClient
from general_agent.ui.components import (
    reduce_live_events,
    render_conversation_diagnostics_content,
    render_diagnostics,
    render_live_run,
    render_turn,
)

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
UI_DEBUG_MODE = Settings(project_root=PROJECT_ROOT).ui_debug_mode
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', '8502')}",
).rstrip("/")
MATCH_TYPES = ["csv", "xlsx"]

st.set_page_config(
    page_title="Advisor Match Agent",
    page_icon=":material/manage_search:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def initialize_state() -> None:
    st.session_state.setdefault(
        "corp_id", os.getenv("DEFAULT_CORP_ID", "A123456") or "A123456"
    )
    st.session_state.setdefault("current_conversation_id", None)


@st.cache_resource
def api_client(base_url: str, corp_id: str) -> AgentAPIClient:
    return AgentAPIClient(base_url, corp_id)


def clear_current_chat_state() -> None:
    """Drop polling state when starting a fresh browser chat."""

    for key in list(st.session_state):
        if key.startswith(("live_state_", "event_cursor_")):
            del st.session_state[key]


def create_current_conversation(client: AgentAPIClient) -> tuple[str, dict]:
    created = client.create_conversation()
    conversation_id = created["conversation_id"]
    clear_current_chat_state()
    st.session_state["current_conversation_id"] = conversation_id
    st.query_params["conversation_id"] = conversation_id
    return conversation_id, client.conversation(conversation_id)


def get_or_create_current_conversation(
    client: AgentAPIClient,
) -> tuple[str, dict]:
    """Resolve the one browser chat, mirroring the analytics app's model."""

    requested = st.query_params.get("conversation_id")
    if not requested:
        requested = st.session_state.get("current_conversation_id")
    if requested:
        try:
            conversation = client.conversation(str(requested))
            st.session_state["current_conversation_id"] = str(requested)
            if st.query_params.get("conversation_id") != str(requested):
                st.query_params["conversation_id"] = str(requested)
            return str(requested), conversation
        except APIError as exc:
            if exc.status_code != 404:
                raise
            st.query_params.pop("conversation_id", None)
            st.session_state["current_conversation_id"] = None
    return create_current_conversation(client)


def render_page_header() -> None:
    st.caption(":material/manage_search: TRUSTED ADVISOR WORKFLOW AGENT")
    st.title("Match financial advisors and generate reports", anchor=False)
    st.caption(
        "Upload one CSV or XLSX, match its advisor rows against the master "
        "advisor database, or generate a placeholder HTML profile report from a CRD "
        "column."
    )


def load_starter_prompt(prompt_key: str, suggestions: dict[str, str]) -> None:
    """Copy a selected example into the composer without submitting it."""

    selected = st.session_state.get(prompt_key)
    prompt = suggestions.get(selected)
    if prompt:
        st.session_state["chat_input"] = prompt


initialize_state()
client = api_client(API_BASE_URL, st.session_state["corp_id"])

try:
    health = client.health()
    conversation_id, conversation = get_or_create_current_conversation(client)
except APIError as exc:
    st.title("Advisor Match Agent", anchor=False)
    st.error(str(exc), icon=":material/cloud_off:")
    st.caption("Run `./scripts/start.sh` from the advisor-match-agent directory, then refresh this page.")
    st.stop()

with st.sidebar:
    st.title("Advisor Match Agent", anchor=False)
    st.caption(
        f":material/corporate_fare: Corporation scope {st.session_state['corp_id']}"
    )
    st.caption(
        "A trusted workflow for deterministic advisor matching and workbook export."
    )
    new_chat = st.button(
        "New chat",
        icon=":material/add_comment:",
        type="primary",
        width="stretch",
        disabled=bool(conversation.get("active_run_id")),
        help="Start a fresh chat. This browser shows one chat at a time.",
    )
    st.badge(
        f"API ready · {health['model']}",
        icon=":material/check_circle:",
        color="green",
    )
    if UI_DEBUG_MODE:
        diagnostics = conversation.get("diagnostics") or {}
        st.caption(f"Chat · `{conversation_id[:8]}`")
        st.caption(":material/bug_report: UI debug mode enabled")
        with st.expander(
            "Conversation diagnostics",
            icon=":material/monitoring:",
            expanded=False,
            key=f"conversation_diagnostics_{conversation_id}",
        ):
            render_conversation_diagnostics_content(
                diagnostics,
                run_count=len(conversation.get("turns") or []),
                active=bool(conversation.get("active_run_id")),
            )
        with st.expander(
            "Technical details",
            icon=":material/info:",
            expanded=False,
        ):
            st.info(
                "The advisor graph has no shell, dynamic tools, or arbitrary code execution.",
                icon=":material/security:",
            )
            st.markdown("**Chat ID**")
            st.code(conversation_id, language=None)
            st.markdown("**Refresh-safe link**")
            st.code(
                f"{APP_BASE_URL}/?conversation_id={conversation_id}",
                language=None,
            )

if new_chat:
    try:
        create_current_conversation(client)
        st.rerun()
    except APIError as exc:
        st.sidebar.error(str(exc), icon=":material/error:")

render_page_header()

if not conversation["turns"]:
    suggestions = {
        ":material/manage_search: Match uploaded advisors": (
            "Help me match the advisors from the uploaded file against the master "
            "advisor database and export the results as an auditable workbook. Put "
            "ambiguous or unmatched records on the Review Required sheet for me to "
            "review in Excel."
        ),
        ":material/description: Generate advisor profile report": (
            "Generate an advisor profile report from the CRD numbers in the uploaded "
            "file. Identify the exact CRD column, ignore blank values, and deduplicate "
            "repeated CRDs."
        ),
    }
    with st.container(border=True):
        st.subheader("Start with a task", anchor=False)
        st.caption(
            "Attach one CSV or XLSX, choose an example, or write your own request."
        )
        starter_key = f"starter_prompt_{conversation_id}"
        st.pills(
            "Example tasks",
            list(suggestions),
            label_visibility="collapsed",
            width="stretch",
            key=starter_key,
            on_change=load_starter_prompt,
            args=(starter_key, suggestions),
        )

active_run_id = conversation.get("active_run_id")

for turn in conversation["turns"]:
    render_turn(
        client,
        turn,
        conversation_id=conversation_id,
        actions_disabled=bool(active_run_id),
        debug_mode=UI_DEBUG_MODE,
    )


@st.fragment(run_every=0.5)
def active_run_fragment(run_id: str) -> None:
    state_key = f"live_state_{run_id}"
    cursor_key = f"event_cursor_{run_id}"
    state = st.session_state.setdefault(state_key, {})
    cursor = int(st.session_state.get(cursor_key, 0))
    try:
        run = client.run(run_id, cursor)
    except APIError as exc:
        st.error(str(exc), icon=":material/error:")
        return
    reduce_live_events(state, run.get("events") or [])
    st.session_state[cursor_key] = run.get("next_event_id", cursor)
    render_live_run(client, run, state, debug_mode=UI_DEBUG_MODE)
    if run["status"] in {"completed", "failed", "stopped"}:
        st.session_state.pop(state_key, None)
        st.session_state.pop(cursor_key, None)
        st.rerun(scope="app")


if active_run_id:
    active_run_fragment(active_run_id)
else:
    submission = st.chat_input(
        "Ask Advisor Match Agent or attach one CSV/XLSX",
        key="chat_input",
        accept_file=True,
        file_type=MATCH_TYPES,
        max_upload_size=int(health.get("max_upload_mb") or 100),
        submit_mode="disable",
    )
    if submission:
        try:
            run = client.send_message(
                conversation_id,
                submission.text,
                list(submission.files),
            )
            st.session_state[f"live_state_{run['run_id']}"] = {}
            st.session_state[f"event_cursor_{run['run_id']}"] = 0
            st.rerun()
        except APIError as exc:
            st.error(str(exc), icon=":material/error:")
