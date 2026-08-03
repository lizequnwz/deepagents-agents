"""Native Streamlit renderers and pure live-event reduction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import streamlit as st

from general_agent.ui.api_client import AgentAPIClient

_PHASE_ICONS = {
    "started": ":material/pending:",
    "updated": ":material/info:",
    "completed": ":material/check_circle:",
    "failed": ":material/error:",
}


def reduce_live_events(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold event-only run updates into stable fragment-rendering state."""

    state.setdefault("todos", [])
    state.setdefault("activities", [])
    state.setdefault("tools", {})
    for event in events:
        kind = event["kind"]
        data = event.get("data") or {}
        if kind == "plan_updated" and event.get("agent") == "advisor-match-agent":
            state["todos"] = data.get("todos") or []
        elif kind == "tool_started":
            call_id = str(data.get("call_id") or event["id"])
            state["tools"][call_id] = event
            state["activities"].append(("tool", call_id))
        elif kind == "tool_finished":
            call_id = str(data.get("call_id") or event["id"])
            prior = state["tools"].get(call_id, {})
            merged = {**prior, **event, "data": {**(prior.get("data") or {}), **data}}
            state["tools"][call_id] = merged
            if ("tool", call_id) not in state["activities"]:
                state["activities"].append(("tool", call_id))
        elif kind not in {"usage_updated", "assistant_delta", "plan_updated"}:
            state["activities"].append(("event", event))
    return state


def render_turn(
    client: AgentAPIClient, turn: dict[str, Any], *, debug_mode: bool = False
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
                with st.expander("Technical details", icon=":material/bug_report:"):
                    st.code(turn["error"], language="text")
        render_artifacts(client, turn.get("artifacts") or [], turn["run_id"])
        activity_state = reduce_live_events({}, turn.get("events") or [])
        if activity_state.get("activities") or activity_state.get("todos"):
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


def render_artifacts(client: AgentAPIClient, artifacts: list[dict[str, Any]], run_id: str) -> None:
    if not artifacts:
        return
    with st.expander("Workbook exports", icon=":material/folder:", expanded=True):
        for artifact in artifacts:
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
                    "Download",
                    data=lambda item=artifact: client.download_artifact(item["artifact_id"]),
                    file_name=Path(artifact["relative_path"]).name,
                    icon=":material/download:",
                    type="tertiary",
                    on_click="ignore",
                    key=f"artifact_{run_id}_{artifact['artifact_id']}",
                )


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
    """Render plans and consolidated v3 lifecycle events like the analyst UI."""

    todos = state.get("todos") or []
    if todos:
        with st.container(border=True):
            st.markdown("**Plan**")
            for todo in todos:
                status = (
                    todo.get("status", "pending")
                    if isinstance(todo, dict)
                    else "pending"
                )
                content = (
                    todo.get("content", str(todo))
                    if isinstance(todo, dict)
                    else str(todo)
                )
                icon = {
                    "completed": ":material/check_circle:",
                    "in_progress": ":material/progress_activity:",
                }.get(status, ":material/radio_button_unchecked:")
                st.caption(f"{icon} {content}")
    for activity_type, item in state.get("activities") or []:
        if activity_type == "tool":
            event = state["tools"][item]
            data = event.get("data") or {}
            duration = _duration_suffix(data.get("duration_ms"))
            st.caption(
                f"{_PHASE_ICONS.get(str(event.get('phase')), ':material/info:')} "
                f"{event.get('label') or data.get('tool_name') or 'Tool activity'} · "
                f"{_agent_label(event.get('agent'))}{duration}"
            )
            if debug_mode:
                _render_tool(event)
            continue
        event = item
        duration = _duration_suffix((event.get("data") or {}).get("duration_ms"))
        icon = (
            ":material/account_tree:"
            if str(event.get("kind", "")).startswith("subagent_")
            else _PHASE_ICONS.get(str(event.get("phase")), ":material/info:")
        )
        st.caption(
            f"{icon} {event.get('label') or 'Agent activity'} · "
            f"{_agent_label(event.get('agent'))}{duration}"
        )


def _latest_activity_label(state: dict[str, Any]) -> str | None:
    activities = state.get("activities") or []
    if not activities:
        return None
    activity_type, item = activities[-1]
    if activity_type == "tool":
        return str(state["tools"][item].get("label") or "Using a tool")
    return str(item.get("label") or "Deep Agent is working…")


def _render_tool(event: dict[str, Any]) -> None:
    data = event.get("data") or {}
    name = str(data.get("tool_name") or "tool")
    phase = event.get("phase")
    with st.expander(
        event.get("label") or name,
        icon=":material/build:",
        expanded=False,
    ):
        tool_input = data.get("input")
        if tool_input is not None:
            st.json(tool_input)
        if "output" in data and data.get("output") not in (None, ""):
            output = data["output"]
            st.code(str(output), language="text")
        if phase in {"completed", "failed"}:
            duration = int(data.get("duration_ms") or 0)
            st.caption(f"{'Failed' if phase == 'failed' else 'Completed'} · {duration / 1000:.2f}s")


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
    return "The run failed. Open technical details for the provider or tool error."


def _markdown_text(value: Any) -> str:
    """Prevent currency amounts from becoming accidental display-math spans."""

    return re.sub(r"(?<!\\)\$(?=\d)", r"\\$", str(value or ""))
