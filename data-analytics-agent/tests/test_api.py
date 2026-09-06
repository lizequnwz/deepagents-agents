from fastapi.testclient import TestClient
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.schemas import (
    API_CONTRACT_VERSION,
    CoordinatorResponse,
    RunStatus,
)
from tests.test_run_manager import Graph, Stream


def test_saved_navigation_health_and_greeting(test_settings):
    services = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Hello"))]),
    )
    with TestClient(create_app(services)) as client:
        assert (
            client.get("/health").json()["api_contract_version"] == API_CONTRACT_VERSION
        )
        conversation = client.post(
            "/api/conversations", json={"source_id": "test"}
        ).json()
        thread = conversation["thread_id"]
        response = client.post(
            f"/api/conversations/{thread}/messages", json={"message": "Hello"}
        )
        assert response.status_code == 202, response.text
        run = client.get("/api/runs/" + response.json()["run_id"]).json()
        assert run["status"] == "completed" and run["answer"]["answer"] == "Hello"
        assert client.get("/api/conversations").json()[0]["thread_id"] == thread
    reopened = Services(settings=test_settings)
    assert reopened.conversations.get(thread).turns[0].answer.answer == "Hello"


def test_restart_paused_run_requires_explicit_resume(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Continue")
    services.conversations.begin_run(thread, run)
    services.runs.start_active(run)
    reopened = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Resumed"))]),
    )
    assert reopened.runs.get(run).status == RunStatus.PAUSED
    assert not reopened.conversations.get(thread).active_run_id
    with TestClient(create_app(reopened)) as client:
        assert client.post(f"/api/runs/{run}/resume").status_code == 202
        assert reopened.runs.get(run).status == RunStatus.COMPLETED


def test_source_scope_and_one_active_run(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Working")
    services.conversations.begin_run(thread, run)
    with TestClient(create_app(services)) as client:
        response = client.post(
            f"/api/conversations/{thread}/messages", json={"message": "Second"}
        )
        assert response.status_code == 409
        assert client.post(
            "/api/conversations", json={"source_id": "unknown"}
        ).status_code in (404, 422)
        assert client.get("/api/results/unknown").status_code == 404
