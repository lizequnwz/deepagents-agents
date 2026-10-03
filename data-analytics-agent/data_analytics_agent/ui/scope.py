"""Native controls for explicit snapshot selection, population and refresh."""

from datetime import date

import streamlit as st

from data_analytics_agent.ui.api_client import APIError


def render_input_selector(client, conversation, *, disabled=False):
    thread_id = conversation["thread_id"]
    try:
        datasets = client.list_datasets(thread_id)
    except APIError as exc:
        st.error(str(exc))
        return None, None
    by_id = {item["result_id"]: item for item in datasets}
    previous = conversation.get("analytical_input") or {}
    key = f"analytical_dataset_{thread_id}"
    version_key = f"analytical_dataset_version_{thread_id}"
    version = conversation["turns"][-1]["run_id"] if conversation["turns"] else None
    if st.session_state.get(version_key) != version:
        st.session_state[key] = previous.get("selected_result_id")
        st.session_state[version_key] = version
    st.session_state.setdefault(key, previous.get("selected_result_id"))
    if st.session_state[key] not in by_id:
        st.session_state[key] = None
    selected = st.selectbox(
        "Analyze",
        [None, *by_id],
        key=key,
        disabled=disabled,
        format_func=lambda value: (
            "Current source"
            if value is None
            else f"{by_id[value]['label']} · {by_id[value]['row_count']:,} rows · complete snapshot"
        ),
        help="A saved dataset fixes the population for this question. If necessary detail is missing, the agent will ask before retrieving broader or newer source data.",
    )
    if selected:
        item = by_id[selected]
        st.caption(f"Saved {item['snapshot_at']} · {item['grain']}")
        st.caption(
            "Known scope: "
            + (
                item["question"]
                or "No business scope recorded; inspect the saved calculation before use."
            )
        )
        st.caption(
            "Complete saved population. Source cutoff is unknown unless declared in the evidence."
        )
    scope = (
        previous.get("scope")
        if selected == previous.get("selected_result_id")
        else None
    )
    if scope:
        filters = [
            f"{column}: {', '.join('Missing' if value is None else str(value) for value in values)}"
            for column, values in scope["categories"].items()
        ]
        if scope.get("dates"):
            dates = scope["dates"]
            filters.append(
                f"{dates['column']}: {dates['start']} through {dates['end']} (inclusive)"
            )
        st.caption(
            f"Applied population: {previous['row_count']:,} rows. "
            + ("Filters: " + "; ".join(filters) if filters else "All saved rows.")
        )
    return selected, scope


def render_scope_controls(client, conversation, selected_result_id, *, is_warehouse):
    if not conversation["turns"]:
        return
    turn = conversation["turns"][-1]
    report = turn["answer"].get("report")
    if not report:
        return
    thread_id, report_id = conversation["thread_id"], report["report_id"]
    if is_warehouse and st.button(
        "Refresh from warehouse", key=f"refresh_{report_id}", icon=":material/refresh:"
    ):
        try:
            run = client.refresh_warehouse(turn["run_id"], report_id)
        except APIError as exc:
            st.error(str(exc))
        else:
            st.session_state["active_run_id"] = run["run_id"]
            st.rerun()
    if not selected_result_id:
        return
    control_key = f"{thread_id}_{selected_result_id}"
    if not st.toggle("Refine saved population", key=f"show_scope_{control_key}"):
        return
    try:
        options = client.scope_options(thread_id, selected_result_id)
    except APIError as exc:
        st.error(str(exc))
        return
    applied = (conversation.get("analytical_input") or {}).get("scope") or {}
    if applied.get("base_result_id") != selected_result_id:
        applied = {}
    st.caption(
        "Filters select existing rows. Aggregated rows retain their saved grain; filters cannot recover missing detail or split aggregate periods."
    )
    unavailable = set(applied.get("categories", {})) - set(options["categories"])
    if unavailable:
        st.warning(
            "This snapshot no longer supports category controls for: "
            + ", ".join(sorted(unavailable))
            + ". The applied scope is preserved. Ask for a saved-data analysis to change those filters."
        )
    columns = st.multiselect(
        "Category columns",
        list(options["categories"]),
        default=[
            column
            for column in applied.get("categories", {})
            if column in options["categories"]
        ],
        max_selections=10,
        key=f"scope_columns_{control_key}",
    )
    date_columns = options["date_columns"]
    previous_date = applied.get("dates") or {}
    date_column = st.selectbox(
        "Date column",
        [None, *date_columns],
        index=1 + date_columns.index(previous_date["column"])
        if previous_date.get("column") in date_columns
        else 0,
        format_func=lambda value: value or "No date filter",
        key=f"scope_date_{control_key}",
    )
    revision_key = f"scope_revision_{control_key}"
    displayed_revision = st.session_state.get(revision_key, report_id)
    defaults = {}
    absent = []
    for column in columns:
        selected = applied.get("categories", {}).get(column, [])
        available = options["categories"][column]
        defaults[column] = [value for value in selected if value in available]
        absent.extend(
            f"{column}: {'Missing' if value is None else value}"
            for value in selected
            if value not in available
        )
    if absent:
        st.warning(
            "Applied values are absent from this snapshot: "
            + "; ".join(absent)
            + ". The current answer keeps that population. Choose available values or remove the filter before applying a new population."
        )
    with st.form(f"scope_form_{control_key}"):
        categories = {
            column: st.multiselect(
                column,
                options["categories"][column],
                default=defaults[column],
                max_selections=100,
                format_func=lambda value: "Missing" if value is None else str(value),
                key=f"scope_values_{control_key}_{column}",
            )
            for column in columns
        }
        dates = None
        if date_column:
            bounds = options["date_bounds"].get(date_column)
            if not bounds:
                st.warning("This column has no dated rows.")
            else:
                initial = (
                    previous_date
                    if previous_date.get("column") == date_column
                    else bounds
                )
                start = st.date_input(
                    "Start date (inclusive)",
                    value=date.fromisoformat(initial["start"]),
                    key=f"scope_start_{control_key}_{date_column}",
                )
                end = st.date_input(
                    "End date (inclusive)",
                    value=date.fromisoformat(initial["end"]),
                    key=f"scope_end_{control_key}_{date_column}",
                )
                dates = {
                    "column": date_column,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
        apply = st.form_submit_button("Apply population", disabled=bool(unavailable))
    st.session_state[revision_key] = report_id
    if apply:
        if displayed_revision != report_id:
            st.error(
                "This report changed while the form was open. Review the latest answer before applying the population again."
            )
            return
        if any(not values for values in categories.values()):
            st.error("Choose values for each category column, or remove that filter.")
            return
        try:
            question = turn["user_message"]
            if turn.get("corrections"):
                question += "\nAccepted corrections: " + "\n".join(
                    item["message"] for item in turn["corrections"]
                )
            run = client.send_message(
                thread_id,
                question,
                selected_result_id=selected_result_id,
                scope={
                    "base_result_id": selected_result_id,
                    "categories": categories,
                    "dates": dates,
                },
                previous_report_id=report_id,
            )
        except APIError as exc:
            st.error(str(exc))
        else:
            st.session_state["active_run_id"] = run["run_id"]
            st.rerun()
