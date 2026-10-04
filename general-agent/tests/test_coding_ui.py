"""Workbench interaction tests without a server or configured provider."""

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from general_agent.ui import api_client


class WorkbenchClient:
    def __init__(self):
        self.applied = False
        self.stopped = False
        self.active = False
        self.opened = None
        self.submitted = None
        self.prepared = None
        self.session_id = "s1"
        self.setup_available = False
        self.attempt = {"id": "a1", "session_id": "s1", "mode": "implement",
                        "status": "completed", "outcome": "not_verified", "message": "Fix a bug",
                        "answer": "Changed a.py", "checks": [], "change_id": "c1"}

    def coding_readiness(self):
        return {"ready": True, "errors": []}

    def projects(self):
        return [{"id": "p1", "name": "Fixture"}]

    def coding_sessions(self):
        return [{"id": self.session_id}]

    def coding_session(self, sid):
        return {"id": sid, "project_id": "p1", "project": {"root": "/original"}, "attempts": [self.attempt]}

    def coding_github_status(self, project_id):
        return {"configured": False, "connection": None}

    def coding_snowflake_status(self, project_id):
        return {"configured": False, "enabled": False}

    def coding_setup(self, sid):
        if self.setup_available:
            return {"python": {"ready": True, "files": ["requirements.txt"],
                               "manifest_identity": "f" * 64, "prepared": None}}
        return {kind: {"ready": False, "blockers": ["No lock file"], "prepared": None}
                for kind in ("python", "node")}

    def register_project(self, root, name, checks, domains):
        self.opened = (root, name, checks, domains)

    def create_coding_session(self, project_id):
        assert project_id == "p1"
        self.session_id = "s2"
        return {"id": self.session_id}

    def coding_task(self, session_id, message, mode, **links):
        self.submitted = (session_id, message, mode)
        return self.attempt

    def prepare_coding_setup(self, sid, kind, manifest):
        self.prepared = (sid, kind, manifest)

    def coding_decision_status(self, decision_id):
        return {"id": decision_id, "kind": "input", "question": "Choose target", "options": ["A", "B"], "status": "pending"}

    def answer_coding_input(self, decision_id, message):
        self.submitted = (decision_id, message, "input")
        self.attempt.update(status="completed", input_decision_id=None)

    def coding_diff(self, cid):
        result = {"revision": "revision1", "text": "-bug\n+fixed", "files": [{"path": "a.py"}]}
        if self.applied:
            result["apply_journal"] = "j1"
        return result

    def apply_coding_change(self, cid, revision, paths):
        assert (cid, revision, paths) == ("c1", "revision1", ["a.py"])
        self.applied = True

    def coding_run(self, aid, after=0):
        return {**self.attempt, "events": [{"kind": "check_started", "label": "Running tests"}], "next_cursor": 1}

    def coding_processes(self, aid):
        return []

    def stop_coding_run(self, aid):
        self.stopped = True
        self.attempt["status"] = "stopped"


def page(monkeypatch, client):
    st.cache_resource.clear()
    monkeypatch.setattr(api_client, "AgentAPIClient", lambda *args, **kwargs: client)
    return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_pages/coding.py"), default_timeout=10).run()


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def test_workbench_review_and_explicit_apply(monkeypatch):
    client = WorkbenchClient()
    app = page(monkeypatch, client)
    assert not app.exception
    assert any("+fixed" in code.value for code in app.code)
    assert not client.applied
    button(app, "Apply selected files to original").click().run()
    assert not app.exception
    assert client.applied
    assert button(app, "Revert this application")


def test_workbench_stop_is_available_during_a_task(monkeypatch):
    client = WorkbenchClient()
    client.attempt["status"] = "running"
    app = page(monkeypatch, client)
    assert not app.exception
    assert button(app, "Start task").disabled
    button(app, "Stop task").click().run()
    assert not app.exception
    assert client.stopped


def test_workbench_open_project_create_session_and_start_task(monkeypatch):
    client = WorkbenchClient()
    app = page(monkeypatch, client)
    def text(label):
        return next(widget for widget in app.text_input if widget.label == label)
    text("Absolute repository folder").set_value("/original")
    text("Project name").set_value("Source")
    text("Documentation websites (optional)").set_value("docs.python.org, developer.mozilla.org")
    button(app, "Open project").click().run()
    assert not app.exception
    assert client.opened == ("/original", "Source", {"tests": "python -m pytest"}, ["docs.python.org", "developer.mozilla.org"])
    button(app, "New coding session").click().run()
    assert not app.exception
    assert app.query_params["session"] == ["s2"]
    next(widget for widget in app.text_area if widget.label == "Task").set_value("Inspect imports")
    button(app, "Start task").click().run()
    assert not app.exception
    assert client.submitted == ("s2", "Inspect imports", "plan")


def test_workbench_prepares_exact_lock_and_answers_pending_input(monkeypatch):
    client = WorkbenchClient()
    client.setup_available = True
    app = page(monkeypatch, client)
    button(app, "Prepare python dependencies").click().run()
    assert not app.exception
    assert client.prepared == ("s1", "python", "f" * 64)
    client.attempt.update(status="waiting_input", input_decision_id="question1")
    app.run()
    assert not app.exception
    assert button(app, "Start task").disabled
    next(widget for widget in app.text_area if widget.label == "Your answer").set_value("A")
    button(app, "Answer and resume").click().run()
    assert not app.exception
    assert client.submitted == ("question1", "A", "input")


def test_github_review_publishes_only_after_explicit_button(monkeypatch):
    class ConnectedClient(WorkbenchClient):
        published = None
        def coding_github_status(self, project_id):
            return {"configured": True, "connection": {"owner": "owner", "repository": "source",
                "identity": {"full_name": "owner/source", "url": "https://github.com/owner/source"}}}
        def coding_deliveries(self, sid):
            return [{"id": "delivery1", "digest": "reviewed-digest", "status": "prepared",
                     "proposal": {"title": "Repair", "repository": "owner/source", "base_branch": "main",
                                  "branch": "codex/repair", "base_commit": "remote-base", "source_revision": "revision1",
                                  "diff": "-bug\n+fixed", "body": "Checked locally", "actions": ["Create draft pull request"]}}]
        def publish_coding_delivery(self, delivery_id, digest):
            self.published = (delivery_id, digest)
    client = ConnectedClient()
    app = page(monkeypatch, client)
    assert not app.exception
    assert not client.published
    button(app, "Publish this draft PR").click().run()
    assert not app.exception
    assert client.published == ("delivery1", "reviewed-digest")


def test_snowflake_enabling_binds_the_displayed_profile(monkeypatch):
    class ScopedClient(WorkbenchClient):
        enabled = False
        def coding_snowflake_status(self, project_id):
            return {"configured": True, "enabled": self.enabled, "digest": "profile-digest",
                    "profile": {"role": "READER", "warehouse": "DEV", "tables": ["APP.PUBLIC.EVENTS"]}}
        def enable_coding_snowflake(self, project_id, enabled, digest):
            assert (project_id, digest) == ("p1", "profile-digest")
            self.enabled = enabled
    client = ScopedClient()
    app = page(monkeypatch, client)
    assert not app.exception and not client.enabled
    button(app, "Enable these Snowflake reads").click().run()
    assert not app.exception and client.enabled
    button(app, "Disable Snowflake reads").click().run()
    assert not app.exception and not client.enabled
