"""Reusable native Streamlit components for the analyst chat."""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st

from text2sql_agent.ui.api_client import APIError, AgentAPIClient

EXAMPLE_QUESTIONS = {
    ":material/leaderboard: Top artists by revenue": (
        "Which five artists generated the most line-item revenue?"
    ),
    ":material/public: Customers by country": (
        "How many customers are in each country? Show the top five."
    ),
    ":material/calendar_month: Monthly sales": (
        "Show monthly invoice revenue and explain any assumptions."
    ),
}


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


def render_page_header() -> None:
    st.caption(":material/query_stats: CONVERSATIONAL ANALYTICS")
    st.title("Ask questions about Chinook")
    st.caption(
        "The analyst grounds itself in the OSI semantic model, prepares one "
        "read-only query, and waits for your approval before execution."
    )


def render_sidebar(
    *,
    thread_id: str,
    app_base_url: str,
    health: dict[str, Any] | None,
    health_error: str | None,
) -> bool:
    """Render app-level metadata and return whether New conversation was used."""

    with st.sidebar:
        st.caption(":material/database: DEEP AGENT POC")
        st.title("Chinook Analyst")
        st.caption(
            "Human-reviewed SQL with semantic grounding and local in-memory "
            "conversation state."
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
        elif health:
            st.warning("API setup incomplete", icon=":material/warning:")
            for error in health.get("errors", []):
                st.caption(error)

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


def render_empty_state(thread_id: str) -> str | None:
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
            options=list(EXAMPLE_QUESTIONS),
            key=f"starter_question_{thread_id}",
            label_visibility="collapsed",
            width="stretch",
        )
    return EXAMPLE_QUESTIONS.get(selection) if selection else None


def _render_result(
    client: AgentAPIClient,
    result_id: str,
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
                "Capped at 500",
                icon=":material/content_cut:",
                color="orange",
            )

    if result["rows"]:
        st.dataframe(
            result["rows"],
            column_order=result["columns"],
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Download CSV",
            data=rows_to_csv(result["columns"], result["rows"]),
            file_name=f"chinook-result-{result_id[:8]}.csv",
            mime="text/csv",
            icon=":material/download:",
            on_click="ignore",
            width="content",
            key=f"download_{result_id}",
        )
    else:
        st.info(
            "The query completed successfully but returned no rows.",
            icon=":material/info:",
        )


def render_turn(client: AgentAPIClient, turn: dict[str, Any]) -> None:
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
            _render_result(client, answer["result_id"])

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


def render_approval(run: dict[str, Any]) -> dict[str, Any] | None:
    approval = run["approval"]
    query = approval["query"]
    cycle_key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:10]
    editor_key = f"sql_review_{run['run_id']}_{cycle_key}"

    with st.container(border=True):
        st.subheader(
            "Review SQL before execution",
            anchor=False,
        )
        st.warning(
            "Nothing has been executed yet.",
            icon=":material/security:",
        )
        st.caption(
            "Compare the joins, filters, metric definitions, sorting, and row "
            "limit with your question before choosing an action."
        )
        edited_sql = st.text_area(
            "Generated SQL",
            value=query,
            height=240,
            key=editor_key,
            help=(
                "Review the query carefully. The backend parses and validates "
                "the exact approved or edited SQL before execution."
            ),
        )
        changed = edited_sql != query
        st.caption(
            "Read-only SQLite · one statement · 10-second timeout · "
            "500-row result cap"
        )

        with st.container(
            horizontal=True,
            vertical_alignment="center",
            gap="xsmall",
        ):
            approve = st.button(
                "Approve and run",
                icon=":material/play_arrow:",
                type="primary",
                key=f"approve_{run['run_id']}_{cycle_key}",
            )
            edit = st.button(
                "Run edited SQL",
                icon=":material/edit:",
                disabled=not changed,
                help=(
                    "Change the SQL above to enable this action."
                    if not changed
                    else "Execute the edited query after backend validation."
                ),
                key=f"edit_{run['run_id']}_{cycle_key}",
            )

        if approve:
            return {"action": "approve"}
        if edit:
            return {"action": "edit", "edited_sql": edited_sql}

        with st.expander(
            "Reject and request changes",
            icon=":material/replay:",
            expanded=False,
        ):
            feedback = st.text_area(
                "Feedback for the analyst",
                placeholder=(
                    "Explain what should change, such as the metric, "
                    "filter, grouping, or sort order."
                ),
                height=100,
                key=f"rejection_feedback_{run['run_id']}_{cycle_key}",
            )
            reject = st.button(
                "Reject and replan",
                icon=":material/undo:",
                disabled=not feedback.strip(),
                key=f"reject_{run['run_id']}_{cycle_key}",
            )
            if reject:
                return {
                    "action": "reject",
                    "feedback": feedback.strip(),
                }
    return None
