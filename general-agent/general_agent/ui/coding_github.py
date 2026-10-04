"""Concrete GitHub review and explicit publication controls."""

import streamlit as st


def connection(client, project_id: str, *, active: bool) -> bool:
    status = client.coding_github_status(project_id)
    with st.expander("GitHub", icon=":material/link:"):
        if not status["configured"]:
            st.caption("Configure a GitHub token for this user on the application server to connect a repository.")
            return False
        current = status["connection"]
        if current:
            st.link_button(current["identity"]["full_name"], current["identity"]["url"])
            st.caption("The agent can read issues and pull requests. Draft publication is a separate review action.")
        with st.form(f"github_connect_{project_id}"):
            owner = st.text_input("GitHub owner", value=current["owner"] if current else "")
            repository = st.text_input("GitHub repository", value=current["repository"] if current else "")
            if st.form_submit_button("Connect this repository", disabled=active):
                client.connect_coding_github(project_id, owner, repository)
                st.rerun()
    return bool(status["connection"])


def prepare(client, attempt: dict, *, active: bool):
    with st.expander("Prepare a draft pull request"):
        st.caption("Preparation reads the remote base and builds a complete review. Publication creates a new branch and draft PR and may trigger repository workflows.")
        with st.form(f"github_prepare_{attempt['id']}"):
            title = st.text_input("Pull request title")
            body = st.text_area("Pull request description")
            base = st.text_input("Base branch (blank uses the default)")
            if st.form_submit_button("Prepare delivery review", disabled=active):
                client.prepare_coding_delivery(attempt["change_id"], title, body, base or None)
                st.rerun()


def reviews(client, session_id: str, *, active: bool):
    for delivery in client.coding_deliveries(session_id):
        proposal = delivery["proposal"]
        with st.expander(f"GitHub delivery: {proposal['title']} · {delivery['status']}"):
            st.write(f"{proposal['repository']} · {proposal['base_branch']} → {proposal['branch']}")
            st.caption(f"Base commit: {proposal['base_commit']} · source revision: {proposal['source_revision']}")
            st.code(proposal["diff"], language="diff")
            st.write(proposal["body"])
            for action in proposal["actions"]:
                st.write(action)
            if delivery.get("error"):
                st.warning(delivery["error"])
            if delivery.get("remote"):
                st.link_button("Open draft pull request", delivery["remote"]["url"])
            if delivery.get("journal"):
                with st.expander("Publication receipts"):
                    st.json(delivery["journal"])
            if st.button("Publish this draft PR", key=f"publish_{delivery['id']}", disabled=active or delivery["status"] != "prepared"):
                client.publish_coding_delivery(delivery["id"], delivery["digest"])
                st.rerun()
