from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    VisualizationResult,
)
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.config import Settings
from data_analytics_agent.schemas import FinalAnswer


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
        self.configs: list[dict[str, Any]] = []

    async def astream_events(self, agent_input: Any, **_kwargs: Any):
        assert "transformers" not in _kwargs
        self.inputs.append(agent_input)
        self.configs.append(_kwargs["config"])
        return self.streams.popleft()


class FakeAutoChartStream(FakeStream):
    def __init__(
        self,
        *,
        chart_spec: ChartSpec,
    ) -> None:
        super().__init__(
            answer=FinalAnswer(
                answer="Coordinator chart response.",
                result_id=chart_spec.result_id,
            )
        )
        self.chart_spec = chart_spec

    async def __aiter__(self):
        yield {
            "method": "tools",
            "params": {
                "namespace": [],
                "data": {
                    "event": "tool-started",
                    "tool_name": "create_chart",
                    "input": {
                        "spec": self.chart_spec.model_dump(mode="json")
                    },
                },
            },
        }

    async def output(self) -> dict[str, Any]:
        result = VisualizationResult(
            answer=(
                "Chart generated successfully: "
                f"{self.chart_spec.chart_type.value} chart "
                f"{self.chart_spec.title!r}."
            ),
            chart=self.chart_spec,
        )
        return {
            "structured_response": self.answer,
            "messages": [
                {"type": "human", "content": "Chart the result"},
                {"type": "tool", "content": result.model_dump_json()},
            ],
        }


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


def test_health_reports_visualization_feature_state(
    test_settings: Settings,
) -> None:
    services = Services(settings=test_settings, agent=FakeAgent([]))
    health = TestClient(create_app(services)).get("/health")

    assert health.status_code == 200
    assert health.json()["visualization_enabled"] is True


def test_api_chart_generation_is_automatic_and_completes_conversation(
    test_settings: Settings,
) -> None:
    fake = FakeAgent([])
    services = Services(settings=test_settings, agent=fake)
    client = TestClient(create_app(services))
    thread_id = client.post("/api/conversations").json()["thread_id"]
    saved = services.results.save(
        thread_id=thread_id,
        source_id="test",
        executed_sql="SELECT Name, ArtistId FROM Artist",
        columns=["Name", "ArtistId"],
        rows=[{"Name": "AC/DC", "ArtistId": 1}],
        truncated=False,
        elapsed_ms=1,
    )
    spec = ChartSpec(
        result_id=saved.result_id,
        chart_type="bar",
        title="Artist IDs",
        x="Name",
        y=["ArtistId"],
    )
    fake.streams.append(FakeAutoChartStream(chart_spec=spec))

    created = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "Chart the saved artists"},
    )
    run_id = created.json()["run_id"]
    assert len(fake.inputs) == 1
    assert fake.configs[0]["configurable"]["thread_id"] == run_id
    completed = client.get(f"/api/runs/{run_id}").json()
    assert completed["status"] == "completed"
    assert completed["approval"] is None
    assert completed["answer"]["chart"] == spec.model_dump(mode="json")
    assert completed["answer"]["answer"] == (
        "Chart generated successfully: bar chart 'Artist IDs'."
    )
    assert any(
        event["label"] == "Generating bar chart · x=Name · y=ArtistId"
        for event in completed["events"]
    )
    assert all(
        saved.result_id not in event["label"]
        for event in completed["events"]
    )
    turn = client.get(f"/api/conversations/{thread_id}").json()["turns"][0]
    assert turn["answer"]["chart"] == spec.model_dump(mode="json")
    assert turn["answer"]["answer"] == completed["answer"]["answer"]
    assert turn["answer"]["result_id"] == saved.result_id
    assert turn["answer"]["sql"] == saved.executed_sql
    decision = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"decisions": [{"action": "approve"}]},
    )
    assert decision.status_code == 409
    assert len(fake.inputs) == 1


def test_followup_after_automatic_chart_uses_complete_history(
    test_settings: Settings,
) -> None:
    fake = FakeAgent([])
    services = Services(settings=test_settings, agent=fake)
    client = TestClient(create_app(services))
    thread_id = client.post("/api/conversations").json()["thread_id"]
    saved = services.results.save(
        thread_id=thread_id,
        source_id="test",
        executed_sql="SELECT category, amount FROM metrics",
        columns=["category", "amount"],
        rows=[{"category": "A", "amount": 10}],
        truncated=False,
        elapsed_ms=1,
    )
    spec = ChartSpec(
        result_id=saved.result_id,
        chart_type="bar",
        title="Amount",
        x="category",
        y=["amount"],
    )
    fake.streams.append(FakeAutoChartStream(chart_spec=spec))
    first_run_id = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "Chart the metrics"},
    ).json()["run_id"]
    fake.streams.append(
        FakeStream(answer=FinalAnswer(answer="Follow-up complete."))
    )
    second_run_id = client.post(
        f"/api/conversations/{thread_id}/messages",
        json={"message": "Explain what the chart represents"},
    ).json()["run_id"]

    assert first_run_id != second_run_id
    assert fake.configs[0]["configurable"]["thread_id"] == first_run_id
    assert fake.configs[1]["configurable"]["thread_id"] == second_run_id
    messages = fake.inputs[1]["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert messages[0]["content"] == "Chart the metrics"
    assert saved.result_id in messages[1]["content"]
    assert messages[2]["content"] == "Explain what the chart represents"
    conversation = client.get(
        f"/api/conversations/{thread_id}"
    ).json()
    assert len(conversation["turns"]) == 2
    assert conversation["turns"][1]["answer"]["answer"] == (
        "Follow-up complete."
    )
