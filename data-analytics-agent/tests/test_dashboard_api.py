"""Dashboard HTTP behavior preserves report completion and conversation scope."""

from fastapi.testclient import TestClient

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.dashboard.schemas import DashboardAction
from data_analytics_agent.handoff import ReportCompletionMiddleware
from data_analytics_agent.schemas import CoordinatorResponse
from tests.test_presentation_edits import presented as presented
from tests.test_run_manager import Graph, Stream


def services_for(w, settings, *, agent=None):
    return Services(
        settings=settings,
        storage=w.storage,
        results=w.results,
        runs=w.runs,
        conversations=w.conversations,
        analyses=w.analyses,
        reports=w.reports,
        agent=agent,
    )


def test_dashboard_create_scope_and_idempotent_stale_view_edits(
    presented, test_settings
):
    w = presented
    services = services_for(w, test_settings)
    prefix = f"/api/conversations/{w.thread}/dashboards"
    with TestClient(create_app(services)) as client:
        created = client.post(
            prefix, json={"run_id": w.run, "request_id": "save-dashboard"}
        )
        assert created.status_code == 201, created.text
        revision = created.json()["revision"]
        dashboard_id = revision["dashboard_id"]
        assert revision["report_id"] == w.report.report_id
        repeated = client.post(
            prefix, json={"run_id": w.run, "request_id": "save-dashboard"}
        )
        assert repeated.json()["revision"]["dashboard_id"] == dashboard_id
        update = {
            "expected_revision": revision["revision_id"],
            "request_id": "rename-dashboard",
            "title": "Saved monthly sales",
        }
        saved = client.post(f"{prefix}/{dashboard_id}/view", json=update)
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"]["version"] == 2
        retry = client.post(f"{prefix}/{dashboard_id}/view", json=update)
        assert retry.status_code == 200
        assert retry.json()["revision"]["version"] == 2
        stale = client.post(
            f"{prefix}/{dashboard_id}/view",
            json={**update, "request_id": "stale-edit", "title": "Wrong revision"},
        )
        assert stale.status_code == 409
        other = services.conversations.create("test")
        assert (
            client.get(
                f"/api/conversations/{other}/dashboards/{dashboard_id}"
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/conversations/{other}/dashboards",
                json={"run_id": w.run},
            ).status_code
            == 404
        )
        assert len(client.get(prefix).json()["dashboards"]) == 1
        assert client.delete(f"/api/conversations/{w.thread}").status_code == 200
        assert not services.storage.load("dashboard_heads", dict)
        assert not services.storage.load("dashboard_candidates", dict)


def test_failed_refresh_preserves_dashboard_and_retry_returns_original_run(
    presented, test_settings
):
    w = presented
    graph = Graph(
        [Stream(CoordinatorResponse(answer="Unable to complete the refresh."))]
    )
    services = services_for(w, test_settings, agent=graph)
    prefix = f"/api/conversations/{w.thread}/dashboards"
    with TestClient(create_app(services)) as client:
        original = client.post(prefix, json={"run_id": w.run}).json()["revision"]
        endpoint = f"{prefix}/{original['dashboard_id']}"
        action = {
            "expected_revision": original["revision_id"],
            "request_id": "refresh-once",
            "action": "refresh",
        }
        started = client.post(endpoint + "/actions", json=action)
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "failed"
        assert run["question"] == "Refresh dashboard data"
        assert "dashboard_spec" not in run["question"]
        view = client.get(endpoint).json()
        assert view["revision"]["revision_id"] == original["revision_id"]
        assert view["pending_action"]["status"] == "failed"
        duplicate = client.post(endpoint + "/actions", json=action)
        assert duplicate.status_code == 202
        assert duplicate.json()["run_id"] == run_id
        assert len(graph.inputs) == 1
        brief = graph.inputs[0]["messages"][-1]["content"]
        assert "dashboard_spec" in brief and "chart display samples" in brief


def test_requested_dashboard_prevents_early_report_completion(presented, test_settings):
    w = presented
    services = services_for(w, test_settings)
    services.storage.put(
        "dashboard_requests", w.run, {"run_id": w.run, "thread_id": w.thread}
    )
    middleware = ReportCompletionMiddleware(services.runs, services.dashboards)
    response = middleware.before_model({"run_id": w.run}, None)
    assert "jump_to" not in response
    assert "create_dashboard" in response["messages"][0].content


