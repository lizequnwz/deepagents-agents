"""Provider-free API workflow with real agent tools and fixture-only checks."""

import hashlib
import os
import sys
import time
import sqlite3
import json
import pytest


from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from general_agent.api import create_app
from general_agent.processes import ProcessSupervisor
from tests.fakes import FakeGraph
from tests.test_budgets import ScriptedModel


class FixtureRuntime:
    """Test injection only; production never selects this runtime."""
    identity = "fixture-image-v1"
    runtime_id = "fixture-image-v1"
    executions = 0

    def __init__(self, settings, repo, owner_id):
        self.settings, self.repo, self.owner_id = settings, repo, owner_id

    @classmethod
    async def check_readiness(cls, settings):
        return {"ready": True, "errors": [], "runtime": "local", "runtime_id": cls.runtime_id}

    @classmethod
    async def cleanup_owner(cls, settings, owner_id):
        return None

    async def start(self):
        pass

    async def sync_to_runtime(self):
        pass

    def track_source(self, paths):
        self.source_paths = paths

    async def sync_from_runtime(self):
        pass

    async def close(self):
        pass

    async def execute(self, command, timeout=None):
        type(self).executions += 1
        assert command == "python -m unittest discover -s tests"
        return await ProcessSupervisor().run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            owner_id=self.owner_id, cwd=self.repo,
            env={"PATH": os.path.dirname(sys.executable), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=timeout or 5, max_output_bytes=5000,
        )


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def wait_for_attempt(client, attempt_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(f"/coding/runs/{attempt_id}").json()
        if result["status"] not in {"queued", "running", "stopping"}:
            return result
        time.sleep(0.02)
    raise AssertionError("Coding attempt did not finish.")


def fixture_project(settings):
    root = settings.project_root / "source"
    (root / "tests").mkdir(parents=True)
    (root / "increment.py").write_text("def increment(value):\n    return value + 1\n")
    (root / "tests/test_increment.py").write_text(
        "import unittest\nfrom increment import increment\n"
        "class Tests(unittest.TestCase):\n    def test_increment(self):\n        self.assertEqual(increment(1), 3)\n")
    (root / "user.txt").write_text("unrelated dirty user file")
    return root


def open_session(client, root):
    response = client.post("/projects", json={"root": str(root), "name": "Fixture",
        "checks": {"tests": "python -m unittest discover -s tests"}})
    assert response.status_code == 201, response.text
    project = response.json()
    response = client.post(f"/projects/{project['id']}/sessions")
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("mode", ["plan", "review"])
def test_read_only_modes_use_compiler_helper_without_source_execution(settings, mode):
    instances = []
    class CompilerFixture(FixtureRuntime):
        def __init__(self, *args):
            super().__init__(*args)
            instances.append(self)
            self.closed = False
        async def language_probe(self, request):
            assert request["operation"] == "symbols"
            assert [doc["path"] for doc in request["documents"]] == ["app.ts"]
            return {"protocol": 1, "typescript_version": "5.9.3", "symbols": [
                {"id": "ts:fixture", "name": "value", "path": "app.ts", "line": 1, "column": 13}], "truncated": False}
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("Read-only compiler navigation cannot execute source.")
        async def close(self):
            self.closed = True
    root = fixture_project(settings)
    (root / "app.ts").write_text("export const value = 1;\n")
    model = ScriptedModel(responses=[tool_call("symbols", {"path": "app.ts"}, "symbols"), AIMessage(content="Inspected.")])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_model=model,
                               coding_runtime_factory=CompilerFixture)) as client:
        session = open_session(client, root)
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Inspect symbols", "mode": mode}).json()
        attempt = wait_for_attempt(client, task["id"])
        assert attempt["status"] == "completed", attempt
        assert attempt["runtime_identity"] == "inspection-only"
        assert len(instances) == 1 and instances[0].closed
        returned = next(message for message in model.calls[-1] if getattr(message, "name", None) == "symbols")
        assert json.loads(returned.content)["symbols"][0]["name"] == "value"
        assert client.get(f"/changes/{attempt['change_id']}/diff").json()["files"] == []


