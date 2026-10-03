"""Reusable native Streamlit components for the analyst chat."""

from __future__ import annotations

import csv
from functools import partial
import hashlib
import io
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st

from data_analytics_agent.visualization.geocoding import (
    USLocationResolver,
)
from data_analytics_agent.visualization.renderer import build_chart
from data_analytics_agent.visualization.schemas import ChartSpec
from data_analytics_agent.ui.api_client import APIError, AgentAPIClient

FALLBACK_EXAMPLES = [
    {
        "label": "Summarize the available data",
        "question": (
            "What business entities and measures are available in this data source?"
        ),
    },
    {
        "label": "Count records by category",
        "question": (
            "Choose an important categorical field and show record counts "
            "for its top five values."
        ),
    },
]

REPORT_PREVIEW_HEIGHT = 900


def prose_markdown(text: str) -> str:
    """Keep dollar signs literal in business prose instead of enabling LaTeX."""
    return re.sub(r"(?<!\\)\$", r"\\$", text)


_PHASE_ICONS = {
    "info": ":material/info:",
    "started": ":material/pending:",
    "completed": ":material/check_circle:",
    "failed": ":material/error:",
    "waiting": ":material/pause_circle:",
    "cancelled": ":material/stop_circle:",
}


def _tool_identity(tool):
    return tool.get("invocation_id") or tool.get("call_id")


def consolidate_activity_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge append-only tool lifecycle events for compact display."""

    consolidated: list[dict[str, Any]] = []
    tool_indexes: dict[str, int] = {}
    for source in events:
        event = dict(source)
        tool = event.get("tool")
        call_id = _tool_identity(tool) if isinstance(tool, dict) else None
        if not call_id:
            consolidated.append(event)
            continue
        if call_id not in tool_indexes:
            tool_indexes[call_id] = len(consolidated)
            consolidated.append(event)
            continue
        existing = consolidated[tool_indexes[call_id]]
        existing_tool = existing.get("tool") or {}
        new_tool = tool or {}
        existing.update(
            {
                "label": event.get("label", existing.get("label")),
                "phase": event.get("phase", existing.get("phase")),
                "agent": event.get("agent") or existing.get("agent"),
                "created_at": event.get("created_at", existing.get("created_at")),
                "duration_ms": event.get("duration_ms", existing.get("duration_ms")),
            }
        )
        existing["tool"] = {
            **new_tool,
            "input": (
                existing_tool.get("input")
                if existing_tool.get("input") is not None
                else new_tool.get("input")
            ),
            "output": (
                new_tool.get("output")
                if event.get("phase") in {"completed", "failed"}
                else existing_tool.get("output")
            ),
        }
    return consolidated


def _agent_label(agent: str | None) -> str:
    return {
        "coordinator": "Coordinator",
        "text-to-sql": "Text-to-SQL",
        "data-visualization": "Visualization",
    }.get(agent or "", (agent or "Agent").replace("-", " ").title())


def _format_duration(milliseconds: int | float | None) -> str:
    value = max(0, float(milliseconds or 0))
    if value < 1000:
        return f"{round(value):,} ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.0f}s"


def _format_tokens(value: int | None) -> str:
    return f"{int(value or 0):,}"


def render_conversation_diagnostics_content(
    diagnostics: dict[str, Any],
) -> None:
    """Render aggregate diagnostics inside an existing container."""

    tokens = diagnostics.get("tokens") or {}
    partial = bool(diagnostics.get("token_usage_partial"))
    active = bool(diagnostics.get("has_active_run"))
    qualifier = "partial" if partial else "reported"
    state = " · active" if active else ""
    st.caption(
        f"{_format_tokens(tokens.get('total_tokens'))} tokens ({qualifier})"
        f" · {_format_duration(diagnostics.get('elapsed_ms'))} elapsed"
        f" · {int(diagnostics.get('run_count') or 0)} runs{state}"
    )
    st.caption(
        f"Active {_format_duration(diagnostics.get('active_ms'))} · "
        f"approval wait "
        f"{_format_duration(diagnostics.get('approval_wait_ms'))}"
    )


def render_conversation_diagnostics(
    diagnostics: dict[str, Any],
    *,
    key: str | None = None,
) -> None:
    """Render compact aggregate diagnostics beside conversation metadata."""

    with st.expander(
        "Conversation diagnostics",
        icon=":material/monitoring:",
        expanded=False,
        key=key,
    ):
        render_conversation_diagnostics_content(diagnostics)


def render_run_diagnostics_content(
    diagnostics: dict[str, Any],
    *,
    activities: list[dict[str, Any]] | None = None,
) -> None:
    """Render one run's diagnostics inside an existing container."""

    tokens = diagnostics.get("tokens") or {}
    partial = bool(diagnostics.get("token_usage_partial"))
    columns = st.columns(4)
    columns[0].metric(
        "Tokens",
        _format_tokens(tokens.get("total_tokens")),
        help="Provider-reported total across all model calls.",
    )
    columns[1].metric(
        "Elapsed",
        _format_duration(diagnostics.get("elapsed_ms")),
    )
    columns[2].metric(
        "Active",
        _format_duration(diagnostics.get("active_ms")),
    )
    columns[3].metric(
        "Approval wait",
        _format_duration(diagnostics.get("approval_wait_ms")),
    )
    details = [
        f"input {_format_tokens(tokens.get('input_tokens'))}",
        f"output {_format_tokens(tokens.get('output_tokens'))}",
        f"{int(diagnostics.get('model_calls') or 0)} model calls",
        f"{int(diagnostics.get('tool_calls') or 0)} tool calls",
    ]
    if tokens.get("cached_input_tokens") is not None:
        details.append(
            "cached input " + _format_tokens(tokens.get("cached_input_tokens"))
        )
    if tokens.get("reasoning_output_tokens") is not None:
        details.append(
            "reasoning output " + _format_tokens(tokens.get("reasoning_output_tokens"))
        )
    if partial:
        details.append("token total is partial")
    st.caption(" · ".join(details))

    agent_rows = []
    for agent in diagnostics.get("agents") or []:
        agent_tokens = agent.get("tokens") or {}
        agent_rows.append(
            {
                "Agent": _agent_label(agent.get("agent")),
                "Tokens": int(agent_tokens.get("total_tokens") or 0),
                "Model calls": int(agent.get("model_calls") or 0),
                "Model time": _format_duration(agent.get("model_ms")),
                "Max model call": _format_duration(agent.get("max_model_call_ms")),
                "Tool calls": int(agent.get("tool_calls") or 0),
                "Tool time": _format_duration(agent.get("tool_ms")),
            }
        )
    if agent_rows:
        st.markdown("**By agent**")
        st.dataframe(agent_rows, hide_index=True, width="stretch")

    tool_rows = []
    for event in consolidate_activity_events(activities or []):
        tool = event.get("tool") or {}
        duration_ms = event.get("duration_ms")
        if not tool.get("name") or duration_ms is None:
            continue
        tool_rows.append(
            {
                "Tool": str(tool["name"]),
                "Agent": _agent_label(event.get("agent")),
                "Status": str(event.get("phase") or "completed"),
                "Duration": _format_duration(duration_ms),
            }
        )
    if tool_rows:
        st.markdown("**Tool calls**")
        st.dataframe(tool_rows, hide_index=True, width="stretch")