def test_dashboard_follow_up_uses_displayed_revision_and_rejects_stale_or_foreign_context(
    presented, test_settings
):
    w = presented
    graph = Graph([Stream(CoordinatorResponse(answer="The saved scope is available."))])
    services = services_for(w, test_settings, agent=graph)
    prefix = f"/api/conversations/{w.thread}/dashboards"
    with TestClient(create_app(services)) as client:
        original = client.post(prefix, json={"run_id": w.run}).json()["revision"]
        current = client.post(
            f"{prefix}/{original['dashboard_id']}/view",
            json={
                "expected_revision": original["revision_id"],
                "request_id": "rename-before-follow-up",
                "title": "Displayed monthly revenue",
            },
        ).json()["revision"]
        question = {
            "message": "Explain the scope of this view.",
            "dashboard_id": current["dashboard_id"],
            "dashboard_revision": current["revision_id"],
        }
        before = services.conversations.get(w.thread).run_ids
        stale = client.post(
            f"/api/conversations/{w.thread}/messages",
            json={**question, "dashboard_revision": original["revision_id"]},
        )
        assert stale.status_code == 409, stale.text
        assert "displayed dashboard changed" in stale.json()["detail"]
        for missing in ("dashboard_id", "dashboard_revision"):
            incomplete = {
                key: value for key, value in question.items() if key != missing
            }
            rejected = client.post(
                f"/api/conversations/{w.thread}/messages", json=incomplete
            )
            assert rejected.status_code == 422, rejected.text
        foreign = services.conversations.create("test")
        foreign_source = services.conversations.create("test_alt")
        for thread in (foreign, foreign_source):
            rejected = client.post(
                f"/api/conversations/{thread}/messages", json=question
            )
            assert rejected.status_code == 404, rejected.text
            assert not services.conversations.get(thread).run_ids
        assert services.conversations.get(w.thread).run_ids == before
        assert not graph.inputs

        accepted = client.post(f"/api/conversations/{w.thread}/messages", json=question)
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run_id"]
        context = services.storage.get("workspace_run_context", run_id, dict)
        assert context == {
            "run_id": run_id,
            "thread_id": w.thread,
            "source_id": "test",
            "context": {
                "dashboard_id": current["dashboard_id"],
                "revision_id": current["revision_id"],
                "original_question": current["question"],
                "spec": current["spec"],
                "applied_filters": current["applied_filters"],
            },
        }
        assert "Displayed monthly revenue" in graph.inputs[0]["messages"][-1]["content"]
        assert (
            "ordinary follow-up creates a new answer"
            in graph.inputs[0]["messages"][-1]["content"]
        )
        assert not services.storage.get("dashboard_requests", run_id, dict)
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "completed"
        assert (
            client.get(f"{prefix}/{current['dashboard_id']}").json()["revision"]
            == current
        )


def test_active_dashboard_action_prose_queues_follow_up_without_changing_typed_action(
    presented, test_settings
):
    w = presented
    services = services_for(w, test_settings)
    prefix = f"/api/conversations/{w.thread}/dashboards"
    with TestClient(create_app(services)) as client:
        revision = client.post(prefix, json={"run_id": w.run}).json()["revision"]
        action = services.dashboards.begin_action(
            revision["dashboard_id"],
            w.thread,
            source_id="test",
            action=DashboardAction(
                action="refresh",
                expected_revision=revision["revision_id"],
                request_id="active-refresh",
            ),
        )
        action_run = services.runs.create(w.thread, "test", "Refresh dashboard data")
        services.dashboards.attach_action_run(action.action_id, action_run)
        services.conversations.begin_run(w.thread, action_run)
        services.runs.start_active(action_run)
        original_action = services.dashboards.action_for_run(action_run)

        response = client.post(
            f"/api/runs/{action_run}/corrections",
            json={"message": "Also explain which period the dashboard covers."},
        )
        assert response.status_code == 202, response.text
        receipt = response.json()
        follow_up = receipt["run_id"]
        assert receipt["disposition"] == "follow_up"
        assert "keeps its declared filters" in receipt["message"]
        assert follow_up != action_run
        assert services.runs.get(action_run).corrections == []
        assert services.dashboards.action_for_run(action_run) == original_action
        assert services.runs.follow_ups(action_run) == [follow_up]
        assert services.conversations.get(w.thread).active_run_id == action_run
        assert services.conversations.get(w.thread).run_ids[-1] == follow_up
        assert services.runs.get(follow_up).question == (
            "Also explain which period the dashboard covers."
        )
        assert services.storage.get("workspace_run_context", follow_up, dict) == {
            "run_id": follow_up,
            "thread_id": w.thread,
            "source_id": "test",
            "dashboard_id": revision["dashboard_id"],
        }
