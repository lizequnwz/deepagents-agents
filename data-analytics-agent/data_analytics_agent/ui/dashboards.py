"""Native Streamlit access to the shared dashboard service."""

from datetime import date
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

from data_analytics_agent.ui.api_client import APIError


def render_dashboards(client, thread_id, conversation, *, disabled=False):
    panel = st.expander(
        "Saved dashboards",
        key=f"dashboards_open_{thread_id}",
        on_change="rerun",
        icon=":material/dashboard:",
    )
    if not panel.open:
        return
    prefix = f"/api/conversations/{thread_id}/dashboards"
    with panel:
        try:
            dashboards = client.request("GET", prefix)["dashboards"]
            turns = [
                turn for turn in conversation["turns"] if turn["answer"].get("report")
            ]
            if turns and st.button(
                "Save latest report as dashboard",
                key=f"save_dashboard_{thread_id}",
                disabled=disabled,
            ):
                created = client.request(
                    "POST",
                    prefix,
                    json={"run_id": turns[-1]["run_id"], "request_id": str(uuid4())},
                )
                st.session_state[f"dashboard_choice_{thread_id}"] = created["revision"][
                    "dashboard_id"
                ]
                st.rerun()
            if not dashboards:
                st.caption("Save a completed report, or ask for a dashboard in chat.")
                return
            by_id = {item["dashboard_id"]: item for item in dashboards}
            selected = st.selectbox(
                "Dashboard",
                list(by_id),
                format_func=lambda key: by_id[key]["spec"]["title"],
                key=f"dashboard_choice_{thread_id}",
            )
            view = client.request("GET", f"{prefix}/{selected}")
            revision = view["revision"]
            identity = revision["revision_id"]
            st.subheader(revision["spec"]["title"])
            st.caption(
                f"Version {revision['version']} · Saved {revision['created_at']} · Source completeness is unknown."
            )
            action = view.get("pending_action")
            controls_disabled = disabled or bool(
                action and action["status"] in {"queued", "running"}
            )
            if action and action["status"] == "failed":
                st.warning(action.get("error") or "The dashboard action failed.")
            if controls_disabled:
                st.info(
                    "The last committed dashboard remains visible. Complete or resume the current action before changing this view."
                )
            with st.form(f"dashboard_filters_{identity}"):
                values = {}
                for filtering in view["filters"]:
                    key = filtering["id"]
                    current = revision["saved_filter_values"].get(
                        key, revision["applied_filters"].get(key, [])
                    )
                    if filtering["kind"] == "date_range":
                        selected_dates = st.date_input(
                            filtering["label"],
                            value=tuple(date.fromisoformat(v) for v in current),
                            key=f"dashboard_filter_{identity}_{key}",
                            disabled=controls_disabled,
                        )
                        values[key] = [d.isoformat() for d in selected_dates]
                    else:
                        options = list(filtering["options"])
                        options.extend(
                            value for value in current if value not in options
                        )
                        values[key] = st.multiselect(
                            filtering["label"],
                            options,
                            default=current,
                            accept_new_options=True,
                            key=f"dashboard_filter_{identity}_{key}",
                            disabled=controls_disabled,
                        )
                    if filtering.get("description"):
                        st.caption(filtering["description"])
                    st.caption(
                        "Applies to: "
                        + ", ".join(
                            binding["component_id"] for binding in filtering["bindings"]
                        )
                    )
                apply = st.form_submit_button(
                    "Apply filters",
                    disabled=controls_disabled or not bool(view["filters"]),
                )
                if apply:
                    client.request(
                        "POST",
                        f"{prefix}/{selected}/actions",
                        json={
                            "expected_revision": identity,
                            "request_id": str(uuid4()),
                            "action": "filter",
                            "filter_values": values,
                        },
                    )
                    st.rerun()
            with st.container(horizontal=True):
                if st.button(
                    "Refresh dashboard data",
                    key=f"refresh_dashboard_{identity}",
                    disabled=controls_disabled,
                ):
                    client.request(
                        "POST",
                        f"{prefix}/{selected}/actions",
                        json={
                            "expected_revision": identity,
                            "request_id": str(uuid4()),
                            "action": "refresh",
                        },
                    )
                    st.rerun()
                st.link_button(
                    "Open full workspace",
                    f"{client.base_url}/workspace/?thread={thread_id}&dashboard={selected}",
                )
                st.link_button(
                    "Download dashboard report",
                    f"{client.base_url}/api/reports/{revision['report_id']}/download",
                )
            for component in view["components"]:
                with st.container(border=True):
                    if component["type"] == "metric":
                        st.metric(component["title"], component["formatted_value"])
                    elif component["type"] == "chart":
                        if component.get("figure"):
                            st.plotly_chart(
                                go.Figure(component["figure"]),
                                width="stretch",
                                key=f"dashboard_chart_{identity}_{component['id']}",
                                config={"displaylogo": False},
                            )
                        else:
                            st.info("No data matches the applied filters.")
                    elif component["type"] == "table":
                        st.write(component["title"])
                        st.dataframe(component["rows"], hide_index=True)
                    elif component.get("body"):
                        st.write(component["body"])
                    for warning in component.get("warnings", []):
                        st.caption(warning)
                    for note in component.get("notes", []):
                        st.caption(note)
            with st.form(f"dashboard_title_{identity}"):
                title = st.text_input("Dashboard title", revision["spec"]["title"])
                if st.form_submit_button("Save view", disabled=controls_disabled):
                    client.request(
                        "POST",
                        f"{prefix}/{selected}/view",
                        json={
                            "expected_revision": identity,
                            "request_id": str(uuid4()),
                            "title": title,
                            "saved_filter_values": values,
                        },
                    )
                    st.rerun()
        except (APIError, ValueError) as exc:
            st.error(str(exc))
