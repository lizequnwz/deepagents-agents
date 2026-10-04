"""Immutable GitHub review and single-use publication with a mock API only."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from general_agent.api import create_app
from general_agent.coding.changes import ChangeManager
from general_agent.coding.github import GitHubConnector, GitHubDelivery, GitHubError
from general_agent.coding.store import CodingConflict, CodingStore
from tests.fakes import FakeGraph
from tests.test_budgets import ScriptedModel
from tests.test_coding_api import FixtureRuntime, fixture_project, open_session, tool_call, wait_for_attempt

CORP = "A123456"
SESSION = "1" * 32
BASE = "2" * 40
TREE = "3" * 40
NEW_TREE = "4" * 40
COMMIT = "5" * 40
TOKEN = "fixture-only-secret"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class Remote:
    def __init__(self, before: dict[str, bytes]):
        self.before = before
        self.requests = []
        self.base = BASE
        self.fail = None
        self.branch = None
        self.repository_id = 17
        self.dirty = False

    def __call__(self, request):
        assert request.url.host == "api.github.com"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
        path = request.url.path.removeprefix("/repos/example/project")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        if request.method == "POST":
            if path == self.fail:
                raise httpx.ReadTimeout("fixture failure", request=request)
            if path == "/git/trees":
                assert body["base_tree"] == TREE  # Unrelated remote files remain in this base tree.
                return httpx.Response(201, json={"sha": NEW_TREE})
            if path == "/git/commits":
                return httpx.Response(201, json={"sha": COMMIT, "tree": {"sha": NEW_TREE}, "parents": [{"sha": BASE}]})
            if path == "/git/refs":
                self.branch = body["ref"].removeprefix("refs/heads/")
                return httpx.Response(201, json={"ref": body["ref"], "object": {"sha": COMMIT, "type": "commit"}})
            if path == "/pulls":
                return httpx.Response(201, json={"number": 42, "draft": True,
                    "head": {"ref": self.branch, "sha": COMMIT, "repo": {"id": self.repository_id}},
                    "base": {"ref": "main", "sha": BASE, "repo": {"id": self.repository_id}}})
            raise AssertionError(path)
        if path == "":
            return httpx.Response(200, json={"id": self.repository_id, "full_name": "example/project", "default_branch": "main"})
        if path.startswith("/git/ref/heads/"):
            branch = path.removeprefix("/git/ref/heads/")
            if branch != "main":
                return httpx.Response(404)
            return httpx.Response(200, json={"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.base}})
        if path == f"/git/commits/{BASE}":
            return httpx.Response(200, json={"sha": BASE, "tree": {"sha": TREE}})
        if path == f"/git/trees/{TREE}":
            return httpx.Response(200, json={"sha": TREE, "tree": [
                {"path": path, "type": "blob", "mode": "100644", "sha": "f" * 40 if self.dirty else git_blob(data)}
                for path, data in self.before.items()]})
        if path == "/issues/7":
            return httpx.Response(200, json={"number": 7, "title": "Fix increment", "body": f"Untrusted issue {TOKEN}", "state": "open"})
        if path == "/issues":
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    @property
    def posts(self):
        return [request for request in self.requests if request[0] == "POST"]


def frozen(settings):
    root = settings.project_root / "github-source"
    root.mkdir()
    (root / "app.py").write_text("old\n")
    changes = ChangeManager(settings)
    before = changes.capture(CORP, SESSION, root)
    (root / "app.py").write_text("new\n")
    change = changes.finalize(CORP, SESSION, before, root, "a" * 32)
    return changes, change


def ledger(settings):
    store = CodingStore(settings.coding_db)
    store.register_project(CORP, {"id": "p1", "root": str(settings.project_root / "registered")})
    store.add_session(CORP, {"id": SESSION, "project_id": "p1"})
    return store


async def test_complete_review_then_single_use_draft_publication(settings):
    changes, change = frozen(settings)
    store = ledger(settings)
    remote = Remote({"app.py": b"old\n", "unrelated.txt": b"keep"})
    connector = GitHubConnector(CORP, TOKEN, "example", "project", transport=httpx.MockTransport(remote))
    delivery = GitHubDelivery(connector, store.record_delivery, changes.blob)
    evidence = {"outcome": "verified", "runtime_identity": "runtime", "checks": [
        {"name": "tests", "command": "pytest", "phase": "baseline", "status": "failed", "exit_code": 1},
        {"name": "tests", "command": "pytest", "status": "passed", "exit_code": 0,
         "revision": change["after_revision"], "runtime_identity": "runtime"}]}
    try:
        prepared = await delivery.prepare(CORP, SESSION, change, evidence, "Fix app", "Behavior and checks")
        assert not remote.posts
        assert "+new" in prepared["proposal"]["diff"]
        assert prepared["proposal"]["base_commit"] == BASE
        assert prepared["proposal"]["verification"]["outcome"] == "verified"
        with pytest.raises(KeyError):
            store.delivery("OTHER_CORP", prepared["id"])
        published = await delivery.publish(CORP, prepared, expected_digest=prepared["digest"], current_source_revision=change["after_revision"])
        assert published["status"] == "published"
        assert published["remote"]["url"] == "https://github.com/example/project/pull/42"
        assert len(remote.posts) == 4
        assert all(entry["state"] == "succeeded" for entry in published["journal"])
        assert remote.posts[0][2]["tree"] == [{"path": "app.py", "type": "blob", "mode": "100644", "content": "new\n"}]
        with pytest.raises(CodingConflict):
            await delivery.publish(CORP, prepared, expected_digest=prepared["digest"], current_source_revision=change["after_revision"])
        assert len(remote.posts) == 4
        assert TOKEN not in json.dumps(store.delivery(CORP, prepared["id"]))
    finally:
        await connector.close()
        store.close()


@pytest.mark.parametrize("drift", ["digest", "source", "remote", "dirty", "identity"])
async def test_publication_drift_prevents_remote_mutations(settings, drift):
    changes, change = frozen(settings)
    store = ledger(settings)
    remote = Remote({"app.py": b"old\n"})
    connector = GitHubConnector(CORP, TOKEN, "example", "project", transport=httpx.MockTransport(remote))
    delivery = GitHubDelivery(connector, store.record_delivery, changes.blob)
    try:
        prepared = await delivery.prepare(CORP, SESSION, change, {}, "Fix app")
        if drift == "remote": remote.base = "e" * 40
        if drift == "dirty": remote.dirty = True
        if drift == "identity": remote.repository_id = 99
        with pytest.raises(CodingConflict):
            await delivery.publish(CORP, prepared,
                expected_digest="0" * 64 if drift == "digest" else prepared["digest"],
                current_source_revision="0" * 64 if drift == "source" else change["after_revision"])
        assert not remote.posts
    finally:
        await connector.close()
        store.close()


async def test_transport_uncertainty_is_durable_and_not_replayed(settings):
    changes, change = frozen(settings)
    store = ledger(settings)
    remote = Remote({"app.py": b"old\n"})
    connector = GitHubConnector(CORP, TOKEN, "example", "project", transport=httpx.MockTransport(remote))
    delivery = GitHubDelivery(connector, store.record_delivery, changes.blob)
    try:
        prepared = await delivery.prepare(CORP, SESSION, change, {}, "Fix app")
        remote.fail = "/git/trees"
        with pytest.raises(GitHubError):
            await delivery.publish(CORP, prepared, expected_digest=prepared["digest"], current_source_revision=change["after_revision"])
        record = store.delivery(CORP, prepared["id"])
        assert record["status"] == "uncertain"
        assert record["journal"][0]["state"] == "uncertain"
        with pytest.raises(CodingConflict):
            await delivery.publish(CORP, record, expected_digest=record["digest"], current_source_revision=change["after_revision"])
        assert len(remote.posts) == 1
    finally:
        await connector.close()
        store.close()


async def test_restart_preserves_uncertain_journal(settings):
    changes, change = frozen(settings)
    store = ledger(settings)
    connector = GitHubConnector(CORP, TOKEN, "example", "project", transport=httpx.MockTransport(Remote({"app.py": b"old\n"})))
    try:
        delivery = GitHubDelivery(connector, store.record_delivery, changes.blob)
        record = await delivery.prepare(CORP, SESSION, change, {}, "Fix")
        record.update(status="publishing")
        store.record_delivery(CORP, record, "claim")
        record["journal"].append({"action": "create_tree", "state": "sending"})
        store.record_delivery(CORP, record, "progress")
        store.close()
        store = CodingStore(settings.coding_db)
        recovered = store.delivery(CORP, record["id"])
        assert recovered["status"] == "uncertain"
        assert recovered["journal"] == record["journal"]
    finally:
        await connector.close()
        store.close()


async def test_read_only_connector_scope_bounds_and_redaction():
    remote = Remote({})
    connector = GitHubConnector(CORP, TOKEN, "example", "project", transport=httpx.MockTransport(remote))
    try:
        assert "[redacted]" in (await connector.issue(CORP, 7))["body"]
        for operation in [lambda: connector.issue("OTHER_CORP", 7), lambda: connector.issues(CORP, page=4), lambda: connector.issue(CORP, True)]:
            with pytest.raises((KeyError, ValueError)):
                await operation()
        assert not remote.posts
    finally:
        await connector.close()


def test_api_connect_task_prepare_and_explicit_publish(settings):
    settings = replace(settings, github_tokens={CORP: SecretStr(TOKEN)})
    root = fixture_project(settings)
    remote = Remote({"increment.py": (root / "increment.py").read_bytes()})
    model = ScriptedModel(responses=[
        tool_call("github_issue", {"number": 7}, "issue"),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "edit"),
        tool_call("run_check", {"name": "tests"}, "check"), AIMessage(content="Fixed issue 7")])
    app = create_app(settings=settings, graph_override=FakeGraph(), coding_model=model, coding_runtime_factory=FixtureRuntime)
    with TestClient(app) as client:
        app.state.coding.github.connector_factory = lambda corp, token, owner, repo: GitHubConnector(corp, token, owner, repo, transport=httpx.MockTransport(remote))
        session = open_session(client, root)
        assert client.post(f"/projects/{session['project_id']}/github", json={"owner": "example", "repository": "project"}).status_code == 200
        task = client.post(f"/sessions/{session['id']}/tasks", json={"mode": "implement", "message": "Fix issue 7"}).json()
        completed = wait_for_attempt(client, task["id"])
        assert completed["outcome"] == "verified", completed
        prepared = client.post(f"/changes/{completed['change_id']}/deliveries", json={"title": "Fix increment"})
        assert prepared.status_code == 201, prepared.text
        record = prepared.json()
        assert not remote.posts
        foreign = {"X-Corp-ID": "OTHER_CORP"}
        assert client.get(f"/deliveries/{record['id']}", headers=foreign).status_code == 404
        assert client.post(f"/deliveries/{record['id']}/publish", headers=foreign, json={"expected_digest": record["digest"]}).status_code == 404
        response = client.post(f"/deliveries/{record['id']}/publish", json={"expected_digest": record["digest"]})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "published"
        assert len(remote.posts) == 4
        assert "value + 1" in (root / "increment.py").read_text()
        assert TOKEN not in json.dumps(client.get(f"/coding/runs/{task['id']}").json())
