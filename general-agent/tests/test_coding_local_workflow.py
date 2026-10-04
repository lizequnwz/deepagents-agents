"""Production local runtime through the API, without a provider or Docker."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from general_agent.api import create_app
from general_agent.config import Settings
from tests.fakes import FakeGraph
from tests.test_budgets import ScriptedModel
from tests.test_coding_api import fixture_project, open_session, tool_call, wait_for_attempt


def test_local_settings_are_default_and_selection_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("CODING_RUNTIME", raising=False)
    configured = Settings(project_root=tmp_path, model_name="test:model")
    assert configured.coding_runtime == "local"
    assert not replace(configured, coding_image="", coding_browser_image="").readiness_errors()
    assert "CODING_RUNTIME must be local or docker." in replace(configured, coding_runtime="automatic").readiness_errors()
    assert replace(configured, coding_runtime="docker", coding_image="").readiness_errors()
    assert replace(configured, coding_typescript_sdk=tmp_path.relative_to(tmp_path.parent)).readiness_errors()


def test_default_workbench_edits_checks_reviews_and_applies_without_docker(settings, monkeypatch):
    def docker_forbidden(*args, **kwargs):
        raise AssertionError("Local work must never construct Docker.")

    monkeypatch.setattr("general_agent.coding.runtime.DockerRuntime.__init__", docker_forbidden)
    root = fixture_project(settings)
    model = ScriptedModel(responses=[
        tool_call("read_file", {"file_path": "/repo/increment.py"}, "read"),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "edit"),
        tool_call("run_check", {"name": "tests"}, "check"),
        AIMessage(content="Changed and checked in the local working copy."),
    ])
    with TestClient(create_app(settings=replace(settings, run_timeout_seconds=20),
                              graph_override=FakeGraph(), coding_model=model)) as client:
        ready = client.get("/coding/readiness").json()
        assert ready["ready"] and ready["runtime"] == "local", ready
        assert ready["runtime_id"].startswith("local:")
        session = open_session(client, root)
        queued = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Fix increment", "mode": "implement"})
        assert queued.status_code == 202, queued.text
        result = wait_for_attempt(client, queued.json()["id"])
        assert result["status"] == "completed" and result["outcome"] == "verified", result
        assert result["runtime_identity"].startswith("local:")
        assert "value + 1" in (root / "increment.py").read_text()
        diff = client.get(f"/changes/{result['change_id']}/diff").json()
        assert "+    return value + 2" in diff["text"]
        foreign = {"X-Corp-ID": "OTHER_CORP"}
        assert client.get(f"/changes/{result['change_id']}/diff", headers=foreign).status_code == 404
        (root / "user.txt").write_text("Preserved outside edit")
        applied = client.post(f"/changes/{result['change_id']}/apply",
                              json={"expected_revision": diff["revision"], "paths": ["increment.py"]})
        assert applied.status_code == 200, applied.text
        assert "value + 2" in (root / "increment.py").read_text()
        assert (root / "user.txt").read_text() == "Preserved outside edit"


@pytest.mark.parametrize("mode", ["plan", "review"])
def test_local_inspection_never_starts_repository_runtime(settings, monkeypatch, mode):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Inspection must not start a command runtime.")

    monkeypatch.setattr("general_agent.coding.local_runtime.LocalRuntime.start", forbidden)
    root = fixture_project(settings)
    model = ScriptedModel(responses=[
        tool_call("read_file", {"file_path": "/repo/increment.py"}, "read"),
        AIMessage(content="Inspected source."),
    ])
    with TestClient(create_app(settings=settings, graph_override=FakeGraph(), coding_model=model)) as client:
        session = open_session(client, root)
        queued = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Inspect", "mode": mode}).json()
        result = wait_for_attempt(client, queued["id"])
        assert result["status"] == "completed" and result["outcome"] == "not_verified", result
        assert "value + 1" in (root / "increment.py").read_text()
