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


def test_retry_rejects_previous_attempt_with_active_worker(test_settings):
    services = Services(settings=test_settings, agent=Graph([]))
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Question")
    with TestClient(create_app(services)) as client:
        services.runs.fail(run, "Timed out")
        with services.runs.worker(run):
            response = client.post(f"/api/runs/{run}/resume")
            assert response.status_code == 409
            assert "still stopping" in response.json()["detail"]
        assert services.runs.get(run).status == RunStatus.FAILED
        assert not services.conversations.get(thread).active_run_id


def test_resume_after_publication_finishes_report_without_restarting_analysis(
    test_settings,
):
    from data_analytics_agent.presentation import resolve_answer

    graph = Graph([])
    services = Services(settings=test_settings, agent=graph)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Count artists")
    result = services.results.save(
        columns=["count"], rows=[{"count": 0}], thread_id=thread, source_id="test"
    )
    services.runs.publish(
        run,
        resolve_answer(
            CoordinatorResponse(answer="Zero", primary_result_id=result.result_id),
            thread_id=thread,
            source_id="test",
            results=services.results,
            analyses=services.analyses,
            runs=services.runs,
        ),
    )
    services.runs.save_report_spec(
        run,
        {
            "title": "Artist count",
            "blocks": [
                {"type": "table", "title": "Count", "result_id": result.result_id}
            ],
        },
    )
    with TestClient(create_app(services)) as client:
        services.runs.fail(run, "Report failed")
        assert client.post(f"/api/runs/{run}/resume").status_code == 202
        state = client.get(f"/api/runs/{run}").json()
        assert state["status"] == "completed" and not state["error"]
        assert state["answer"]["report"]
        assert client.post(f"/api/runs/{run}/retry-report").status_code == 409
        assert len(services.conversations.get(thread).turns) == 1
        assert not graph.inputs
