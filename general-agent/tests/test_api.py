from __future__ import annotations

import time

from fastapi.testclient import TestClient

from general_agent.api import create_app
from general_agent.workspace import Workspace
from tests.fakes import FakeGraph


def test_api_persists_chat_and_enforces_single_active_run(settings) -> None:
    graph = FakeGraph(blocked=True)
    app = create_app(settings=settings, graph_override=graph)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["trusted_host_execution"] is True
        assert health.json()["max_upload_files"] == settings.max_upload_files

        first = client.post("/conversations", json={"title": "First"}).json()
        second = client.post("/conversations", json={"title": "Second"}).json()
        response = client.post(
            f"/conversations/{first['conversation_id']}/messages",
            data={"text": "work"},
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        collision = client.post(
            f"/conversations/{second['conversation_id']}/messages",
            data={"text": "also work"},
        )
        assert collision.status_code == 409
        stopped = client.post(f"/runs/{run_id}/stop")
        assert stopped.status_code == 200
        for _ in range(100):
            run = client.get(f"/runs/{run_id}").json()
            if run["status"] == "stopped":
                break
            time.sleep(0.01)
        assert run["status"] == "stopped"
        conversation = client.get(f"/conversations/{first['conversation_id']}").json()
        assert conversation["turns"][0]["attachments"][0]["original_name"] == "notes.txt"


def test_api_rejects_absolute_traversal_protected_and_escaping_symlinks(settings, tmp_path) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    workspace = Workspace(settings.workspace_root, settings.data_root)
    (workspace.shared_root("A123456") / "escape").symlink_to(outside)
    with TestClient(app) as client:
        for unsafe in (
            "/etc/passwd",
            "../outside.txt",
            ".packages/hidden",
            "shared/escape",
        ):
            response = client.get("/workspace/download", params={"path": unsafe})
            assert response.status_code == 400


def test_api_corp_header_isolates_chats_and_workspace(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    alice = {"X-Corp-ID": "A123456"}
    bob = {"X-Corp-ID": "B654321"}
    with TestClient(app) as client:
        conversation = client.post(
            "/conversations", json={"title": "Alice"}, headers=alice
        ).json()
        assert client.get(
            f"/conversations/{conversation['conversation_id']}", headers=bob
        ).status_code == 404
        uploaded = client.post(
            "/workspace/uploads",
            files=[("files", ("private.txt", b"alice", "text/plain"))],
            headers=alice,
        ).json()[0]
        assert client.get(
            "/workspace/download", params={"path": uploaded["path"]}, headers=bob
        ).status_code == 404
        assert client.get("/workspace", headers=bob).json() == []


def test_upload_inspect_and_download_workspace(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        upload = client.post(
            "/workspace/uploads",
            files=[("files", ("sample.csv", b"name,value\na,1\n", "text/csv"))],
        )
        assert upload.status_code == 200
        path = upload.json()[0]["path"]
        preview = client.get("/workspace/inspect", params={"path": path})
        assert preview.status_code == 200
        assert preview.json()["rows"][0]["name"] == "a"
        download = client.get("/workspace/download", params={"path": path})
        assert download.content == b"name,value\na,1\n"


def test_chat_workspace_upload_promote_and_cleanup(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        conversation = client.post("/conversations", json={}).json()
        conversation_id = conversation["conversation_id"]
        upload = client.post(
            "/workspace/uploads",
            params={"scope": "chat", "conversation_id": conversation_id},
            files=[("files", ("brief.txt", b"brief", "text/plain"))],
        )
        assert upload.status_code == 200
        entry = upload.json()[0]
        assert entry["scope"] == "chat"
        assert entry["origin"] == "upload"

        listed = client.get(
            "/workspace",
            params={"scope": "chat", "conversation_id": conversation_id},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["name"] == "uploads"

        promoted = client.post(
            "/workspace/promote",
            params={"path": entry["path"], "conversation_id": conversation_id},
        )
        assert promoted.status_code == 200
        assert promoted.json()["path"] == "shared/brief.txt"

        cleanup = client.delete(f"/workspace/chats/{conversation_id}")
        assert cleanup.status_code == 204
        shared = client.get("/workspace", params={"scope": "shared"}).json()
        assert any(item["name"] == "brief.txt" for item in shared)
