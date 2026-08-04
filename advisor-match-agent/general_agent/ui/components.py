"""Native Streamlit renderers and pure live-event reduction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import streamlit as st

from general_agent.ui.api_client import APIError, AgentAPIClient

_PHASE_ICONS = {
    "started": ":material/pending:",
    "updated": ":material/info:",
    "completed": ":material/check_circle:",
    "failed": ":material/error:",
}


def reduce_live_events(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold event-only run updates into stable fragment-rendering state."""

    state.setdefault("activities", [])
    for event in events:
        state["activities"].append(("event", event))
    return state


def render_turn(
    client: AgentAPIClient,
    turn: dict[str, Any],
    *,
    conversation_id: str,
    actions_disabled: bool = False,
    debug_mode: bool = False,
) -> None:
    with st.chat_message("user"):
        st.markdown(_markdown_text(turn["user_message"]))
        for attachment in turn.get("attachments") or []:
            is_derived = bool(attachment.get("derived_from_attachment_id"))
            attachment_label = "Derived input" if is_derived else "Original upload"
            with st.container(horizontal=True, vertical_alignment="center"):
                st.caption(
                    f":material/attach_file: {attachment_label} · "
                    f"{attachment['original_name']} · "
                    f"{_format_bytes(attachment['size_bytes'])}"
                )
                st.download_button(
                    "Download derived" if is_derived else "Download original",
                    data=lambda item=attachment: client.download_attachment(item["attachment_id"]),
                    file_name=attachment["original_name"],
                    icon=":material/download:",
                    type="tertiary",
                    on_click="ignore",
                    key=f"attachment_{attachment['attachment_id']}",
                )

    if turn["status"] == "running":
        return
    with st.chat_message("assistant", avatar=":material/assistant:"):
        if turn.get("assistant_message"):
            st.markdown(_markdown_text(turn["assistant_message"]))
        elif turn["status"] == "stopped":
            st.warning("This run was stopped before a final answer was produced.", icon=":material/stop_circle:")
        elif turn.get("error"):
            st.error(_friendly_error(turn["error"]), icon=":material/error:")
            if debug_mode:
                st.caption("Technical details are available below because debug mode is enabled.")
                with st.expander("Technical details", icon=":material/bug_report:"):
                    st.code(turn["error"], language="text")
        render_artifacts(
            client,
            turn.get("artifacts") or [],
            turn["run_id"],
            conversation_id=conversation_id,
            actions_disabled=actions_disabled,
        )
        activity_state = reduce_live_events({}, turn.get("events") or [])
        if activity_state.get("activities"):
            with st.status(
                "How this was produced",
                expanded=False,
                state="complete" if turn["status"] == "completed" else "error",
            ):
                render_activity_timeline(activity_state, debug_mode=debug_mode)
        if debug_mode:
            render_diagnostics(
                turn.get("diagnostics") or {}, key=f"turn_{turn['run_id']}"
            )


def render_artifacts(
    client: AgentAPIClient,
    artifacts: list[dict[str, Any]],
    run_id: str,
    *,
    conversation_id: str,
    actions_disabled: bool = False,
) -> None:
    if not artifacts:
        return
    with st.expander("Workflow exports", icon=":material/folder:", expanded=True):
        for artifact in artifacts:
            is_profile_report = (
                artifact.get("artifact_kind") == "advisor_profile_report"
                or Path(artifact["relative_path"]).suffix.casefold() == ".html"
            )
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(
                    f"**{Path(artifact['relative_path']).name}**  "
                    f":{_artifact_color(artifact['change_type'])}-badge[{artifact['change_type']}]"
                )
                details = [_format_bytes(artifact["size_bytes"])]
                if artifact.get("revision"):
                    details.append(f"Revision {artifact['revision']}")
                st.caption(" · ".join(details))
                st.download_button(
                    "Download HTML" if is_profile_report else "Download",
                    data=lambda item=artifact: client.download_artifact(item["artifact_id"]),
                    file_name=Path(artifact["relative_path"]).name,
                    mime="text/html" if is_profile_report else None,
                    icon=":material/download:",
                    type="tertiary",
                    on_click="ignore",
                    key=f"artifact_{run_id}_{artifact['artifact_id']}",
                )
                if artifact.get("match_session_id") and not is_profile_report:
                    if st.button(
                        "Generate advisor profile report",
                        icon=":material/description:",
                        type="secondary",
                        disabled=actions_disabled,
                        key=f"profile_action_{artifact['artifact_id']}",
                    ):
                        _start_profile_report(
                            client,
                            conversation_id,
                            str(artifact["match_session_id"]),
                        )
            if is_profile_report:
                _render_profile_report_preview(client, artifact)