def render_run_diagnostics(
    diagnostics: dict[str, Any],
    *,
    activities: list[dict[str, Any]] | None = None,
    key: str | None = None,
) -> None:
    """Render one bounded operational summary for a run."""

    with st.expander(
        "Run diagnostics",
        icon=":material/monitoring:",
        expanded=False,
        key=key,
    ):
        render_run_diagnostics_content(
            diagnostics,
            activities=activities,
        )


def render_debug_states(
    debug_states: list[dict[str, Any]],
    *,
    key_prefix: str,
) -> None:
    """Render trusted-local state snapshots supplied by the debug API."""

    if not debug_states:
        return
    with st.expander(
        "Agent state (debug)",
        icon=":material/bug_report:",
        expanded=False,
        type="compact",
        key=f"debug_state_{key_prefix}",
    ):
        st.warning(
            "Debug state may contain questions, SQL, model text, sampled "
            "business data, and unrecognized secrets.",
            icon=":material/security:",
        )
        for snapshot in debug_states:
            with st.container(border=True):
                st.markdown(f"**{_agent_label(snapshot.get('agent'))}**")
                namespace = snapshot.get("namespace") or []
                captured_at = snapshot.get("captured_at")
                metadata = " / ".join(str(item) for item in namespace)
                if not metadata:
                    metadata = "root namespace"
                if captured_at:
                    metadata = f"{metadata} · {captured_at}"
                st.caption(metadata)
                if snapshot.get("truncated"):
                    st.caption(
                        ":material/content_cut: Snapshot bounded for display · "
                        f"{snapshot.get('omitted_messages', 0)} messages and "
                        f"{snapshot.get('omitted_items', 0)} items omitted"
                    )
                st.json(snapshot.get("state") or {})


# Running, completed, and failed labels share one vocabulary across live/history views.
_ACTIVITY_LABELS = {
    "execute_sql": ("Retrieving data", "SQL query finished", "SQL query failed"),
    "query_saved_results": (
        "Transforming saved data",
        "Saved data transformed",
        "Saved-data query failed",
    ),
    "lookup_values": ("Looking up values", "Values loaded", "Value lookup failed"),
    "get_semantic_context": (
        "Loading business definitions",
        "Business definitions loaded",
        "Definition lookup failed",
    ),
    "browse_semantic_model": (
        "Exploring data catalog",
        "Data catalog reviewed",
        "Catalog lookup failed",
    ),
    "list_conversation_results": (
        "Finding saved datasets",
        "Saved datasets found",
        "Dataset lookup failed",
    ),
    "inspect_conversation_result": (
        "Reviewing saved dataset",
        "Saved dataset reviewed",
        "Dataset review failed",
    ),
    "execute_analysis_python": (
        "Analyzing data",
        "Python analysis finished",
        "Python analysis failed",
    ),
    "finish_analysis": (
        "Saving analysis findings",
        "Analysis findings saved",
        "Saving analysis failed",
    ),
    "list_conversation_analyses": (
        "Finding saved analyses",
        "Saved analyses found",
        "Analysis lookup failed",
    ),
    "inspect_conversation_analysis": (
        "Reviewing saved analysis",
        "Saved analysis reviewed",
        "Analysis review failed",
    ),
    "create_chart": ("Creating chart", "Chart saved", "Chart creation failed"),
    "create_report": ("Preparing report", "Report ready", "Report generation failed"),
    "publish_findings": ("Saving findings", "Findings saved", "Saving findings failed"),
    "save_investigation": (
        "Saving investigation progress",
        "Investigation progress saved",
        "Saving progress failed",
    ),
    "write_todos": (
        "Updating investigation plan",
        "Investigation plan updated",
        "Plan update failed",
    ),
    "request_clarification": (
        "Requesting clarification",
        "Clarification received",
        "Clarification failed",
    ),
    "read_file": (
        "Reading reference material",
        "Reference material loaded",
        "Reading reference failed",
    ),
    "ls": ("Listing reference files", "Reference files listed", "File listing failed"),
    "glob": ("Finding reference files", "Reference files found", "File search failed"),
    "grep": (
        "Searching reference material",
        "Reference search finished",
        "Reference search failed",
    ),
    "write_file": (
        "Saving working notes",
        "Working notes saved",
        "Saving notes failed",
    ),
    "edit_file": (
        "Updating working notes",
        "Working notes updated",
        "Updating notes failed",
    ),
}


def _activity_context(value):
    text = " ".join(str(value or "").split())
    return text[:177] + "…" if len(text) > 180 else text


def activity_label(event, *, source_id=None):
    tool = event.get("tool") or {}
    arguments = tool.get("input") or {}
    arguments = arguments if isinstance(arguments, dict) else {}
    name = tool.get("name")
    stage = {"completed": 1, "failed": 2}.get(event.get("phase"), 0)
    if name == "task":
        working = (
            "Retrieving data"
            if arguments.get("subagent_type") == "text-to-sql"
            else "Analyzing data"
        )
        label = (working, "Finished", "Assignment failed")[stage]
        detail = re.sub(
            r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b",
            "saved evidence",
            str(arguments.get("description") or ""),
        )
        detail = re.split(r"(?<=[.!?])\s", detail, maxsplit=1)[0]
    else:
        label = _ACTIVITY_LABELS.get(
            name, ("Working", "Work finished", "Operation failed")
        )[stage]
        detail = arguments.get("purpose")
        if name == "execute_sql" and source_id and stage == 0:
            label = f"Retrieving data from {source_id}"
        elif name == "lookup_values":
            detail = arguments.get("field_name")
        elif name == "create_chart":
            spec = arguments.get("spec")
            detail = spec.get("title") if isinstance(spec, dict) else None
        elif name == "read_file" and "report-design" in str(
            arguments.get("file_path", "")
        ):
            label = (
                "Loading report design instructions",
                "Report design instructions loaded",
                "Loading report instructions failed",
            )[stage]
    if event.get("phase") == "waiting":
        label = "Waiting for your input"
    elif event.get("phase") == "cancelled":
        label = "Stopped"
    detail = _activity_context(detail)
    return f"{label} · {detail}" if detail else label


_MODEL_RESPONSE_LABELS = {
    "execute_sql": "Reviewing retrieved data",
    "query_saved_results": "Reviewing transformed data",
    "lookup_values": "Reviewing source values",
    "get_semantic_context": "Reviewing business definitions",
    "browse_semantic_model": "Reviewing data catalog",
    "inspect_conversation_result": "Reviewing dataset evidence",
    "list_conversation_results": "Selecting saved datasets",
    "execute_analysis_python": "Reviewing analysis results",
    "finish_analysis": "Summarizing analysis findings",
    "inspect_conversation_analysis": "Reviewing analysis findings",
    "list_conversation_analyses": "Selecting saved analyses",
    "task": "Reviewing findings",
    "create_chart": "Reviewing chart results",
    "read_file": "Reviewing reference material",
    "write_todos": "Planning next investigation step",
    "save_investigation": "Planning next investigation step",
}


