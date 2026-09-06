"""Reusable native Streamlit components for the analyst chat."""

from __future__ import annotations

import csv
import hashlib
import io
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

_PHASE_ICONS = {
    "info": ":material/info:",
    "started": ":material/pending:",
    "completed": ":material/check_circle:",
    "failed": ":material/error:",
}


def consolidate_activity_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge append-only tool lifecycle events for compact display."""

    consolidated: list[dict[str, Any]] = []
    tool_indexes: dict[str, int] = {}
    for source in events:
        event = dict(source)
        tool = event.get("tool")
        call_id = tool.get("call_id") if isinstance(tool, dict) else None
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


def render_activity_summary(events: list[dict[str, Any]]) -> None:
    """Keep current tools and recent completions visible without opening raw I/O."""
    calls = [e for e in consolidate_activity_events(events) if e.get("tool")]
    if not calls:
        st.caption("Waiting for the agent’s next action…")
        return
    pending = [e for e in calls if e.get("phase") == "started"]
    finished = [e for e in calls if e.get("phase") != "started"]
    st.caption(f"{len(calls)} tool calls · {len(pending)} running")
    for event in pending + finished[-5:]:
        tool = event["tool"]
        name = tool.get("name") or "tool"
        arguments = tool.get("input") or {}
        detail = ""
        if isinstance(arguments, dict):
            if name == "task" and arguments.get("subagent_type"):
                detail = f" → {arguments['subagent_type']}"
            elif name == "read_file" and arguments.get("file_path"):
                detail = f" · {arguments['file_path']}"
        phase = event.get("phase") or "completed"
        duration = event.get("duration_ms")
        timing = f" · {_format_duration(duration)}" if duration is not None else ""
        st.caption(
            f"{_agent_label(event.get('agent'))} · {name}{detail} · {phase}{timing}"
        )


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
        label = str(event.get("label") or "Agent activity")
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
        event_key = tool.get("call_id") or event.get("id") or len(tool_seen)
        with st.expander(
            f"{tool_name}{ordinal}",
            icon=":material/build:",
            expanded=False,
            type="compact",
            key=f"activity_{key_prefix}_{event_key}",
        ):
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


def _reset_sql_editor(editor_key: str, generated_sql: str) -> None:
    st.session_state[editor_key] = generated_sql


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
        "Semantic-grounded analytics. SQL and analytical Python are reviewed "
        "when enabled; saved evidence supports iterative analysis."
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
            source for source in data_sources["sources"] if source["ready"]
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


def _render_result(
    client: AgentAPIClient,
    result_id: str,
    *,
    widget_key: str,
    source_id: str,
    chart: dict[str, Any] | None = None,
    reference: dict[str, Any] | None = None,
    expanded: bool = False,
) -> None:
    try:
        result = _saved_result(client.base_url, result_id, 5000 if chart else 100)
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

    def render_table() -> None:
        if not result["rows"]:
            st.info(
                "The query completed successfully but returned no rows.",
                icon=":material/info:",
            )
            return
        st.dataframe(
            result["rows"],
            column_order=result["columns"],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"Preview: {len(result['rows'])} of {result['row_count']:,} saved rows."
        )
        st.link_button("Download full CSV", client.dataset_download_url(result_id))
        st.link_button(
            "Download full Parquet", client.dataset_download_url(result_id, "parquet")
        )

    def render_provenance() -> None:
        if reference:
            question = str(reference.get("originating_question") or "")
            if question:
                st.caption(f"Originating question · {question}")
            st.markdown("**Executed SQL**")
            st.code(
                str(reference.get("executed_sql") or result["executed_sql"]),
                language="sql",
            )
        else:
            st.markdown("**Executed SQL**")
            st.code(result["executed_sql"], language="sql")

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
        except Exception as exc:
            st.warning(
                f"The generated chart could not be rendered: {exc}",
                icon=":material/warning:",
            )
        with st.expander(
            "Evidence data and provenance",
            icon=":material/table_chart:",
            expanded=expanded,
        ):
            render_table()
            render_provenance()
    else:
        with st.expander(
            "Evidence data and provenance",
            icon=":material/table_chart:",
            expanded=expanded,
        ):
            render_table()
            render_provenance()


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
        with st.expander(
            "Report preview",
            icon=":material/preview:",
            expanded=True,
            key=f"report_preview_{report_id}_{widget_key}",
        ):
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
        st.markdown(turn["user_message"])

    answer = turn["answer"]
    with st.chat_message("assistant", avatar=":material/query_stats:"):
        st.markdown(answer["answer"])

        assumptions = answer.get("assumptions") or []
        interpretation = answer.get("interpretation")
        if assumptions or interpretation:
            with st.container(border=True):
                if assumptions:
                    st.markdown("**Assumptions**")
                    for assumption in assumptions:
                        st.markdown(f"- {assumption}")
                if interpretation:
                    st.markdown("**Interpretation**")
                    st.markdown(interpretation)

        if answer.get("partial"):
            st.warning("Partial findings — the investigation is unfinished.")
        for question in answer.get("unresolved_questions") or []:
            st.caption(f"Still to investigate: {question}")
        for index, analysis in enumerate(answer.get("analyses") or []):
            _render_data_analysis(
                analysis, client=client, widget_key=f"{turn_key}_{index}"
            )
        for index, chart in enumerate(answer.get("charts") or []):
            _render_result(
                client,
                chart["result_id"],
                widget_key=f"{turn_key}_chart_{index}",
                source_id=source_id,
                chart=chart,
            )

        report = answer.get("report")
        if report:
            _render_report(
                client,
                report,
                widget_key=turn_key,
            )

        results = answer.get("results") or []
        chart = None
        for index, reference in enumerate(results):
            result_id = str(reference.get("result_id") or "")
            label = str(reference.get("short_label") or "SQL evidence")
            st.markdown(f"**Evidence {index + 1} · {label}**")
            if result_id == answer.get("primary_result_id"):
                st.badge(
                    "Primary evidence",
                    icon=":material/verified:",
                    color="green",
                )
            _render_result(
                client,
                result_id,
                widget_key=f"{turn_key}_{index}",
                source_id=source_id,
                chart=(
                    chart if chart and chart.get("result_id") == result_id else None
                ),
                reference=reference,
                expanded=index == 0 and chart is None,
            )

        activities = turn.get("activities") or []
        debug_states = turn.get("debug_states") or []
        if activities or debug_states:
            with st.status(
                "How this was produced",
                expanded=False,
                state="complete",
            ):
                render_activity_timeline(
                    activities,
                    debug_states=debug_states,
                    key_prefix=f"turn_{turn_key}",
                )
        if turn.get("diagnostics"):
            render_run_diagnostics(
                turn["diagnostics"],
                activities=activities,
                key=f"run_diagnostics_{turn_key}",
            )


def _render_data_analysis(
    analysis: dict[str, Any], *, client: AgentAPIClient, widget_key: str
) -> None:
    st.badge(
        str(analysis.get("outcome", "analysis")).replace("_", " "),
        icon=":material/functions:",
    )
    with st.expander("Analysis methods, outputs, and executed Python", expanded=False):
        st.markdown(analysis.get("method") or "")
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
        st.markdown(question)


def render_approval(
    run: dict[str, Any],
    *,
    revision_feedback: str | None = None,
) -> dict[str, Any] | None:
    """Render the appropriate SQL or Python human-review surface."""

    if run["approval"].get("review_type") == "python":
        return _render_python_approval(
            run,
            revision_feedback=revision_feedback,
        )
    return _render_sql_approval(
        run,
        revision_feedback=revision_feedback,
    )


def _render_sql_approval(
    run: dict[str, Any],
    *,
    revision_feedback: str | None = None,
) -> dict[str, Any] | None:
    approval = run["approval"]
    query = approval["query"]
    cycle_source = f"{run['next_event_id']}\0{query}"
    cycle_key = hashlib.sha256(cycle_source.encode("utf-8")).hexdigest()[:10]
    editor_key = f"sql_review_{run['run_id']}_{cycle_key}"
    st.session_state.setdefault(editor_key, query)

    with st.container(border=True):
        st.subheader(
            "Review SQL before execution",
            anchor=False,
        )
        st.warning(
            "Nothing has been executed yet.",
            icon=":material/security:",
        )
        if revision_feedback:
            st.success(
                "Revised SQL is ready for another review.",
                icon=":material/check_circle:",
            )
            st.caption(f"Your feedback: {revision_feedback}")
        st.caption(
            "Compare the joins, filters, metric definitions, sorting, and row "
            "limit with your question. The SQL visible in the editor is the "
            "SQL that will run."
        )
        with st.form(
            f"sql_run_form_{run['run_id']}_{cycle_key}",
            border=False,
            enter_to_submit=False,
        ):
            reviewed_sql = st.text_area(
                "SQL to execute",
                height=240,
                key=editor_key,
                help=(
                    "Review or edit the query. This exact text is parsed and "
                    "validated by the backend before execution."
                ),
            )
            st.caption(
                f"Read-only {approval['dialect']} · one statement · "
                f"{approval['timeout_seconds']:g}-second timeout · "
                f"{approval['max_result_rows']}-row result cap"
            )
            run_sql = st.form_submit_button(
                "Run this SQL",
                icon=":material/play_arrow:",
                type="primary",
                key=f"run_sql_{run['run_id']}_{cycle_key}",
            )
        st.button(
            "Reset to generated SQL",
            icon=":material/restart_alt:",
            type="tertiary",
            key=f"reset_sql_{run['run_id']}_{cycle_key}",
            on_click=_reset_sql_editor,
            args=(editor_key, query),
        )

        if run_sql:
            return sql_review_decision(query, reviewed_sql)

        with st.expander(
            "Reject and request changes",
            icon=":material/replay:",
            expanded=False,
        ):
            st.caption(
                "The analyst will propose revised SQL. You will review it "
                "again before anything is executed."
            )
            with st.form(
                f"sql_reject_form_{run['run_id']}_{cycle_key}",
                border=False,
                enter_to_submit=False,
            ):
                feedback = st.text_area(
                    "Feedback for the analyst",
                    placeholder=(
                        "Explain what should change, such as the metric, "
                        "filter, grouping, or sort order."
                    ),
                    height=100,
                    key=(f"rejection_feedback_{run['run_id']}_{cycle_key}"),
                )
                reject = st.form_submit_button(
                    "Send feedback and revise",
                    icon=":material/replay:",
                    key=f"reject_{run['run_id']}_{cycle_key}",
                )
            if reject:
                if not feedback.strip():
                    st.error(
                        "Add feedback describing how the SQL should change.",
                        icon=":material/error:",
                    )
                    return None
                return {
                    "action": "reject",
                    "feedback": feedback.strip(),
                }
    return None


def _render_python_approval(
    run: dict[str, Any],
    *,
    revision_feedback: str | None = None,
) -> dict[str, Any] | None:
    approval = run["approval"]
    generated_python = approval["query"]
    cycle_source = f"{run['next_event_id']}\0{generated_python}"
    cycle_key = hashlib.sha256(cycle_source.encode("utf-8")).hexdigest()[:10]
    editor_key = f"python_review_{run['run_id']}_{cycle_key}"
    st.session_state.setdefault(editor_key, generated_python)

    with st.container(border=True):
        st.subheader("Review Python before execution", anchor=False)
        st.warning(
            "Nothing in this Python proposal has been executed yet. Approved "
            "code runs with the local API service's file and process access.",
            icon=":material/security:",
        )
        if revision_feedback:
            st.success(
                "Revised Python is ready for another review.",
                icon=":material/check_circle:",
            )
            st.caption(f"Your feedback: {revision_feedback}")

        with st.container(
            horizontal=True,
            vertical_alignment="center",
            gap="small",
        ):
            st.badge(
                f"Result {str(approval.get('parent_result_id') or '')[:8]}",
                icon=":material/database:",
                color="blue",
            )
            st.badge(
                f"{approval.get('row_count', 0)} rows",
                icon=":material/table_rows:",
                color="gray",
            )
            st.badge(
                str(approval.get("source_id") or "source"),
                icon=":material/storage:",
                color="gray",
            )

        st.caption(
            "The immutable parent result is loaded as pandas `df`; `pd` and "
            "`np` are preloaded. The complete code visible in the editor is "
            "the exact code that will execute."
        )
        with st.expander(
            "Input dataset provenance",
            icon=":material/data_object:",
            expanded=False,
        ):
            if approval.get("originating_question"):
                st.markdown("**Originating question**")
                st.markdown(str(approval["originating_question"]))
            st.markdown("**Executed SQL**")
            st.code(str(approval.get("executed_sql") or ""), language="sql")
            st.markdown("**Columns and full-result profile**")
            st.json(
                {
                    "columns": approval.get("columns") or [],
                    "profile": approval.get("profile") or {},
                    "truncated": approval.get("truncated"),
                }
            )
            sample_rows = approval.get("sample_rows") or []
            if sample_rows:
                st.markdown("**First 10 rows at most**")
                st.dataframe(
                    sample_rows,
                    column_order=approval.get("columns") or None,
                    hide_index=True,
                    width="stretch",
                )

        with st.form(
            f"python_run_form_{run['run_id']}_{cycle_key}",
            border=False,
            enter_to_submit=False,
        ):
            reviewed_python = st.text_area(
                "Python to execute",
                height=420,
                key=editor_key,
                help=(
                    "Review or edit the code. This exact text executes in a "
                    "bounded subprocess against the immutable parent result."
                ),
            )
            st.caption(
                f"{approval['timeout_seconds']:g}-second timeout · scoped `df` "
                "input · bounded stdout, tables, and figures"
            )
            run_python = st.form_submit_button(
                "Run this Python",
                icon=":material/play_arrow:",
                type="primary",
                key=f"run_python_{run['run_id']}_{cycle_key}",
            )
        st.button(
            "Reset to generated Python",
            icon=":material/restart_alt:",
            type="tertiary",
            key=f"reset_python_{run['run_id']}_{cycle_key}",
            on_click=_reset_sql_editor,
            args=(editor_key, generated_python),
        )

        if run_python:
            if not reviewed_python.strip():
                st.error(
                    "Python code cannot be empty.",
                    icon=":material/error:",
                )
                return None
            return python_review_decision(
                generated_python,
                reviewed_python,
            )

        with st.expander(
            "Reject and request changes",
            icon=":material/replay:",
            expanded=False,
        ):
            st.caption(
                "The statistical analyst will propose revised Python. You "
                "will review it again before anything executes."
            )
            with st.form(
                f"python_reject_form_{run['run_id']}_{cycle_key}",
                border=False,
                enter_to_submit=False,
            ):
                feedback = st.text_area(
                    "Feedback for the analyst",
                    placeholder=(
                        "Explain what should change in the method, data "
                        "handling, outputs, or figures."
                    ),
                    height=100,
                    key=(f"rejection_feedback_{run['run_id']}_{cycle_key}"),
                )
                reject = st.form_submit_button(
                    "Send feedback and revise",
                    icon=":material/replay:",
                    key=f"reject_python_{run['run_id']}_{cycle_key}",
                )
            if reject:
                if not feedback.strip():
                    st.error(
                        "Add feedback describing how the Python should change.",
                        icon=":material/error:",
                    )
                    return None
                return {"action": "reject", "feedback": feedback.strip()}
    return None
