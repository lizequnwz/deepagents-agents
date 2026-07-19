from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from text2sql_agent.api import Services, create_app
from text2sql_agent.config import Settings
from text2sql_agent.schemas import FinalAnswer


class FakeStream:
    def __init__(
        self,
        *,
        approval_sql: str | None = None,
        answer: FinalAnswer | None = None,
    ) -> None:
        self.approval_sql = approval_sql
        self.answer = answer

    async def __aiter__(self):
        yield {
            "method": "tools",
            "params": {
                "namespace": [],
                "data": {
                    "event": "tool-started",
                    "tool_name": "read_file",
                    "input": {
                        "file_path": "/project/semantic/chinook.osi.yaml"
                    },
                },
            },
        }

    async def interrupted(self) -> bool:
        return self.approval_sql is not None

    async def interrupts(self) -> list[dict[str, Any]]:
        if self.approval_sql is None:
            return []
        return [
            {
                "action_requests": [
                    {
                        "name": "execute_sql",
                        "args": {"query": self.approval_sql},
                        "description": "Review SQL",
                    }
                ],
                "review_configs": [
                    {
                        "allowed_decisions": [
                            "approve",
                            "edit",
                            "reject",
                        ]
                    }
                ],
            }
        ]

    async def output(self) -> dict[str, Any] | None:
        if self.answer is None:
            return None
        return {"structured_response": self.answer}


class FakeAgent:
    def __init__(self, streams: list[FakeStream]) -> None:
        self.streams = deque(streams)
        self.inputs: list[Any] = []

    async def astream_events(self, agent_input: Any, **_kwargs: Any):
        assert "transformers" not in _kwargs
        self.inputs.append(agent_input)
        return self.streams.popleft()


def test_api_approval_rejection_reapproval_and_rehydration(
    test_settings: Settings,
) -> None:
    final_stream = FakeStream()
    fake = FakeAgent(
        [
            FakeStream(approval_sql="SELECT Name FROM Artist LIMIT 5"),
            FakeStream(
                approval_sql=(
                    "SELECT Name FROM Artist ORDER BY Name LIMIT 5"
                )
            ),
            final_stream,
        ]
    )
    services = Services(
        settings=test_settings,
        agent=fake,
    )
    client = TestClient(create_app(services))

    sources = client.get("/api/data-sources").json()
    assert sources["default_source_id"] == "test"
    assert all(source["ready"] for source in sources["sources"])
    created_conversation = client.post(
        "/api/conversations",
        json={"source_id": "test"},
    ).json()
    thread_id = created_conversation["thread_id"]
    assert created_conversation["source_id"] == "test"
    executed_sql = "SELECT Name FROM Artist ORDER BY Name LIMIT 5"
    saved = services.results.save(
        thread_id=thread_id,
        source_id="test",
        executed_sql=executed_sql,
        columns=["Name"],
        rows=[{"Name": "AC/DC"}],
        truncated=False,
        elapsed_ms=1.0,
    )
    final_stream.answer = FinalAnswer(
        answer="Five artists were returned.",
        sql="SELECT stale_model_sql",
        result_id=saved.result_id,
        assumptions=["Artist names use catalog spelling."],
        interpretation="The rows are alphabetically ordered.",
    )
    created = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "List five artists"},
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    first = client.get(f"/api/runs/{run_id}").json()
    assert first["status"] == "approval_required"
    assert "Args:" not in first["approval"]["description"]
    assert first["approval"]["description"].startswith(
        "Review the generated SQL"
    )
    assert any(
        event["label"] == "Inspecting the OSI semantic model"
        for event in first["events"]
    )

    rejected = client.post(
        f"/api/runs/{run_id}/decisions",
        json={
            "decisions": [
                {
                    "action": "reject",
                    "feedback": "Sort the result alphabetically.",
                }
            ]
        },
    )
    assert rejected.status_code == 202
    second = client.get(f"/api/runs/{run_id}").json()
    assert second["status"] == "approval_required"
    assert "ORDER BY Name" in second["approval"]["query"]
    assert any(
        event["label"] == "Applying feedback and revising SQL"
        for event in second["events"]
    )

    approved = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"decisions": [{"action": "approve"}]},
    )
    assert approved.status_code == 202
    completed = client.get(f"/api/runs/{run_id}").json()
    assert completed["status"] == "completed"

    conversation = client.get(
        f"/api/conversations/{thread_id}"
    ).json()
    assert conversation["source_id"] == "test"
    assert conversation["active_run_id"] is None
    assert len(conversation["turns"]) == 1
    assert conversation["turns"][0]["answer"]["answer"].startswith("Five")
    assert conversation["turns"][0]["answer"]["sql"] == executed_sql


def test_concurrent_run_is_rejected(test_settings: Settings) -> None:
    fake = FakeAgent(
        [FakeStream(approval_sql="SELECT 1")]
    )
    services = Services(
        settings=test_settings,
        agent=fake,
    )
    client = TestClient(create_app(services))
    thread_id = client.post("/api/conversations").json()["thread_id"]
    first = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "One"},
    )
    assert first.status_code == 202
    second = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "Two"},
    )
    assert second.status_code == 409


def test_conversations_are_permanently_bound_to_selected_source(
    test_settings: Settings,
) -> None:
    services = Services(settings=test_settings, agent=FakeAgent([]))
    client = TestClient(create_app(services))

    first = client.post(
        "/api/conversations",
        json={"source_id": "test"},
    )
    second = client.post(
        "/api/conversations",
        json={"source_id": "test_alt"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["thread_id"] != second.json()["thread_id"]
    assert first.json()["source_id"] == "test"
    assert second.json()["source_id"] == "test_alt"
    assert (
        client.get(
            f"/api/conversations/{first.json()['thread_id']}"
        ).json()["source_id"]
        == "test"
    )

    unknown = client.post(
        "/api/conversations",
        json={"source_id": "missing"},
    )
    assert unknown.status_code == 422