def _model_activity(events, consolidated, agent):
    """Describe observable inputs to the current model call, scoped to its assignment."""
    assignment = next(
        (
            event
            for event in reversed(consolidated)
            if event.get("phase") == "started"
            and (event.get("tool") or {}).get("name") == "task"
            and isinstance((event.get("tool") or {}).get("input"), dict)
            and event["tool"]["input"].get("subagent_type") == agent
        ),
        None,
    )
    brief = assignment["tool"]["input"].get("description") if assignment else None
    merged = {_tool_identity(event.get("tool") or {}): event for event in consolidated}
    recent = None
    # Raw completion order matters: parallel tools need not finish in start order.
    for event in reversed(events):
        call_id = _tool_identity(event.get("tool") or {})
        if assignment and call_id == _tool_identity(assignment["tool"]):
            break
        if event.get("agent") == agent and event.get("phase") in {
            "completed",
            "failed",
        }:
            recent = merged.get(call_id) if call_id else event
            break
    label = {
        "coordinator": "Preparing response",
        "text-to-sql": "Planning data retrieval",
        "data-analysis": "Planning analysis",
    }.get(agent, "Processing the request")
    detail = brief
    if recent:
        tool = recent.get("tool") or {}
        arguments = tool.get("input") or {}
        arguments = arguments if isinstance(arguments, dict) else {}
        if recent.get("phase") == "failed":
            label = f"Responding to error · {activity_label(recent)}"
        else:
            label = _MODEL_RESPONSE_LABELS.get(
                tool.get("name"), "Processing tool response"
            )
        detail = arguments.get("purpose") or brief
        if tool.get("name") == "task":
            detail = re.sub(
                r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b",
                "saved evidence",
                str(arguments.get("description") or ""),
            )
        elif tool.get("name") == "create_chart" and isinstance(
            arguments.get("spec"), dict
        ):
            detail = arguments["spec"].get("title")
    if detail and not (recent and recent.get("phase") == "failed"):
        label += f" · {_activity_context(detail)}"
    return label


def current_activity(
    events,
    *,
    status="running",
    findings=False,
    active_model_agent=None,
    report_ready=False,
    approval=None,
    source_id=None,
):
    if status == "approval_required":
        languages = {
            "Python" if action["review_type"] == "python" else "SQL"
            for action in (approval or {}).get("actions", [])
        }
        language = " and ".join(sorted(languages)) or "execution"
        return f"Waiting for {language} review"
    if status in {
        "paused",
        "stopping",
        "failed",
        "clarification_required",
        "queued",
        "completed",
    }:
        return {
            "clarification_required": "Waiting for your clarification",
            "queued": "Waiting to start",
            "paused": "Paused",
            "stopping": "Stopping work",
            "failed": (
                "Report ready · Finalizing answer failed"
                if report_ready
                else "Findings saved · Report generation failed"
                if findings
                else "Run failed"
            ),
            "completed": "Complete",
        }[status]
    consolidated = consolidate_activity_events(events)
    pending = [e for e in consolidated if e.get("phase") == "started"]
    analyses = [
        e
        for e in pending
        if (e.get("tool") or {}).get("name") == "task"
        and isinstance((e.get("tool") or {}).get("input"), dict)
        and ((e.get("tool") or {}).get("input") or {}).get("subagent_type")
        == "data-analysis"
    ]
    leaves = [e for e in pending if (e.get("tool") or {}).get("name") != "task"]
    if len(analyses) > 1:
        label = f"Analyzing data · {len(analyses)} analyses running"
    elif leaves:
        event = leaves[-1]
        label = activity_label(event, source_id=source_id)
    elif active_model_agent:
        label = _model_activity(events, consolidated, active_model_agent)
    elif pending:
        label = activity_label(pending[-1], source_id=source_id)
    else:
        label = "Preparing next step" if events else "Understanding the request"
    if findings:
        if not leaves:
            label = "Finalizing answer" if report_ready else "Preparing report"
        return f"Findings saved · {label}"
    return label


def render_analysis_plan(events, *, key, completed=False, partial=False):
    """Keep active plans visible and completed-turn plans available on demand."""
    steps = consolidate_activity_events(events)
    plans = [
        e
        for e in steps
        if (e.get("tool") or {}).get("name") == "write_todos"
        and e.get("agent") == "coordinator"
        and e.get("phase") == "completed"
    ]
    if not plans:
        return
    plan_input = plans[-1]["tool"].get("input") or {}
    todos = plan_input.get("todos", []) if isinstance(plan_input, dict) else []
    todos = [todo for todo in todos if isinstance(todo, dict) and todo.get("content")]
    if not todos:
        return
    if completed:
        label = (
            "Analysis complete · View steps"
            if not partial and all(todo.get("status") == "completed" for todo in todos)
            else "Analysis plan · View steps"
        )
        panel = st.expander(
            label,
            expanded=False,
            type="compact",
            key=f"completed_plan_{key}",
            on_change="rerun",
        )
        if not panel.open:
            return
    else:
        panel = st.container()
    with panel:
        if not completed:
            st.markdown("**Analysis plan**")
        icons = {
            "completed": ":material/check_circle:",
            "in_progress": ":material/pending:",
            "pending": ":material/radio_button_unchecked:",
        }
        for todo in todos:
            state = todo.get("status", "pending")
            content = prose_markdown(todo["content"])
            if state == "in_progress" and not completed:
                content = f"**{content}**"
            st.markdown(
                f"{icons.get(state, icons['pending'])} {content} · {state.replace('_', ' ')}"
            )


def render_activity(events, diagnostics, *, key, completed=False, partial=False):
    render_analysis_plan(events, key=key, completed=completed, partial=partial)
    panel = st.expander("Activity", key=f"activity_turn_{key}", on_change="rerun")
    if panel.open:
        with panel:
            render_activity_timeline(events, key_prefix=key)
            diagnostics_panel = st.expander(
                "Developer diagnostics", key=f"diagnostics_{key}", on_change="rerun"
            )
            if diagnostics_panel.open:
                with diagnostics_panel:
                    render_run_diagnostics_content(diagnostics, activities=events)


