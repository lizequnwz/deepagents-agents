"""Chat-first Streamlit frontend for the trusted-local General Agent."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

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
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', '8502')}",
).rstrip("/")
SUPPORTED_TYPES = [
    "pdf", "docx", "pptx", "xls", "xlsx", "csv", "tsv", "txt", "md",
    "rst", "json", "yaml", "yml", "toml", "py", "js", "ts", "tsx",
    "jsx", "java", "c", "cc", "cpp", "h", "hpp", "go", "rs", "rb",
    "php", "sh", "zsh", "fish", "sql", "ini", "cfg", "xml", "html",
    "css", "log",
]

st.set_page_config(
    page_title="Deep Agent",
    page_icon=":material/assistant:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def initialize_state() -> None:
    st.session_state.setdefault(
        "corp_id", os.getenv("DEFAULT_CORP_ID", "A123456") or "A123456"
    )
    st.session_state.setdefault("current_conversation_id", None)
    st.session_state.setdefault("workspace_chat_path", "")
    st.session_state.setdefault("workspace_shared_path", "")


@st.cache_resource
def api_client(base_url: str, corp_id: str) -> AgentAPIClient:
    return AgentAPIClient(base_url, corp_id)


@st.dialog("Delete workspace entry", icon=":material/delete:")
def confirm_delete_workspace(client: AgentAPIClient, path: str) -> None:
    st.warning(f"Permanently delete `{path}` from the live workspace?", icon=":material/warning:")
    if st.button("Delete file", type="primary", icon=":material/delete:"):
        client.delete_workspace(path)
        st.rerun()


@st.dialog("Clean up chat files", icon=":material/cleaning_services:")
def confirm_cleanup_chat_workspace(
    client: AgentAPIClient, conversation_id: str
) -> None:
    st.warning(
        "This permanently removes the live files for this chat. Immutable "
        "artifact versions remain available from completed turns.",
        icon=":material/warning:",
    )
    st.caption("Shared files are not affected.")
    if st.button(
        "Clean up chat files",
        type="primary",
        icon=":material/delete_sweep:",
        width="stretch",
    ):
        client.cleanup_chat_workspace(conversation_id)
        st.session_state["workspace_chat_path"] = ""
        st.toast("Chat files cleaned up", icon=":material/check_circle:")
        st.rerun()


@st.dialog("Rename workspace entry", icon=":material/edit:")
def rename_workspace_entry(client: AgentAPIClient, path: str) -> None:
    new_name = st.text_input("New name", value=Path(path).name)
    if st.button("Rename", type="primary", icon=":material/edit:"):
        client.rename_workspace(path, new_name)
        st.rerun()


@st.dialog("File preview", icon=":material/preview:", width="large")
def preview_workspace_file(client: AgentAPIClient, path: str) -> None:
    try:
        preview = client.inspect_workspace(path)
    except APIError as exc:
        st.error(str(exc), icon=":material/error:")
        return
    st.caption(f"/{path} · {preview.get('size_bytes', 0):,} bytes")
    if preview.get("scanned_or_image_only"):
        st.warning(preview.get("message"), icon=":material/document_scanner:")
    if isinstance(preview.get("text"), str):
        st.code(preview["text"], language="text")
    elif preview.get("pages"):
        for page in preview["pages"]:
            st.markdown(f"**Page {page['page']}**")
            st.code(page.get("text") or "No embedded text", language="text")
    elif preview.get("slides"):
        for slide in preview["slides"]:
            st.markdown(f"**Slide {slide['slide']}**")
            st.code(slide.get("text") or "No slide text", language="text")
            if slide.get("notes"):
                st.caption(slide["notes"])
    else:
        st.json(preview)


def clear_current_chat_state() -> None:
    """Drop polling state when starting a fresh browser chat."""

    for key in list(st.session_state):
        if key.startswith(("live_state_", "event_cursor_")):
            del st.session_state[key]


def create_current_conversation(client: AgentAPIClient) -> tuple[str, dict]:
    created = client.create_conversation()
    conversation_id = created["conversation_id"]
    clear_current_chat_state()
    st.session_state["workspace_chat_path"] = ""
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


def _scope_relative_path(path: str, scope: str, conversation_id: str) -> str:
    prefix = f"chats/{conversation_id}/" if scope == "chat" else "shared/"
    if path == prefix.rstrip("/"):
        return ""
    return path.removeprefix(prefix)


def _entry_caption(entry: dict) -> str:
    origin = {
        "upload": "Uploaded",
        "agent": "Created by agent",
        "migration": "Migrated",
        "system": "System",
        "user": "User managed",
    }.get(entry.get("origin"), "Workspace file")
    modified = str(entry.get("modified_at") or "")[:10]
    details = [origin]
    if entry.get("kind") == "file":
        details.append(f"{int(entry.get('size_bytes') or 0):,} bytes")
    if modified:
        details.append(modified)
    return " · ".join(details)


def render_workspace_sidebar(
    client: AgentAPIClient,
    conversation_id: str,
    *,
    active_run: bool,
) -> None:
    scope = st.segmented_control(
        "Workspace scope",
        options=["chat", "shared"],
        default="chat",
        required=True,
        format_func=lambda value: {
            "chat": ":material/chat: Current chat",
            "shared": ":material/folder_shared: Shared",
        }[value],
        key="workspace_scope",
        width="stretch",
        label_visibility="collapsed",
    ) or "chat"
    path_key = f"workspace_{scope}_path"
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Workspace")
        with st.popover(
            "Add files",
            icon=":material/upload:",
            type="tertiary",
            width="content",
        ):
            manual_files = st.file_uploader(
                "Choose workspace files",
                type=SUPPORTED_TYPES,
                accept_multiple_files=True,
                key=f"workspace_uploader_{scope}",
            )
            if manual_files and st.button(
                "Upload",
                icon=":material/upload:",
                width="stretch",
                key=f"workspace_upload_{scope}",
            ):
                client.upload_workspace(
                    manual_files,
                    scope=scope,
                    conversation_id=conversation_id if scope == "chat" else None,
                )
                st.toast("Files uploaded", icon=":material/check_circle:")
                st.rerun()
    st.caption(
        "Files for this chat only."
        if scope == "chat"
        else "Files intentionally retained across chats."
    )
    if scope == "chat" and st.button(
        "Clean up chat files",
        icon=":material/cleaning_services:",
        type="tertiary",
        width="stretch",
        disabled=active_run,
        help="Remove this chat's live files without touching shared files or artifact snapshots.",
    ):
        confirm_cleanup_chat_workspace(client, conversation_id)
    current = st.session_state.get(path_key, "")
    if current:
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            if st.button(
                "Up",
                icon=":material/arrow_upward:",
                type="tertiary",
                key="workspace_up",
            ):
                parent = Path(current).parent.as_posix()
                st.session_state[path_key] = "" if parent == "." else parent
                st.rerun()
            st.caption(f"/{current}")
    entries = client.workspace(
        current,
        scope=scope,
        conversation_id=conversation_id if scope == "chat" else None,
    )
    if not entries:
        st.caption("No files here yet.")
    for entry in entries:
        with st.container(border=True, gap=None):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                icon = ":material/folder:" if entry["kind"] == "directory" else ":material/description:"
                if st.button(
                    entry["name"],
                    icon=icon,
                    type="tertiary",
                    width="stretch",
                    key=f"workspace_open_{scope}_{entry['path']}",
                ):
                    if entry["kind"] == "directory":
                        st.session_state[path_key] = _scope_relative_path(
                            entry["path"], scope, conversation_id
                        )
                        st.rerun()
                    else:
                        preview_workspace_file(client, entry["path"])
                with st.popover(
                    "Actions",
                    icon=":material/more_horiz:",
                    type="tertiary",
                    width="content",
                    key=f"workspace_actions_{scope}_{entry['path']}",
                ):
                    if entry["kind"] == "file":
                        if st.button(
                            "Preview",
                            icon=":material/preview:",
                            width="stretch",
                            key=f"workspace_preview_{entry['path']}",
                        ):
                            preview_workspace_file(client, entry["path"])
                        st.download_button(
                            "Download",
                            data=lambda item=entry: client.download_workspace(item["path"]),
                            file_name=entry["name"],
                            icon=":material/download:",
                            type="tertiary",
                            on_click="ignore",
                            key=f"workspace_download_{entry['path']}",
                            width="stretch",
                        )
                    if entry.get("can_promote") and st.button(
                        "Keep in shared",
                        icon=":material/drive_file_move:",
                        width="stretch",
                        key=f"workspace_promote_{entry['path']}",
                    ):
                        kept = client.promote_workspace(entry["path"], conversation_id)
                        st.toast(
                            f"Kept {kept['name']} in shared workspace",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    if entry.get("can_modify", True):
                        if st.button(
                            "Rename",
                            icon=":material/edit:",
                            width="stretch",
                            key=f"workspace_rename_{entry['path']}",
                        ):
                            rename_workspace_entry(client, entry["path"])
                        if st.button(
                            "Delete",
                            icon=":material/delete:",
                            width="stretch",
                            key=f"workspace_delete_{entry['path']}",
                        ):
                            confirm_delete_workspace(client, entry["path"])
            st.caption(_entry_caption(entry))


def render_page_header() -> None:
    st.caption(":material/assistant: TRUSTED-LOCAL DEEP AGENT")
    st.title("Work with files, code, and plans", anchor=False)
    st.caption(
        "Plan and delegate tasks, inspect documents, create artifacts, and run "
        "visible Python or shell commands in an isolated chat workspace, with "
        "a shared area for files you choose to keep."
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
    st.title("Deep Agent", anchor=False)
    st.error(str(exc), icon=":material/cloud_off:")
    st.caption("Run `./scripts/start.sh` from the general-agent directory, then refresh this page.")
    st.stop()

with st.sidebar:
    st.title("Deep Agent", anchor=False)
    st.caption(f":material/person: User {st.session_state['corp_id']}")
    st.caption(
        "A trusted-local workspace assistant with planning, delegation, file "
        "tools, and automatic host command execution."
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
    st.badge(
        "Host execution enabled",
        icon=":material/terminal:",
        color="orange",
    )
    render_workspace_sidebar(
        client,
        conversation_id,
        active_run=bool(conversation.get("active_run_id")),
    )
    diagnostics = conversation.get("diagnostics") or {}
    st.caption(f"Chat · `{conversation_id[:8]}`")
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
        st.warning(
            "Commands run automatically on this host. Use only with trusted prompts and files.",
            icon=":material/security:",
        )
        st.markdown("**Chat ID**")
        st.code(conversation_id, language=None)
        st.markdown("**Workspace paths**")
        st.caption(
            "`/` is this chat · `/shared` persists across this user's chats"
        )
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
        ":material/code: Build a Python utility": "Create a useful Python CLI utility in the workspace and test it.",
        ":material/description: Draft a document": "Create a polished project brief as a Word document.",
        ":material/table_chart: Analyze a spreadsheet": "Inspect the spreadsheet I attach and summarize the most important findings.",
        ":material/account_tree: Plan a complex task": "Make and execute a plan for organizing the files in this workspace.",
    }
    with st.container(border=True):
        st.subheader("Start with a task", anchor=False)
        st.caption(
            "Try an example or write your own request below. Commands and code "
            "will appear in the event timeline before execution."
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

for turn in conversation["turns"]:
    render_turn(client, turn)

active_run_id = conversation.get("active_run_id")


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
    render_live_run(client, run, state)
    if run["status"] in {"completed", "failed", "stopped"}:
        st.session_state.pop(state_key, None)
        st.session_state.pop(cursor_key, None)
        st.rerun(scope="app")


if active_run_id:
    active_run_fragment(active_run_id)
else:
    submission = st.chat_input(
        "Message General Agent or attach files",
        key="chat_input",
        accept_file="multiple",
        file_type=SUPPORTED_TYPES,
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
