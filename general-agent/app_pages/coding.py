"""Repository workbench. All writes to original source require a visible action."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from general_agent.ui.api_client import APIError, AgentAPIClient
from general_agent.ui import coding_github

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
st.session_state.setdefault("corp_id", os.getenv("DEFAULT_CORP_ID", "A123456") or "A123456")


@st.cache_resource(max_entries=20)
def coding_client(url: str, corp_id: str) -> AgentAPIClient:
    return AgentAPIClient(url, corp_id)


client = coding_client(os.getenv("API_BASE_URL", "http://127.0.0.1:8001"), st.session_state["corp_id"])
st.title("Coding workbench", anchor=False)
st.caption("Open a local repository, work in an isolated copy, inspect checks and diffs, then apply selected files.")
try:
    ready = client.coding_readiness()
    if not ready["ready"]:
        st.warning("Implementation is unavailable: " + "; ".join(ready["errors"]))
    projects = client.projects()
    sessions = client.coding_sessions()
    with st.sidebar:
        st.caption(f"User {st.session_state['corp_id']}")
        with st.expander("Open a repository", icon=":material/folder_open:"):
            with st.form("open_repository"):
                root = st.text_input("Absolute repository folder")
                name = st.text_input("Project name")
                tests_command = st.text_input("Tests command", value="python -m pytest",
                                              help="Approve the test command to run inside the container.")
                build_command = st.text_input("Build command (optional)")
                documentation = st.text_input("Documentation websites (optional)",
                    help="Comma-separated exact hostnames, such as docs.python.org. Approves public HTTPS documentation requests through the application.")
                register = st.form_submit_button("Open project")
            if register:
                try:
                    checks = {name: command for name, command in {"tests": tests_command, "build": build_command}.items() if command.strip()}
                    client.register_project(root, name or Path(root).name, checks,
                                            [domain.strip() for domain in documentation.split(",") if domain.strip()])
                except (ValueError, APIError) as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        if projects:
            project_id = st.selectbox("Project", [p["id"] for p in projects],
                                      format_func=lambda value: next(p["name"] for p in projects if p["id"] == value))
            if st.button("New coding session", icon=":material/add:"):
                session = client.create_coding_session(project_id)
                st.query_params["session"] = session["id"]
                st.rerun()
        else:
            st.info("Open a repository to create a coding session.")
    if not sessions:
        st.stop()
    ids = [session["id"] for session in sessions]
    requested = st.query_params.get("session")
    index = ids.index(requested) if requested in ids else 0
    session_id = st.selectbox("Coding session", ids, index=index,
                              format_func=lambda value: next(s.get("name", value[:8]) for s in sessions if s["id"] == value))
    st.query_params["session"] = session_id
    session = client.coding_session(session_id)
    st.caption(f"Session {session_id[:8]} · original: {session['project']['root']}")
    attempts = session["attempts"]
    active = next((a for a in reversed(attempts) if a["status"] in {"queued", "running", "stopping", "waiting_input"}), None)
    github_connected = coding_github.connection(client, session["project_id"], active=bool(active))
    snowflake = client.coding_snowflake_status(session["project_id"])
    if snowflake["configured"]:
        with st.expander("Snowflake reads", icon=":material/database:"):
            st.json(snowflake["profile"])
            st.caption("This profile permits schema inspection and bounded table reads. Queries may incur warehouse costs. Credentials stay in the application.")
            label = "Disable Snowflake reads" if snowflake["enabled"] else "Enable these Snowflake reads"
            if st.button(label, disabled=bool(active)):
                client.enable_coding_snowflake(session["project_id"], not snowflake["enabled"], snowflake["digest"])
                st.rerun()
    with st.expander("Dependencies", icon=":material/package_2:"):
        st.caption("Prepare locked public packages in a separate container. Coding commands stay offline. Private registries, local packages and online source builds are unavailable.")
        for kind, setup in client.coding_setup(session_id).items():
            prepared = setup.get("prepared")
            current = bool(prepared and prepared["status"] == "ready"
                           and prepared["manifest_identity"] == setup["manifest_identity"]
                           and prepared["image_id"] == ready.get("image_id"))
            st.caption(f"{kind.capitalize()} · {'prepared' if current else 'not prepared'}")
            if setup["ready"]:
                st.write("Locked files: " + ", ".join(setup["files"]))
                if st.button(f"Prepare {kind} dependencies", key=f"setup_{kind}", disabled=bool(active) or not ready["ready"]):
                    client.prepare_coding_setup(session_id, kind, setup["manifest_identity"])
                    st.rerun()
            else:
                st.caption("; ".join(setup["blockers"]))
    mode = st.segmented_control("Task mode", ["plan", "implement", "review"], default="plan")
    with st.form("coding_task"):
        message = st.text_area("Task", placeholder="Describe the change or review you need.")
        submit = st.form_submit_button("Start task", disabled=bool(active) or (mode == "implement" and not ready["ready"]))
    if submit and message.strip():
        client.coding_task(session_id, message, mode or "plan")
        st.rerun()
    if active:
        with st.container(horizontal=True):
            st.badge(active["status"], color="blue")
            if st.button("Stop task", icon=":material/stop:"):
                client.stop_coding_run(active["id"])
                st.rerun()
        if active["status"] == "waiting_input":
            pending = client.coding_decision_status(active["input_decision_id"])
            st.info(pending["question"])
            if pending.get("options"):
                st.caption("Suggested answers: " + " · ".join(pending["options"]))
            with st.form("coding_input"):
                answer = st.text_area("Your answer")
                if st.form_submit_button("Answer and resume") and answer.strip():
                    client.answer_coding_input(pending["id"], answer)
                    st.rerun()
        elif active["mode"] != "setup":
            with st.form("steer_task"):
                steer = st.text_input("Follow-up instruction")
                if st.form_submit_button("Queue follow-up") and steer.strip():
                    client.steer_coding_run(active["id"], steer)

        @st.fragment(run_every="1s")
        def progress(run_id):
            key = f"coding_events:{st.session_state['corp_id']}:{run_id}"
            state = st.session_state.setdefault(key, {"cursor": 0, "events": []})
            result = client.coding_run(run_id, after=state["cursor"])
            state["events"] = [*state["events"], *result["events"]][-20:]
            state["cursor"] = result["next_cursor"]
            for process in client.coding_processes(run_id):
                with st.expander(f"Process: {process['command'][:100]} · {process['state']}"):
                    log_key = f"coding_process:{st.session_state['corp_id']}:{run_id}:{process['id']}"
                    log = st.session_state.setdefault(log_key, {"cursor": 0, "output": ""})
                    page = client.coding_process_output(run_id, process["id"], log["cursor"])
                    log["output"] = (log["output"] + page["output"])[-12_000:]
                    log["cursor"] = page["cursor"]
                    if page["gap"]:
                        st.caption("Earlier output was discarded from the bounded log.")
                    st.code(log["output"], language="text")
                    if process["state"] in {"starting", "running"} and st.button("Stop process", key=f"stop_process_{process['id']}"):
                        client.stop_coding_process(run_id, process["id"])
            for event in state["events"]:
                st.caption(event.get("label") or event.get("kind", "Progress"))
                if event.get("output"):
                    st.code(event["output"], language="text")
            if result["status"] not in {"queued", "running", "stopping"}:
                st.rerun()

        if active["status"] != "waiting_input":
            progress(active["id"])
    for attempt in reversed(attempts):
        if attempt["status"] in {"queued", "running", "stopping", "waiting_input"}:
            continue
        with st.container(border=True):
            st.markdown(f"**{attempt['mode'].capitalize()} · {attempt['status']} · {attempt.get('outcome', 'not_verified')}**")
            st.write(attempt["message"])
            if attempt.get("answer"):
                st.markdown(attempt["answer"])
            if attempt.get("error"):
                st.error(attempt["error"])
            if attempt.get("setup"):
                with st.expander("Dependency preparation log"):
                    st.code(attempt["setup"].get("logs", ""), language="text")
            for check in attempt.get("checks", []):
                st.caption(f"{check['name']} · {check.get('phase', 'final')} · {check['status']} · exit {check.get('exit_code')}")
                with st.expander(f"Check log: {check['name']}"):
                    st.code(check.get("output", ""), language="text")
            for process in attempt.get("processes", []):
                with st.expander(f"Process log: {process['command'][:100]}"):
                    st.caption(process["state"])
                    st.code(process.get("output", ""), language="text")
            for check in attempt.get("browser_checks", []):
                with st.expander(f"Browser: {check['path']} · {check['status']}"):
                    if check.get("reason"):
                        st.caption(check["reason"])
                    if check.get("image"):
                        st.image(client.coding_browser_image(attempt["id"], check["id"]), caption="Captured from the isolated preview")
            if attempt.get("decision_id"):
                decision = client.coding_decision_status(attempt["decision_id"])
                pending = decision["status"] == "pending"
                if not pending:
                    st.caption(f"Plan decision: {decision['status']}")
                with st.container(horizontal=True):
                    if st.button("Approve plan and implement", key=f"approve_{attempt['id']}", disabled=not pending or bool(active) or not ready["ready"]):
                        client.coding_decision(attempt["decision_id"], "approve")
                        st.rerun()
                    if st.button("Reject plan", key=f"reject_{attempt['id']}", disabled=not pending):
                        client.coding_decision(attempt["decision_id"], "reject")
                        st.rerun()
            if attempt.get("change_id"):
                diff = client.coding_diff(attempt["change_id"])
                with st.expander("Review changes", expanded=True):
                    st.code(diff.get("text", ""), language="diff")
                    paths = [item["path"] for item in diff.get("files", [])]
                    selected = st.multiselect("Files to apply", paths, default=paths, key=f"files_{attempt['id']}")
                    st.caption("Keep the original checkout stable while applying. Intervening edits produce a conflict. Applying does not commit or publish.")
                    rejected = diff.get("review_status") == "rejected"
                    if rejected:
                        st.caption("Rejected. The isolated copy was restored to its accepted baseline.")
                    if st.button("Apply selected files to original", key=f"apply_{attempt['id']}", disabled=bool(active) or not selected or rejected):
                        client.apply_coding_change(attempt["change_id"], diff["revision"], selected)
                        st.rerun()
                    if st.button("Reject change proposal", key=f"reject_change_{attempt['id']}", disabled=bool(active) or rejected or bool(diff.get("apply_journal"))):
                        client.reject_coding_change(attempt["change_id"], diff["revision"])
                        st.rerun()
                    if diff.get("apply_journal") and st.button("Revert this application", key=f"revert_{attempt['id']}", disabled=bool(active)):
                        client.revert_coding_change(attempt["change_id"], diff["revision"])
                        st.rerun()
                if github_connected and paths and not rejected:
                    coding_github.prepare(client, attempt, active=bool(active))
            if attempt["mode"] != "setup" and attempt["status"] in {"failed", "stopped"} and st.button("Continue as a new attempt", key=f"continue_{attempt['id']}", disabled=bool(active)):
                client.coding_task(session_id, attempt["message"], attempt["mode"], parent_id=attempt["id"])
                st.rerun()
    if github_connected:
        coding_github.reviews(client, session_id, active=bool(active))
except APIError as exc:
    st.error(str(exc), icon=":material/error:")