def render_activity_timeline(
    events: list[dict[str, Any]],
    *,
    debug_states: list[dict[str, Any]] | None = None,
    key_prefix: str,
) -> None:
    """Render one compact activity timeline for live and completed runs."""

    consolidated = consolidate_activity_events(events)
    tool_totals: dict[str, int] = {}
    for event in consolidated:
        tool = event.get("tool") or {}
        name = tool.get("name")
        if name:
            tool_totals[name] = tool_totals.get(name, 0) + 1
    tool_seen: dict[str, int] = {}

    for event in consolidated:
        phase = str(event.get("phase") or "info")
        icon = _PHASE_ICONS.get(phase, ":material/info:")
        label = activity_label(event)
        agent = _agent_label(event.get("agent"))
        duration = (
            f" · {_format_duration(event.get('duration_ms'))}"
            if event.get("duration_ms") is not None
            else ""
        )
        st.caption(f"{icon} {label} · {agent}{duration}")

        tool = event.get("tool") or {}
        if not tool:
            continue
        tool_input = tool.get("input")
        tool_output = tool.get("output")
        tool_name = str(tool.get("name") or "tool")
        tool_seen[tool_name] = tool_seen.get(tool_name, 0) + 1
        ordinal = (
            f" · call {tool_seen[tool_name]}"
            if tool_totals.get(tool_name, 0) > 1
            else ""
        )
        event_key = _tool_identity(tool) or event.get("id") or len(tool_seen)
        with st.expander(
            f"{label if tool_name == 'task' else tool_name}{ordinal}",
            icon=":material/build:",
            expanded=False,
            type="compact",
            key=f"activity_{key_prefix}_{event_key}",
        ):
            if tool_name == "task" and isinstance(tool_input, dict):
                st.markdown("**Specialist assignment**")
                st.text(str(tool_input.get("description") or "No assignment recorded."))
            st.caption("Input · bounded and recognized-secret-key-redacted")
            if tool_input is None:
                st.caption("This tool call has no input.")
            else:
                st.json(tool_input)

            if phase == "started":
                st.caption(":material/pending: Waiting for tool output…")
            else:
                st.caption("Output · bounded and recognized-secret-key-redacted")
                if tool_output is None:
                    st.caption("The tool returned no value.")
                else:
                    st.json(tool_output)

    render_debug_states(
        debug_states or [],
        key_prefix=key_prefix,
    )