def test_browser_screenshot_process_archive_and_corporation_scope(settings):
    from tests.test_coding_process_sessions import PreviewRuntime

    class BrowserFixture(PreviewRuntime, FixtureRuntime):
        pass
    class BrowserModel(ScriptedModel):
        def _generate(self, messages, *args, **kwargs):
            if getattr(messages[-1], "name", None) == "start_process":
                process = json.loads(messages[-1].content)
                self.responses[self.i] = tool_call("browser_check", {"process_id": process["id"],
                    "selector": "h1", "expected_text": "Hello"}, "browser")
            return super()._generate(messages, *args, **kwargs)
    root = fixture_project(settings)
    model = BrowserModel(responses=[tool_call("start_process", {"command": "fixture server", "port": 8080,
        "browser": True}, "start"), AIMessage(content="placeholder"), AIMessage(content="Observed the preview.")])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_model=model,
                               coding_runtime_factory=BrowserFixture)) as client:
        session = open_session(client, root)
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Check preview", "mode": "implement"}).json()
        attempt = wait_for_attempt(client, task["id"])
        assert attempt["status"] == "completed", attempt.get("error")
        assert attempt["outcome"] == "not_verified"  # A screenshot cannot replace the approved tests.
        check = attempt["browser_checks"][0]
        assert check["status"] == "passed"
        image_path = f"/coding/runs/{task['id']}/browser/{check['id']}/image"
        response = client.get(image_path)
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")
        assert client.get(image_path, headers={"X-Corp-ID": "OTHER_CORP"}).status_code == 404
        archived = client.get(f"/coding/runs/{task['id']}/processes").json()[0]
        assert archived["state"] == "stopped"
        output_path = f"/coding/runs/{task['id']}/processes/{archived['id']}"
        assert "ready" in client.get(output_path).json()["output"]
        assert client.get(output_path, params={"cursor": archived["cursor"]}).json()["output"] == ""
        assert client.get(output_path, headers={"X-Corp-ID": "OTHER_CORP"}).status_code == 404


def test_setup_cleanup_failure_is_durable_and_recovered_without_replay(settings):
    class CleanupFailure(FixtureRuntime):
        @classmethod
        async def cleanup_owner(cls, settings, owner_id):
            raise RuntimeError("Container removal failed")
    root = fixture_project(settings)
    (root / "requirements.txt").write_text("example==1.0 --hash=sha256:" + "a" * 64 + "\n")
    app = create_app(settings=settings, graph_override=FakeGraph(), coding_runtime_factory=CleanupFailure)
    prepared_calls = []
    with TestClient(app) as client:
        session = open_session(client, root)
        async def prepare(*args, **kwargs):
            prepared_calls.append(args)
            return {"status": "blocked", "logs": "", "blockers": ["Fixture dependency unavailable"]}
        app.state.coding.setups.prepare = prepare
        setup = client.get(f"/sessions/{session['id']}/setup").json()["python"]
        submitted = client.post(f"/sessions/{session['id']}/setup", json={"kind": "python",
            "manifest_identity": setup["manifest_identity"]})
        assert submitted.status_code == 202, submitted.text
        attempt = wait_for_attempt(client, submitted.json()["id"])
        assert attempt["status"] == "failed" and attempt["cleanup_pending"]
        assert attempt["error"] == "Container removal failed"
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_runtime_factory=FixtureRuntime)) as client:
        recovered = client.get(f"/coding/runs/{attempt['id']}").json()
        assert recovered["status"] == "failed" and not recovered.get("cleanup_pending")
    assert len(prepared_calls) == 1


def test_edit_check_diff_apply_revert_and_corporation_scope(settings):
    root = fixture_project(settings)
    model = ScriptedModel(responses=[
        tool_call("read_file", {"file_path": "/repo/increment.py"}, "read"),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "edit"),
        tool_call("run_check", {"name": "tests"}, "check"),
        AIMessage(content="Implemented and checked."),
    ])
    app = create_app(settings=settings, graph_override=FakeGraph(),
                     coding_model=model, coding_runtime_factory=FixtureRuntime)
    with TestClient(app) as client:
        session = open_session(client, root)
        response = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Fix increment", "mode": "implement"})
        assert response.status_code == 202
        attempt = wait_for_attempt(client, response.json()["id"])
        assert attempt["status"] == "completed", attempt
        assert attempt["outcome"] == "verified", attempt
        assert attempt["checks"][0]["status"] == "passed"
        assert "value + 1" in (root / "increment.py").read_text()
        change = client.get(f"/changes/{attempt['change_id']}/diff").json()
        assert "+    return value + 2" in change["text"]
        foreign = {"X-Corp-ID": "OTHER_CORP"}
        for path in [f"/sessions/{session['id']}", f"/coding/runs/{attempt['id']}",
                     f"/changes/{attempt['change_id']}/diff", f"/runs/{attempt['id']}/checks"]:
            assert client.get(path, headers=foreign).status_code == 404
        (root / "user.txt").write_text("new external edit")
        applied = client.post(f"/changes/{attempt['change_id']}/apply", json={"expected_revision": change["revision"]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied_verification"] == "stale"
        assert "value + 2" in (root / "increment.py").read_text()
        assert (root / "user.txt").read_text() == "new external edit"
        accepted = client.get(f"/sessions/{session['id']}").json()["accepted_snapshot"]
        assert accepted["files"]["increment.py"]["sha256"] == hashlib.sha256((root / "increment.py").read_bytes()).hexdigest()
        reverted = client.post(f"/changes/{attempt['change_id']}/revert", json={"expected_revision": change["revision"]})
        assert reverted.status_code == 200, reverted.text
        assert "value + 1" in (root / "increment.py").read_text()
        assert (root / "user.txt").read_text() == "new external edit"


def test_missing_checks_cannot_be_certified_by_model_prose(settings):
    root = fixture_project(settings)
    model = ScriptedModel(responses=[AIMessage(content="All tests pass. Everything is verified.")])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(),
                    coding_model=model, coding_runtime_factory=FixtureRuntime)) as client:
        session = open_session(client, root)
        attempt = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Inspect", "mode": "review"}).json()
        result = wait_for_attempt(client, attempt["id"])
        assert result["outcome"] == "not_verified"
        assert result["checks"][0]["status"] == "not_run"