def _start_profile_report(
    client: AgentAPIClient,
    conversation_id: str,
    match_session_id: str,
) -> None:
    try:
        run = client.send_message(
            conversation_id,
            "Generate an advisor profile report from the automatically matched CRD numbers.",
            [],
            requested_workflow="profile_report",
            source_match_session_id=match_session_id,
        )
    except APIError as exc:
        st.error(str(exc), icon=":material/error:")
        return
    st.session_state[f"live_state_{run['run_id']}"] = {}
    st.session_state[f"event_cursor_{run['run_id']}"] = 0
    st.rerun()


def _render_profile_report_preview(
    client: AgentAPIClient, artifact: dict[str, Any]
) -> None:
    with st.expander(
        "Preview advisor profile report",
        icon=":material/preview:",
        expanded=True,
    ):
        try:
            html = client.download_artifact(artifact["artifact_id"]).decode("utf-8")
        except (APIError, UnicodeError) as exc:
            st.error(f"The HTML preview is unavailable: {exc}", icon=":material/error:")
            return
        st.caption("Version 1 is an intentionally blank placeholder HTML report.")
        st.html(html, unsafe_allow_javascript=False)


def render_live_run(
    client: AgentAPIClient,
    run: dict[str, Any],
    state: dict[str, Any],
    *,
    debug_mode: bool = False,
) -> None:
    label = _latest_activity_label(state) or "Advisor Match Agent is working…"
    with st.status(label, expanded=True, state="running"):
        render_activity_timeline(state, debug_mode=debug_mode)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button(
            "Stop",
            icon=":material/stop_circle:",
            type="secondary",
            on_click=lambda: client.stop_run(run["run_id"]),
            key=f"stop_{run['run_id']}",
        )
        if debug_mode:
            diagnostics = run.get("diagnostics") or {}
            tokens = diagnostics.get("tokens") or {}
            st.caption(f"{int(tokens.get('total_tokens') or 0):,} tokens so far")
    if debug_mode:
        render_diagnostics(
            run.get("diagnostics") or {}, key=f"live_{run['run_id']}"
        )


def render_activity_timeline(
    state: dict[str, Any], *, debug_mode: bool = False
) -> None:
    """Render explicit graph/application lifecycle events."""
    for activity_type, item in state.get("activities") or []:
        event = item
        duration = _duration_suffix((event.get("data") or {}).get("duration_ms"))
        icon = _PHASE_ICONS.get(str(event.get("phase")), ":material/info:")
        st.caption(
            f"{icon} {event.get('label') or 'Agent activity'} · "
            f"{_agent_label(event.get('agent'))}{duration}"
        )


def _latest_activity_label(state: dict[str, Any]) -> str | None:
    activities = state.get("activities") or []
    if not activities:
        return None
    activity_type, item = activities[-1]
    return str(item.get("label") or "Advisor Match Agent is working…")


def render_diagnostics(diagnostics: dict[str, Any], *, key: str) -> None:
    with st.expander("Run diagnostics", icon=":material/monitoring:", expanded=False, key=f"diagnostics_{key}"):
        render_run_diagnostics_content(diagnostics)