def conversation_url(app_base_url: str, thread_id: str) -> str:
    """Build a refresh-safe conversation URL without duplicating parameters."""

    parts = urlsplit(app_base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["thread_id"] = thread_id
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", urlencode(query), "")
    )


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Serialize result rows in the exact API column order."""

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def sql_review_decision(
    generated_sql: str,
    reviewed_sql: str,
) -> dict[str, Any]:
    """Translate the authoritative editor contents to the existing API shape."""

    if reviewed_sql == generated_sql:
        return {"action": "approve"}
    return {"action": "edit", "edited_sql": reviewed_sql}


def python_review_decision(
    generated_python: str,
    reviewed_python: str,
) -> dict[str, Any]:
    """Translate authoritative Python editor contents to the API shape."""

    if reviewed_python == generated_python:
        return {"action": "approve"}
    return {"action": "edit", "edited_python": reviewed_python}


def _reset_review_editor(editor_key: str, generated_code: str) -> None:
    st.session_state[editor_key] = generated_code


@st.cache_resource
def _us_location_resolver() -> USLocationResolver:
    return USLocationResolver()


def render_page_header(source: dict[str, Any] | None = None) -> None:
    st.caption(":material/query_stats: CONVERSATIONAL ANALYTICS")
    source_name = source["name"] if source else "your data"
    source_anchor = f"ask-questions-about-{source['source_id']}" if source else False
    st.title(
        f"Ask questions about {source_name}",
        anchor=source_anchor,
    )
    st.caption(
        "Saved evidence supports iterative analysis. SQL and analytical Python are reviewed "
        "when review is enabled."
    )


def render_sidebar(
    *,
    thread_id: str,
    app_base_url: str,
    health: dict[str, Any] | None,
    health_error: str | None,
    data_sources: dict[str, Any],
    source_switch_disabled: bool,
    diagnostics: dict[str, Any],
) -> tuple[bool, Any]:
    """Render app-level metadata and return whether New conversation was used."""

    with st.sidebar:
        st.title("Data Analytics Agent")
        st.caption(
            "Approval-configurable SQL and analytical Python, automatic "
            "constrained charts, semantic grounding, and durable local "
            "conversation state."
        )
        ready_sources = [
            source
            for source in data_sources["sources"]
            if source["ready"]
            or (
                source["backend_type"] == "upload"
                and source["source_id"] == st.session_state.get("source_selector")
            )
        ]
        ready_by_id = {source["source_id"]: source for source in ready_sources}
        st.selectbox(
            "Data source",
            options=list(ready_by_id),
            format_func=lambda source_id: ready_by_id[source_id]["name"],
            key="source_selector",
            disabled=source_switch_disabled,
            help=(
                "A conversation is permanently bound to one source. Changing "
                "this selection starts a new conversation."
            ),
        )
        selected_source = ready_by_id[st.session_state["source_selector"]]
        st.caption(selected_source["description"])
        st.badge(
            f"{selected_source['backend_type']} · {selected_source['dialect']}",
            icon=":material/storage:",
            color="blue",
        )
        if source_switch_disabled:
            st.caption(
                "The data source cannot change while a run or SQL review is active."
            )

        new_conversation = st.button(
            "New conversation",
            icon=":material/add_comment:",
            type="primary",
            width="stretch",
            disabled=selected_source["backend_type"] == "upload",
            help="Use Upload a file to start a separate file conversation."
            if selected_source["backend_type"] == "upload"
            else None,
        )

        if health_error:
            st.error(health_error, icon=":material/cloud_off:")
        elif health and health["status"] == "ok":
            st.badge(
                f"API ready · {health['model']}",
                icon=":material/check_circle:",
                color="green",
            )
            st.caption(
                "SQL execution · "
                + (
                    "review required"
                    if health.get("sql_approval_required")
                    else "automatic"
                )
            )
            st.caption(
                "Python analysis · "
                + (
                    "review required"
                    if health.get("python_approval_required")
                    else "automatic"
                )
            )
        elif health:
            st.warning("API setup incomplete", icon=":material/warning:")
            for error in health.get("errors", []):
                st.caption(error)

        unavailable = [
            source for source in data_sources["sources"] if not source["ready"]
        ]
        if unavailable:
            with st.expander(
                f"Unavailable sources ({len(unavailable)})",
                icon=":material/warning:",
                expanded=False,
            ):
                for source in unavailable:
                    st.markdown(f"**{source['name']}**")
                    for error in source.get("errors", []):
                        st.caption(error)
        source_warnings = selected_source.get("warnings") or []
        if source_warnings:
            with st.expander(
                "Source warnings",
                icon=":material/info:",
                expanded=False,
            ):
                for warning in source_warnings:
                    st.caption(warning)

        st.caption(f"Conversation · `{thread_id[:8]}`")
        # Keep the shell mounted while polling replaces only its contents so
        # an open diagnostics panel does not collapse on every update.
        with st.expander(
            "Conversation diagnostics",
            icon=":material/monitoring:",
            expanded=False,
            key=f"conversation_diagnostics_{thread_id}",
        ):
            diagnostics_slot = st.empty()
            with diagnostics_slot.container():
                render_conversation_diagnostics_content(diagnostics)
        with st.expander(
            "Technical details",
            icon=":material/info:",
            expanded=False,
        ):
            st.caption(
                "The URL stores routing state so refresh, bookmarking, and "
                "duplicate-tab workflows return to this conversation."
            )
            st.markdown("**Conversation ID**")
            st.code(thread_id, language=None)
            st.markdown("**Conversation link**")
            st.code(
                conversation_url(app_base_url, thread_id),
                language=None,
            )
            st.caption(
                "Conversations and saved artifacts remain available after restart. "
                "Unfinished work waits for Resume."
            )
        return new_conversation, diagnostics_slot


def _prefill_chat_input(
    selector_key: str,
    chat_input_key: str,
    question_by_label: dict[str, str],
) -> None:
    """Copy one selected example into the composer without submitting it."""

    selection = st.session_state.get(selector_key)
    if selection in question_by_label:
        st.session_state[chat_input_key] = question_by_label[selection]


def render_empty_state(
    thread_id: str,
    source: dict[str, Any],
    *,
    chat_input_key: str,
) -> None:
    examples = source.get("examples") or FALLBACK_EXAMPLES
    question_by_label = {
        f":material/lightbulb: {item['label']}": item["question"] for item in examples
    }
    with st.container(border=True):
        st.subheader(
            "Start with a business question",
            anchor=False,
        )
        st.caption(
            "Choose an example to place it in the chat box, then edit or send "
            "it. Every result retains its exact validated SQL and provenance."
        )
        selector_key = f"starter_question_{thread_id}"
        st.pills(
            "Example questions",
            options=list(question_by_label),
            key=selector_key,
            label_visibility="collapsed",
            width="stretch",
            on_change=_prefill_chat_input,
            args=(selector_key, chat_input_key, question_by_label),
        )


@st.cache_data(max_entries=128, show_spinner=False)
def _saved_result(base_url: str, result_id: str, limit: int = 100):
    return AgentAPIClient(base_url).get_result(result_id, limit=limit)


@st.cache_data(max_entries=32, show_spinner=False)
def _saved_report(base_url: str, report_id: str):
    return AgentAPIClient(base_url).get_report(report_id)


def clear_artifact_cache() -> None:
    _saved_result.clear()
    _saved_report.clear()


_DATASET_KIND_LABELS = {
    "upload": "Uploaded file",
    "source_sql": "Source SQL",
    "saved_sql": "SQL over saved datasets",
    "python": "Python-derived dataset",
    "presentation": "Chart data",
}


def chart_preparation_summary(result):
    preparation = result.get("chart_preparation")
    if not preparation:
        return "Chart preparation details were not recorded for this dataset."
    before, after = preparation["input_row_count"], preparation["output_row_count"]
    columns = ", ".join(preparation["selected_columns"])
    method = preparation["sampling"]
    if method == "none":
        operation = f"Kept all {before:,} rows"
    elif method == "ordered_stride":
        operation = (
            f"Kept {after:,} of {before:,} rows, ordered by {preparation['order_by']}, "
            f"taking every {preparation['stride']} rows and the last row"
        )
    else:
        operation = f"Sampled {after:,} of {before:,} rows using reservoir sampling (seed {preparation['seed']})"
    return f"{operation}; selected columns: {columns}."


def _render_dataset_table(client, result, *, preview_rows=10):
    rows = result["rows"][:preview_rows]
    if rows:
        st.dataframe(
            rows,
            column_order=result["columns"],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("This saved dataset contains no rows.")
    st.caption(f"Preview: {len(rows)} of {result['row_count']:,} saved rows.")
    with st.container(horizontal=True):
        st.link_button(
            "Download full CSV", client.dataset_download_url(result["result_id"])
        )
        st.link_button(
            "Download full Parquet",
            client.dataset_download_url(result["result_id"], "parquet"),
        )


@st.dialog("Dataset inspector", width="large")
def _dataset_inspector(client, result_id, executions, initial_view="Data"):
    # Walk immutable same-source parents only when the user opens the inspector.
    datasets, pending = {}, [result_id]
    while pending:
        key = pending.pop(0)
        if key in datasets:
            continue
        try:
            item = _saved_result(client.base_url, key, 1)
        except APIError as exc:
            st.warning(f"An input dataset is unavailable: {exc}")
            continue
        datasets[key] = item
        pending.extend(
            parent for parent in item["parent_result_ids"] if parent not in datasets
        )
    if not datasets:
        return
    selected = st.selectbox(
        "Dataset and its inputs",
        list(datasets),
        format_func=lambda key: (
            f"{datasets[key]['short_label']} · {_DATASET_KIND_LABELS[datasets[key]['kind']]}"
        ),
        key=f"inspect_dataset_{result_id}",
    )
    view = st.segmented_control(
        "View",
        ["Data", "Source"],
        default=initial_view,
        selection_mode="single",
        key=f"inspect_view_{result_id}_{initial_view}",
    )
    try:
        result = _saved_result(client.base_url, selected, 100)
    except APIError as exc:
        st.warning(f"Saved data is unavailable: {exc}")
        return
    if result["truncated"]:
        st.warning(
            "The source extraction is incomplete. This dataset does not represent the full population."
        )
    if view == "Data":
        _render_dataset_table(client, result, preview_rows=100)
    else:
        render_dataset_provenance(
            result, executions=executions, client=client, navigate=False
        )


def render_dataset_provenance(
    result, *, executions=None, client=None, widget_key="dataset", navigate=True
):
    """Explain the producer and expose named inputs with technical IDs out of the way."""
    kind = result["kind"]
    st.markdown(f"**Source · {_DATASET_KIND_LABELS[kind]}**")
    st.caption(f"Data source · {result['source_id']}")
    if provenance := result.get("upload_provenance"):
        st.caption(
            "Source freshness is unknown. The file hash identifies the uploaded bytes."
        )
        st.json(provenance)
    if kind == "presentation":
        st.caption(chart_preparation_summary(result))
    elif result.get("originating_question"):
        st.caption(f"Originating question · {result['originating_question']}")
    parents = result.get("parent_result_ids") or []
    if parents:
        st.markdown("**Based on**")
        for parent in parents:
            if client is None:
                continue
            try:
                metadata = _saved_result(client.base_url, parent, 1)
            except APIError as exc:
                st.warning(f"Input dataset unavailable: {exc}")
                continue
            label = (
                f"{metadata['short_label']} · {_DATASET_KIND_LABELS[metadata['kind']]}"
            )
            if navigate:
                if st.button(
                    label, key=f"parent_{widget_key}_{parent}", type="tertiary"
                ):
                    _dataset_inspector(client, parent, executions)
                if st.button(
                    "View source SQL"
                    if metadata["kind"] in {"source_sql", "saved_sql"}
                    else "View source",
                    key=f"source_{widget_key}_{parent}",
                ):
                    _dataset_inspector(client, parent, executions, "Source")
            else:
                st.caption(label)
    if kind in {"source_sql", "saved_sql"}:
        if result.get("executed_sql"):
            st.markdown("**Executed SQL**")
            st.code(result["executed_sql"], language="sql")
        else:
            st.caption("Executed SQL was not recorded for this dataset.")
    elif kind == "python":
        execution = (executions or {}).get(result.get("execution_id")) or {}
        if not execution and client:
            try:
                execution = client.get_dataset_python_source(result["result_id"])
            except APIError:
                st.warning("The recorded Python source could not be loaded.")
        if execution.get("executed_python"):
            st.markdown("**Executed Python**")
            st.code(execution["executed_python"], language="python")
        else:
            st.caption(
                "The Python code for this dataset is not attached to these findings."
            )
    with st.expander("Technical details"):
        st.json(
            {
                "dataset_id": result["result_id"],
                "input_dataset_ids": parents,
                "execution_id": result.get("execution_id"),
                "chart_preparation": result.get("chart_preparation"),
            }
        )


def _render_result(
    client: AgentAPIClient,
    result_id: str,
    *,
    widget_key: str,
    source_id: str,
    chart: dict[str, Any] | None = None,
    expanded: bool = False,
    executions: dict[str, dict[str, Any]] | None = None,
    show_evidence: bool = True,
) -> None:
    try:
        result = _saved_result(client.base_url, result_id, 5000 if chart else 10)
    except APIError as exc:
        st.warning(
            f"Saved result is unavailable: {exc}",
            icon=":material/warning:",
        )
        return

    with st.container(
        horizontal=True,
        vertical_alignment="center",
        gap="xsmall",
    ):
        row_label = f"{result['row_count']} row"
        if result["row_count"] != 1:
            row_label += "s"
        st.badge(row_label, icon=":material/table_rows:", color="blue")
        st.badge(
            f"{result['elapsed_ms']:.1f} ms",
            icon=":material/timer:",
            color="gray",
        )
        if result["truncated"]:
            st.badge(
                "Result capped",
                icon=":material/content_cut:",
                color="orange",
            )
            st.warning(
                f"Showing and charting the first {result['row_count']} stored "
                "rows because the configured retrieval cap was reached. "
                "The complete database result may contain additional rows.",
                icon=":material/content_cut:",
            )

    evidence_label = (
        f"{result['short_label'] or 'Saved dataset'} · "
        f"{_DATASET_KIND_LABELS[result['kind']]} · Data and provenance"
    )

    if chart and result["rows"]:
        try:
            spec = ChartSpec.model_validate(chart)
            if spec.result_id != result_id:
                raise ValueError("The chart does not reference this saved result.")
            rendered = build_chart(
                spec,
                result["rows"],
                resolver=_us_location_resolver(),
            )
            st.plotly_chart(
                rendered.figure,
                width="stretch",
                theme="streamlit",
                key=f"chart_{result_id}_{widget_key}",
                config={
                    "displaylogo": False,
                    "responsive": True,
                    "toImageButtonOptions": {
                        "format": "png",
                        "filename": f"chart-{result_id[:8]}",
                        "scale": 2,
                    },
                },
            )
            for warning in rendered.warnings:
                st.warning(warning, icon=":material/warning:")
            for note in rendered.notes:
                st.caption(note)
        except Exception as exc:
            st.warning(
                f"The generated chart could not be rendered: {exc}",
                icon=":material/warning:",
            )
    if not show_evidence:
        if st.button("View chart data", key=f"inspect_{widget_key}_{result_id}"):
            _dataset_inspector(client, result_id, executions)
        return
    panel = st.expander(
        evidence_label,
        icon=":material/table_chart:",
        expanded=expanded,
        key=f"evidence_{widget_key}_{result_id}",
        on_change="rerun",
    )
    if panel.open:
        with panel:
            if st.button(
                "View chart data" if chart else "Open dataset inspector",
                key=f"inspect_{widget_key}_{result_id}",
            ):
                _dataset_inspector(client, result_id, executions)
            _render_dataset_table(client, result)
            render_dataset_provenance(
                result, executions=executions, client=client, widget_key=widget_key
            )


def _render_report(
    client: AgentAPIClient,
    reference: dict[str, Any],
    *,
    widget_key: str,
) -> None:
    """Preview and download the exact trusted self-contained report bytes."""

    report_id = str(reference.get("report_id") or "")
    try:
        report = _saved_report(client.base_url, report_id)
    except APIError as exc:
        st.warning(
            f"Saved report is unavailable: {exc}",
            icon=":material/warning:",
        )
        return

    html = str(report.get("html") or "")
    actual_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    expected_hash = str(reference.get("html_sha256") or "")
    if actual_hash != expected_hash or actual_hash != report.get("html_sha256"):
        st.error(
            "The report content hash does not match its stored reference.",
            icon=":material/security:",
        )
        return

    with st.container(border=True):
        with st.container(
            horizontal=True,
            vertical_alignment="center",
            gap="small",
        ):
            st.badge(
                f"Report v{report['version']}",
                icon=":material/article:",
                color="blue",
            )
            st.caption(str(report["title"]))
        with st.container(horizontal=True, gap="small"):
            st.link_button(
                "Open full report",
                client.report_view_url(report_id),
                icon=":material/open_in_new:",
                width="content",
            )
            st.download_button(
                "Download HTML report",
                data=html.encode("utf-8"),
                file_name=(f"report-{report_id[:8]}-v{report['version']}.html"),
                mime="text/html",
                icon=":material/download:",
                on_click="ignore",
                width="content",
                key=f"download_report_{report_id}_{widget_key}",
            )
        preview = st.expander(
            "Report preview",
            icon=":material/preview:",
            expanded=True,
            key=f"report_preview_{report_id}_{widget_key}",
            on_change="rerun",
        )
        if preview.open:
            with preview:
                st.iframe(
                    html,
                    width="stretch",
                    height=REPORT_PREVIEW_HEIGHT,
                    tab_index=0,
                )


def render_turn(
    client: AgentAPIClient,
    turn: dict[str, Any],
    *,
    turn_key: str,
    source_id: str,
) -> None:
    with st.chat_message("user"):
        st.markdown(prose_markdown(turn["user_message"]))

    for correction in turn.get("corrections") or []:
        with st.chat_message("user"):
            st.markdown(prose_markdown(correction["message"]))
    turn_key = turn.get("run_id") or turn_key
    with st.chat_message("assistant", avatar=":material/query_stats:"):
        render_activity(
            turn.get("activities") or [],
            turn.get("diagnostics") or {},
            key=turn_key,
            completed=True,
            partial=bool(turn["answer"].get("partial")),
        )
        render_answer(client, turn["answer"], turn_key=turn_key, source_id=source_id)


def render_answer(
    client, answer, *, turn_key, source_id, analysis_download_available=True
):
    if answer.get("analytical_input"):
        from data_analytics_agent.analytical_scope import AnalyticalInput, scope_description

        st.caption(scope_description(AnalyticalInput.model_validate(answer["analytical_input"])))
        if answer.get("source_expansion_allowed"):
            st.caption("Additional source retrieval was authorized. The selected snapshot is the starting population; see the attached evidence for the resulting populations.")
    if answer.get("refreshed_from_report_id"):
        st.caption("Refreshed from the warehouse. This answer uses a new source snapshot.")
    st.markdown(prose_markdown(answer["answer"]))
    executions = {
        execution["execution_id"]: execution
        for analysis in answer.get("analyses") or []
        for execution in analysis.get("executions") or []
    }

    assumptions = answer.get("assumptions") or []
    if assumptions:
        with st.expander("Assumptions", expanded=False):
            for assumption in assumptions:
                st.markdown(prose_markdown(f"- {assumption}"))

    if answer.get("partial"):
        st.warning("Partial findings — the investigation is unfinished.")
    for question in answer.get("unresolved_questions") or []:
        st.caption(f"Still to investigate: {question}")
    for warning in dict.fromkeys(
        note
        for analysis in answer.get("analyses") or []
        for note in analysis.get("warnings") or []
    ):
        st.warning(prose_markdown(warning))
    for index, analysis in enumerate(answer.get("analyses") or []):
        _render_data_analysis(analysis, client=client, widget_key=f"{turn_key}_{index}")
    shown_result_ids = set()
    for index, chart in enumerate(answer.get("charts") or []):
        if (
            chart["result_id"] == answer.get("primary_result_id")
            and chart["result_id"] not in shown_result_ids
        ):
            st.badge("Primary evidence", icon=":material/bookmark:", color="blue")
        _render_result(
            client,
            chart["result_id"],
            widget_key=f"{turn_key}_chart_{index}",
            source_id=source_id,
            chart=chart,
            executions=executions,
            show_evidence=chart["result_id"] not in shown_result_ids,
        )
        shown_result_ids.add(chart["result_id"])
        if answer.get("report"):
            with st.popover(
                "Edit chart",
                icon=":material/edit:",
                key=f"edit_chart_{turn_key}_{chart['chart_id']}",
            ):
                _render_chart_editor(client, turn_key, answer["report"], chart)

    report = answer.get("report")
    if report:
        with st.popover(
            "Edit report title",
            icon=":material/edit:",
            key=f"report_title_{turn_key}_{report['report_id']}",
        ):
            with st.form(f"report_title_form_{turn_key}_{report['report_id']}"):
                title = st.text_input(
                    "Report title", value=report["title"], max_chars=200
                )
                save = st.form_submit_button("Save title")
            if save:
                try:
                    client.edit_report_title(turn_key, report["report_id"], title)
                except APIError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        with st.expander(
            "Download data and calculations", icon=":material/folder_zip:"
        ):
            st.caption(
                "For sharing or checking the work: saved data, SQL queries, Python code, notebook and this report in one ZIP."
            )
            st.caption(
                "This package uses the data already analyzed. It does not refresh the source. Replaying calculations requires Python; opening the HTML report only needs a browser."
            )
            st.download_button(
                "Download analysis ZIP",
                data=partial(client.download_analysis, turn_key, report["report_id"]),
                file_name=f"analysis-{turn_key[:8]}.zip",
                mime="application/zip",
                icon=":material/download:",
                on_click="ignore",
                disabled=not analysis_download_available,
                key=f"analysis_download_{turn_key}_{report['report_id']}",
                help="The ZIP is prepared when you click. The button shows progress while the file is prepared.",
            )
            if not analysis_download_available:
                st.caption(
                    "The analysis ZIP will be available when this answer is complete."
                )
        _render_report(
            client,
            report,
            widget_key=turn_key,
        )

    results = answer.get("results") or []
    evidence_index = 0
    for index, reference in enumerate(results):
        result_id = str(reference.get("result_id") or "")
        if result_id in shown_result_ids:
            continue
        shown_result_ids.add(result_id)
        evidence_index += 1
        label = str(reference.get("short_label") or "Saved dataset").strip()
        st.markdown(f"**Evidence {evidence_index} · {label}**")
        if result_id == answer.get("primary_result_id"):
            st.badge(
                "Primary evidence",
                icon=":material/bookmark:",
                color="blue",
            )
        _render_result(
            client,
            result_id,
            widget_key=f"{turn_key}_{index}",
            source_id=source_id,
            executions=executions,
            expanded=evidence_index == 1,
        )


def _render_chart_editor(client, run_id, report, chart):
    from data_analytics_agent.visualization.schemas import ChartType, Palette

    st.caption("Save a new chart and report version using the existing data.")
    with st.form(f"chart_edit_{run_id}_{report['report_id']}_{chart['chart_id']}"):
        title = st.text_input("Chart title", value=chart["title"], max_chars=160)
        x_label = st.text_input(
            "X-axis label", value=chart.get("x_label") or "", max_chars=80
        )
        y_label = st.text_input(
            "Y-axis label", value=chart.get("y_label") or "", max_chars=80
        )
        types = [item.value for item in ChartType]
        chart_type = st.selectbox(
            "Chart type", types, index=types.index(chart["chart_type"])
        )
        palettes = [item.value for item in Palette]
        palette = st.selectbox(
            "Colors", palettes, index=palettes.index(chart.get("palette", "default"))
        )
        st.caption(
            "Chart types must fit the saved columns and data. Unsupported changes keep the current version."
        )
        save = st.form_submit_button("Save chart and report", type="primary")
    if save:
        if not title.strip():
            st.error("Enter a chart title.")
            return
        try:
            with st.spinner("Updating chart and report…"):
                client.edit_chart(
                    run_id,
                    {
                        "report_id": report["report_id"],
                        "chart_id": chart["chart_id"],
                        "title": title,
                        "x_label": x_label or None,
                        "y_label": y_label or None,
                        "chart_type": chart_type,
                        "palette": palette,
                    },
                )
        except APIError as exc:
            st.error(str(exc))
            return
        st.rerun()


def _render_data_analysis(
    analysis: dict[str, Any], *, client: AgentAPIClient, widget_key: str
) -> None:
    st.badge(
        str(analysis.get("outcome", "analysis")).replace("_", " "),
        icon=":material/functions:",
    )
    if analysis.get("forecast_evaluation"):
        from data_analytics_agent.forecasting import ForecastEvaluation

        forecast = ForecastEvaluation.model_validate(analysis["forecast_evaluation"])
        st.caption(forecast.description)
        for note in forecast.warnings:
            st.caption(note)
        scores = client.get_result(forecast.scores_result_id, limit=10)
        st.dataframe(scores["rows"], hide_index=True, key=f"forecast_scores_{widget_key}")
    with st.expander("Analysis methods, outputs, and executed Python", expanded=False):
        st.markdown(prose_markdown(analysis.get("method") or ""))
        for note in (analysis.get("assumptions") or []) + (
            analysis.get("warnings") or []
        ):
            st.caption(note)
        for index, execution in enumerate(analysis.get("executions") or []):
            st.markdown(f"**Execution {index + 1}**")
            st.code(execution.get("executed_python") or "", language="python")
            st.json(
                {
                    "inputs": execution.get("inputs"),
                    "derived datasets": execution.get("output_datasets"),
                }
            )
            if execution.get("error"):
                st.warning(execution["error"])
            for j, output in enumerate(execution.get("outputs") or []):
                st.caption(output.get("name") or "Output")
                if output.get("kind") == "table":
                    st.dataframe(
                        output.get("rows") or [],
                        hide_index=True,
                        key=f"analysis_{widget_key}_{index}_{j}",
                    )
                elif output.get("kind") == "figure" and output.get("image_path"):
                    from pathlib import Path

                    st.image(
                        f"{client.base_url}/api/figures/{Path(output['image_path']).name}"
                    )
                else:
                    st.write(output.get("text") or output.get("value"))
            for warning in execution.get("warnings") or []:
                st.caption(warning)


def render_pending_user_message(question: str) -> None:
    with st.chat_message("user"):
        st.markdown(prose_markdown(question))


def review_decisions(actions, choices, reviewed_code, feedback):
    """Build an ordered batch only when every proposal has a valid decision."""
    decisions = []
    for action, choice, code, message in zip(
        actions, choices, reviewed_code, feedback, strict=True
    ):
        if choice == "Request changes":
            if not message.strip():
                raise ValueError("Add feedback for each proposal you want revised.")
            decision = {"action": "reject", "feedback": message.strip()}
        elif choice == "Run reviewed code":
            if not code.strip():
                raise ValueError("Reviewed code cannot be empty.")
            build = (
                python_review_decision
                if action["review_type"] == "python"
                else sql_review_decision
            )
            decision = build(action["query"], code)
        else:
            raise ValueError("Choose a decision for every proposal.")
        if decision["action"] not in action["allowed_decisions"]:
            raise ValueError(
                "This proposal does not allow that decision. Review the permitted choices."
            )
        decisions.append(decision)
    return decisions


def render_approval(
    run: dict[str, Any],
    *,
    revision_feedback: str | None = None,
) -> list[dict[str, Any]] | None:
    """Review all actions in one interrupt before resuming any of them."""
    approval = run["approval"]
    actions = approval["actions"]
    cycle_key = hashlib.sha256(approval["interrupt_id"].encode()).hexdigest()[:10]
    with st.container(border=True):
        st.subheader("Review proposals before execution", anchor=False)
        st.warning(
            "These proposals have not been executed yet.", icon=":material/security:"
        )
        if any(action["review_type"] == "python" for action in actions):
            st.caption(
                "Approved Python runs with the local API service's file and process access."
            )
        if revision_feedback:
            st.success(
                "Revised proposals are ready for review.",
                icon=":material/check_circle:",
            )
            st.caption(f"Your feedback: {revision_feedback}")
        st.caption(
            "Choose a decision for each proposal, then apply them together. Edited code runs exactly as shown."
        )
        summary = st.empty()
        decisions = []
        for index, action in enumerate(actions):
            with st.container(border=True):
                language = "Python" if action["review_type"] == "python" else "SQL"
                item_key = f"{run['run_id']}_{cycle_key}_{index}"
                st.markdown(f"**{language} proposal {index + 1} of {len(actions)}**")
                purpose = action["arguments"].get("purpose")
                st.write(
                    prose_markdown(
                        purpose
                        or (
                            "Analyze the saved datasets listed below."
                            if language == "Python"
                            else "Calculate from saved data."
                            if action["action_name"] == "query_saved_results"
                            else "Retrieve data for your question."
                        )
                    )
                )
                if language == "Python":
                    for alias, item in action["input_datasets"].items():
                        st.caption(
                            f"{alias}: {item['row_count']:,} saved rows · "
                            + (
                                "incomplete extraction"
                                if item["truncated"]
                                else "complete extraction"
                            )
                        )
                        with st.expander(f"View data used: {alias}"):
                            st.markdown(prose_markdown(item["originating_question"]))
                            st.write("Columns: " + ", ".join(item["columns"]))
                            if item["executed_sql"]:
                                st.code(item["executed_sql"], language="sql")
                            if item["sample_rows"]:
                                st.dataframe(item["sample_rows"][:10], hide_index=True)
                                st.caption(
                                    "Preview only. The analysis uses all saved rows."
                                )
                            with st.expander("Technical data details"):
                                st.json(
                                    {
                                        k: item[k]
                                        for k in (
                                            "result_id",
                                            "profile",
                                            "truncated",
                                            "parent_result_ids",
                                            "upload_provenance",
                                        )
                                    }
                                )
                    st.caption(
                        f"{action['timeout_seconds']:g}-second timeout · named datasets · bounded outputs"
                    )
                else:
                    st.caption(
                        f"Read-only {action['dialect']} · one statement · {action['timeout_seconds']:g}-second timeout · {action['max_result_rows']}-row cap"
                    )
                with st.expander(f"Review or edit {language} code"):
                    if language == "Python":
                        st.caption(
                            "Inputs are DataFrames in datasets[alias]; pd and np are preloaded."
                        )
                    editor_key = f"{language.lower()}_review_{item_key}"
                    st.session_state.setdefault(editor_key, action["query"])
                    code = st.text_area(
                        f"{language} to execute",
                        height=240,
                        key=editor_key,
                        disabled="edit" not in action["allowed_decisions"],
                    )
                    st.button(
                        f"Reset {language} proposal {index + 1}",
                        type="tertiary",
                        key=f"review_reset_{item_key}",
                        on_click=_reset_review_editor,
                        args=(editor_key, action["query"]),
                    )
                options = []
                if {"approve", "edit"} & set(action["allowed_decisions"]):
                    options.append("Run reviewed code")
                if "reject" in action["allowed_decisions"]:
                    options.append("Request changes")
                choice = st.segmented_control(
                    f"Decision for proposal {index + 1}",
                    options,
                    default=None,
                    key=f"review_choice_{item_key}",
                )
                message = ""
                if choice == "Request changes":
                    message = st.text_area(
                        f"Feedback for proposal {index + 1}",
                        help="Tell the analyst what to change. This proposal will not execute.",
                        height=100,
                        key=f"review_feedback_{item_key}",
                    )
                try:
                    decisions.extend(
                        review_decisions([action], [choice], [code], [message])
                    )
                except ValueError as exc:
                    if choice is None:
                        st.caption(
                            "Choose a decision to finish reviewing this proposal."
                        )
                    else:
                        st.error(str(exc), icon=":material/error:")
        summary.progress(
            len(decisions) / len(actions),
            text=f"{len(decisions)} of {len(actions)} proposals ready",
        )
        submitted = st.button(
            "Apply reviewed decisions",
            type="primary",
            icon=":material/play_arrow:",
            key=f"review_submit_{run['run_id']}_{cycle_key}",
            disabled=len(decisions) != len(actions),
        )
        if submitted:
            return decisions
    return None