def test_input_resume_keeps_budget_and_does_not_replay_completed_execution(settings):
    root = fixture_project(settings)
    FixtureRuntime.executions = 0
    model = ScriptedModel(responses=[
        tool_call("execute", {"command": "python -m unittest discover -s tests"}, "before"),
        tool_call("request_input", {"question": "Which increment?", "options": ["Two", "Three"]}, "ask"),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "edit"),
        tool_call("run_check", {"name": "tests"}, "check"),
        AIMessage(content="Used the answer and checked."),
    ])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(),
                    coding_model=model, coding_runtime_factory=FixtureRuntime)) as client:
        session = open_session(client, root)
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Fix", "mode": "implement"}).json()
        waiting = wait_for_attempt(client, task["id"])
        assert waiting["status"] == "waiting_input", waiting
        assert waiting["outcome"] == "not_verified"
        assert FixtureRuntime.executions == 1
        decision = client.get(f"/decisions/{waiting['input_decision_id']}").json()
        assert decision["question"] == "Which increment?"
        assert client.post(f"/decisions/{decision['id']}/respond", json={"response": "approve"}).status_code == 409
        assert client.post(f"/decisions/{decision['id']}/input", headers={"X-Corp-ID": "OTHER_CORP"}, json={"message": "Two"}).status_code == 404
        resumed = client.post(f"/decisions/{decision['id']}/input", json={"message": "Two"})
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["id"] == task["id"]
        completed = wait_for_attempt(client, task["id"])
        assert completed["status"] == "completed", completed
        assert completed["outcome"] == "verified", completed
        assert completed["usage"]["model_calls"] == 5
        assert completed["usage"]["tool_calls"] == 5  # pure input tool resumes once
        assert FixtureRuntime.executions == 2
        assert client.post(f"/decisions/{decision['id']}/input", json={"message": "Two"}).status_code == 409
        assert "value + 1" in (root / "increment.py").read_text()


def test_waiting_input_survives_restart_and_can_be_stopped(settings):
    root = fixture_project(settings)
    model = ScriptedModel(responses=[tool_call("request_input", {"question": "Target?"}, "ask"), AIMessage(content="Planned")])
    options = dict(settings=settings, graph_override=FakeGraph(), coding_model=model, coding_runtime_factory=FixtureRuntime)
    with TestClient(create_app(**options)) as client:
        session = open_session(client, root)
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Plan", "mode": "plan"}).json()
        waiting = wait_for_attempt(client, task["id"])
        assert waiting["status"] == "waiting_input", waiting
    with TestClient(create_app(**options)) as client:
        reopened = client.get(f"/coding/runs/{task['id']}").json()
        assert reopened["status"] == "waiting_input"
        assert client.post(f"/coding/runs/{task['id']}/stop").json()["status"] == "stopped"
        assert client.post(f"/decisions/{waiting['input_decision_id']}/input", json={"message": "A"}).status_code == 409


