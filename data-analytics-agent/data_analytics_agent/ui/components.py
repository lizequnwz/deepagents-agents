"""Reusable native Streamlit components for the analyst chat."""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st

from data_analytics_agent.agents.visualization.geocoding import (
    USLocationResolver,
)
from data_analytics_agent.agents.visualization.renderer import build_chart
from data_analytics_agent.agents.visualization.schemas import ChartSpec
from data_analytics_agent.ui.api_client import APIError, AgentAPIClient

FALLBACK_EXAMPLES = [
    {
        "label": "Summarize the available data",
        "question": (
            "What business entities and measures are available in this "
            "data source?"
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


def _reset_sql_editor(editor_key: str, generated_sql: str) -> None:
    st.session_state[editor_key] = generated_sql


@st.cache_resource
def _us_location_resolver() -> USLocationResolver:
    return USLocationResolver()


def render_page_header(source: dict[str, Any] | None = None) -> None:
    st.caption(":material/query_stats: CONVERSATIONAL ANALYTICS")
    source_name = source["name"] if source else "your data"
    source_anchor = (
        f"ask-questions-about-{source['source_id']}" if source else False
    )
    st.title(
        f"Ask questions about {source_name}",
        anchor=source_anchor,
    )
    st.caption(
        "Semantic-grounded analytics. SQL is reviewed before execution; "
        "explicitly requested charts are generated from constrained specs."
    )


def render_sidebar(
    *,
    thread_id: str,
    app_base_url: str,
    health: dict[str, Any] | None,
    health_error: str | None,
    data_sources: dict[str, Any],
    source_switch_disabled: bool,
) -> bool:
    """Render app-level metadata and return whether New conversation was used."""

    with st.sidebar:
        st.title("Data Analytics Agent")
        st.caption(
            "Human-reviewed SQL and optional constrained charts with semantic "
            "grounding and local in-memory conversation state."
        )
        ready_sources = [
            source for source in data_sources["sources"] if source["ready"]
        ]
        ready_by_id = {
            source["source_id"]: source for source in ready_sources
        }
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
            f"{selected_source['backend_type']} · "
            f"{selected_source['dialect']}",
            icon=":material/storage:",
            color="blue",
        )
        if source_switch_disabled:
            st.caption(
                "The data source cannot change while a run or SQL review "
                "is active."
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
            if health.get("visualization_enabled"):
                st.badge(
                    "Charts enabled",
                    icon=":material/bar_chart:",
                    color="blue",
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
                "Conversation data is process-local and is cleared when the "
                "FastAPI server restarts."
            )
        return new_conversation


def render_empty_state(
    thread_id: str,
    source: dict[str, Any],
) -> str | None:
    examples = source.get("examples") or FALLBACK_EXAMPLES
    question_by_label = {
        f":material/lightbulb: {item['label']}": item["question"]
        for item in examples
    }
    with st.container(border=True):
        st.subheader(
            "Start with a business question",
            anchor=False,
        )
        st.caption(
            "Try an example or write your own question below. You will always "
            "see and review generated SQL before it runs."
        )
        selection = st.pills(
            "Example questions",
            options=list(question_by_label),
            key=f"starter_question_{thread_id}",
            label_visibility="collapsed",
            width="stretch",
        )
    return question_by_label.get(selection) if selection else None


def _render_result(
    client: AgentAPIClient,
    result_id: str,
    *,
    widget_key: str,
    source_id: str,
    chart: dict[str, Any] | None = None,
) -> None:
    try:
        result = client.get_result(result_id)
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
        st.download_button(
            "Download CSV",
            data=rows_to_csv(result["columns"], result["rows"]),
            file_name=f"{source_id}-result-{result_id[:8]}.csv",
            mime="text/csv",
            icon=":material/download:",
            on_click="ignore",
            width="content",
            key=f"download_{result_id}_{widget_key}",
        )

    if chart and result["rows"]:
        try:
            spec = ChartSpec.model_validate(chart)
            if spec.result_id != result_id:
                raise ValueError(
                    "The chart does not reference this saved result."
                )
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
            "Underlying data",
            icon=":material/table_chart:",
            expanded=False,
        ):
            render_table()
    else:
        render_table()


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

        if answer.get("result_id"):
            _render_result(
                client,
                answer["result_id"],
                widget_key=turn_key,
                source_id=source_id,
                chart=answer.get("chart"),
            )

        if answer.get("sql"):
            with st.expander(
                "Executed SQL",
                icon=":material/code:",
                expanded=False,
            ):
                st.code(answer["sql"], language="sql")

        activities = turn.get("activities") or []
        if activities:
            with st.expander(
                "How this was produced",
                icon=":material/account_tree:",
                expanded=False,
            ):
                for event in activities:
                    st.caption(
                        f":material/check: {event['label']}"
                    )


def render_pending_user_message(question: str) -> None:
    with st.chat_message("user"):
        st.markdown(question)


def render_approval(
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
                    key=(
                        f"rejection_feedback_{run['run_id']}_{cycle_key}"
                    ),
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
