from __future__ import annotations

import time

from fastapi.testclient import TestClient

from general_agent.api import create_app
from tests.fakes import FakeGraph


def test_api_persists_chat_and_enforces_single_active_run(settings) -> None:
    graph = FakeGraph(blocked=True)
    app = create_app(settings=settings, graph_override=graph)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["trusted_host_execution"] is False
        assert "workspace" not in health.json()

        first = client.post("/conversations", json={"title": "First"}).json()
        second = client.post("/conversations", json={"title": "Second"}).json()
        response = client.post(
            f"/conversations/{first['conversation_id']}/messages",
            data={"text": "work"},
            files=[("files", ("advisors.csv", b"FIRST_NAME,LAST_NAME\nAvery,Stone\n", "text/csv"))],
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
        assert conversation["turns"][0]["attachments"][0]["original_name"] == "advisors.csv"


def test_chat_rejects_non_advisor_and_multiple_attachments(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={}).json()["conversation_id"]
        non_sheet = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"text": "match this"},
            files=[("files", ("notes.txt", b"not advisors", "text/plain"))],
        )
        assert non_sheet.status_code == 400
        multiple = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"text": "match these"},
            files=[
                ("files", ("one.csv", b"Name\nOne\n", "text/csv")),
                ("files", ("two.xlsx", b"not needed", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ],
        )
        assert multiple.status_code == 400


def test_api_corp_header_isolates_chats_and_attachments(settings) -> None:
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
        sent = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            data={"text": "match"},
            files=[("files", ("private.csv", b"Name\nAlice\n", "text/csv"))],
            headers=alice,
        )
        assert sent.status_code == 200
        for _ in range(100):
            current = client.get(
                f"/conversations/{conversation['conversation_id']}", headers=alice
            ).json()
            if current["turns"][0]["status"] != "running":
                break
            time.sleep(0.01)
        attachment_id = current["turns"][0]["attachments"][0]["attachment_id"]
        assert client.get(
            f"/attachments/{attachment_id}/download", headers=bob
        ).status_code == 404
        assert client.get(
            f"/attachments/{attachment_id}/download", headers=alice
        ).content == b"Name\nAlice\n"


def test_generic_workspace_routes_are_not_exposed(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        assert client.get("/workspace").status_code == 404
        assert client.post("/workspace/uploads").status_code == 404
        assert client.get("/workspace/inspect").status_code == 404