def test_historical_check_becomes_stale_after_later_edit(settings):
    root = fixture_project(settings)
    model = ScriptedModel(responses=[
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "fix"),
        tool_call("run_check", {"name": "tests"}, "check"), AIMessage(content="Checked"),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 2", "new_string": "value + 3"}, "change"),
        AIMessage(content="Changed again"),
    ])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_model=model,
                              coding_runtime_factory=FixtureRuntime)) as client:
        session = open_session(client, root)
        first = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Fix", "mode": "implement"}).json()
        assert wait_for_attempt(client, first["id"])["outcome"] == "verified"
        second = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Change again", "mode": "implement"}).json()
        wait_for_attempt(client, second["id"])
        assert client.get(f"/runs/{first['id']}/checks").json()[0]["status"] == "stale"
        assert client.get(f"/coding/runs/{first['id']}").json()["outcome"] == "not_verified"
        with sqlite3.connect(settings.coding_db) as connection:
            saved = connection.execute("SELECT payload FROM attempts WHERE id=?", (first["id"],)).fetchone()[0]
        assert json.loads(saved)["check_evidence"][0]["status"] == "passed"


def test_explicit_dependency_preparation_is_queued_scoped_and_installed(settings, monkeypatch):
    root = fixture_project(settings)
    (root / "requirements.txt").write_text("approved fixture lock")

    class FixtureSetup:
        def __init__(self, settings):
            pass

        def describe(self, corp, sid, repo, kind):
            if kind != "python":
                return {"kind": kind, "ready": False, "files": [], "manifest_identity": None, "blockers": ["No lock"]}
            return {"kind": kind, "ready": True, "files": ["requirements.txt"], "blockers": [],
                    "manifest_identity": hashlib.sha256((repo / "requirements.txt").read_bytes()).hexdigest()}

        async def prepare(self, corp, sid, repo, kind, *, setup_id):
            return {"id": setup_id, "corp_id": corp, "session_id": sid, "kind": kind, "status": "ready",
                    "manifest_identity": self.describe(corp, sid, repo, kind)["manifest_identity"],
                    "runtime_id": "fixture-image-v1", "dependency_identity": "fixture-packages-v1", "logs": "Fixture prepared", "blockers": []}

    class PreparedRuntime(FixtureRuntime):
        installed = []

        async def install_setup(self, record):
            type(self).installed.append(record)
            self.identity = "fixture-image-v1:fixture-packages-v1"

    monkeypatch.setattr("general_agent.coding.service.SetupManager", FixtureSetup)
    model = ScriptedModel(responses=[AIMessage(content="Inspected prepared environment")])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_model=model,
                              coding_runtime_factory=PreparedRuntime)) as client:
        session = open_session(client, root)
        description = client.get(f"/sessions/{session['id']}/setup").json()["python"]
        body = {"kind": "python", "manifest_identity": description["manifest_identity"]}
        assert client.post(f"/sessions/{session['id']}/setup", json={**body, "manifest_identity": "0" * 64}).status_code == 409
        assert client.post(f"/sessions/{session['id']}/setup", headers={"X-Corp-ID": "OTHER_CORP"}, json=body).status_code == 404
        queued = client.post(f"/sessions/{session['id']}/setup", json=body)
        assert queued.status_code == 202, queued.text
        result = wait_for_attempt(client, queued.json()["id"])
        assert result["status"] == "completed", result
        assert result["setup"]["id"] == result["id"]
        assert result["usage"]["model_calls"] == 0
        assert not model.calls
        prepared = client.get(f"/sessions/{session['id']}/setup").json()["python"]["prepared"]
        assert prepared["id"] == result["id"]
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Inspect", "mode": "implement"}).json()
        assert wait_for_attempt(client, task["id"])["status"] == "completed"
        assert PreparedRuntime.installed == [prepared]


async def test_approved_plan_revalidated_at_queued_execution(settings):
    from langgraph.checkpoint.memory import InMemorySaver
    from general_agent.coding.service import CodingService
    from general_agent.coding.store import CodingStore

    root = fixture_project(settings)
    store = CodingStore(settings.coding_db)
    model = ScriptedModel(responses=[AIMessage(content="Change increment to two")])
    service = CodingService(settings, store, InMemorySaver(), runtime_factory=FixtureRuntime, model=model)
    try:
        project = await service.register("A123456", str(root), "Fixture", {})
        session = await service.create_session("A123456", project["id"])
        plan = await service.submit("A123456", session["id"], "Plan increment", "plan")
        await service._drive(store.claim(1))
        planned = store.attempt("A123456", plan["id"])
        queued = await service.respond("A123456", planned["decision_id"], "approve")
        repo = service.projects.repository("A123456", session["id"])
        (repo / "increment.py").write_text("def increment(value):\n    return value + 10\n")
        await service._drive(store.claim(1))
        result = store.attempt("A123456", queued["id"])
        assert result["status"] == "failed", result
        assert "approved plan is stale" in result["error"]
        assert len(model.calls) == 1
        assert "value + 1" in (root / "increment.py").read_text()
    finally:
        await service.close()
        store.close()