def render_run_diagnostics_content(diagnostics: dict[str, Any]) -> None:
    tokens = diagnostics.get("tokens") or {}
    columns = st.columns(4)
    columns[0].metric("Tokens", _format_tokens(tokens.get("total_tokens")))
    columns[1].metric("Elapsed", _format_duration(diagnostics.get("elapsed_ms")))
    columns[2].metric("Model calls", int(diagnostics.get("model_calls") or 0))
    columns[3].metric("Tool calls", int(diagnostics.get("tool_calls") or 0))
    details = [
        f"input {_format_tokens(tokens.get('input_tokens'))}",
        f"output {_format_tokens(tokens.get('output_tokens'))}",
    ]
    if tokens.get("cached_input_tokens") is not None:
        details.append(f"cached input {_format_tokens(tokens.get('cached_input_tokens'))}")
    if tokens.get("reasoning_output_tokens") is not None:
        details.append(
            f"reasoning output {_format_tokens(tokens.get('reasoning_output_tokens'))}"
        )
    if diagnostics.get("token_usage_partial"):
        details.append("token total is partial")
    st.caption(" · ".join(details))
    agents = diagnostics.get("agents") or []
    if agents:
        st.markdown("**By agent**")
        st.dataframe(
            [
                {
                    "Agent": _agent_label(item.get("agent")),
                    "Tokens": int((item.get("tokens") or {}).get("total_tokens") or 0),
                    "Model calls": int(item.get("model_calls") or 0),
                }
                for item in agents
            ],
            hide_index=True,
            width="stretch",
        )


def render_conversation_diagnostics_content(
    diagnostics: dict[str, Any], *, run_count: int, active: bool
) -> None:
    """Render the same compact aggregate summary used by the analyst app."""

    tokens = diagnostics.get("tokens") or {}
    qualifier = "partial" if diagnostics.get("token_usage_partial") else "reported"
    active_label = " · active" if active else ""
    run_label = "run" if run_count == 1 else "runs"
    st.caption(
        f"{_format_tokens(tokens.get('total_tokens'))} tokens ({qualifier}) · "
        f"{_format_duration(diagnostics.get('elapsed_ms'))} elapsed · "
        f"{run_count} {run_label}{active_label}"
    )
    st.caption(
        f"Input {_format_tokens(tokens.get('input_tokens'))} · "
        f"output {_format_tokens(tokens.get('output_tokens'))} · "
        f"{int(diagnostics.get('model_calls') or 0)} model calls · "
        f"{int(diagnostics.get('tool_calls') or 0)} tool calls"
    )


def _agent_label(agent: Any) -> str:
    value = str(agent or "advisor-match-agent")
    if value == "advisor-match-agent":
        return "Advisor Match Agent"
    return value.replace("-", " ").title()


def _format_tokens(value: Any) -> str:
    return f"{int(value or 0):,}"


def _format_duration(milliseconds: Any) -> str:
    value = max(0.0, float(milliseconds or 0))
    if value < 1000:
        return f"{round(value):,} ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.0f}s"


def _duration_suffix(milliseconds: Any) -> str:
    if milliseconds is None:
        return ""
    return f" · {_format_duration(milliseconds)}"


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _artifact_color(change_type: str) -> str:
    return {"created": "green", "modified": "blue", "deleted": "red"}.get(change_type, "gray")


def _friendly_error(error: str) -> str:
    if "Function tools with reasoning_effort are not supported" in error:
        return (
            "The configured OpenAI transport rejected reasoning with tools. "
            "Restart the backend to apply the Responses API configuration, then try again."
        )
    return (
        "I couldn’t finish this request. Your upload and previous matching results "
        "were not changed. Please try again; if the problem continues, check the API "
        "logs or enable UI debug mode for technical details."
    )


def _markdown_text(value: Any) -> str:
    """Prevent currency amounts from becoming accidental display-math spans."""

    return re.sub(r"(?<!\\)\$(?=\d)", r"\\$", str(value or ""))
