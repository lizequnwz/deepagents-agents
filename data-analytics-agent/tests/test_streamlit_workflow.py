"""Streamlit's supported UI harness verifies stable navigation and run controls."""

from pathlib import Path
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.ui.api_client import AgentAPIClient, APIError
from data_analytics_agent.schemas import CoordinatorResponse
from tests.test_run_manager import Graph, Stream


def test_saved_navigation_resume_and_stable_controls(test_settings, monkeypatch):
    services = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Resumed local test."))]),
    )
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Saved investigation")
    services.conversations.begin_run(thread, run)
    services.runs.pause(run)
    services.conversations.fail_run(thread, run)
    with TestClient(create_app(services)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(
            str(Path(__file__).parents[1] / "streamlit_app.py")
        ).run(timeout=15)
        assert not app.exception
        next(b for b in app.button if b.label == "Saved investigation").click().run(
            timeout=15
        )
        assert not app.exception
        assert any("Paused" in m.value for m in app.markdown)
        assert next(b for b in app.button if b.label == "Resume").key == f"resume_{run}"
        app.run(timeout=15)
        assert not app.exception
        assert next(b for b in app.button if b.label == "Resume").key == f"resume_{run}"
        next(b for b in app.button if b.label == "Resume").click().run(timeout=15)
        assert not app.exception
        app.run(timeout=15)
        assert any("Resumed local test." in m.value for m in app.markdown)
        assert services.runs.get(run).status == "completed"


def test_history_confirmation_cancel_delete_and_clear_all(test_settings, monkeypatch):
    services = Services(settings=test_settings)
    saved = services.conversations.create("test")
    with TestClient(create_app(services)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = saved
        app.run(timeout=15)
        assert not app.exception
        next(b for b in app.button if b.label == "Delete history").click().run()
        assert services.conversations.exists(saved)
        assert any("cannot be undone" in w.value for w in app.warning)
        next(b for b in app.button if b.label == "Cancel").click().run()
        assert services.conversations.exists(saved)
        assert not any(b.label == "Confirm deletion" for b in app.button)
        next(b for b in app.button if b.label == "Delete history").click().run()
        next(b for b in app.button if b.label == "Confirm deletion").click().run(
            timeout=15
        )
        assert not app.exception
        assert not services.conversations.exists(saved)
        assert len(services.conversations.list()) == 1  # New empty conversation.
        another = services.conversations.create("test")
        next(b for b in app.button if b.label == "Delete history").click().run()
        next(r for r in app.radio if r.label == "Delete which history?").set_value(
            "All conversations"
        ).run()
        assert services.conversations.exists(another)
        next(b for b in app.button if b.label == "Confirm deletion").click().run(
            timeout=15
        )
        assert not app.exception
        assert not services.conversations.exists(another)
        remaining = services.conversations.list()
        assert (
            len(remaining) == 1 and not remaining[0].turns and not remaining[0].run_ids
        )
