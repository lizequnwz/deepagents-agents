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


def test_one_turn_preserves_activity_identity_through_publication(
    test_settings, monkeypatch
):
    from data_analytics_agent.schemas import FinalAnswer, ActivityTool

    services = Services(settings=test_settings, agent=Graph([]))
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Synthetic question before activity")
    services.conversations.begin_run(thread, run)
    services.runs.start_active(run)
    services.runs.add_event(
        run,
        "tool",
        "Count artists",
        phase="completed",
        agent="text-to-sql",
        tool=ActivityTool(
            call_id="step",
            name="execute_sql",
            input={"purpose": "Count artists"},
            output={"row_count": 1},
        ),
    )
    with TestClient(create_app(services)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        assert not app.exception and len(app.chat_input) == 1
        assert [m.name for m in app.chat_message] == ["user", "assistant"]
        activity_id = next(e for e in app.expander if e.label == "Activity").proto.id
        app.run(timeout=15)
        findings = FinalAnswer(answer="Synthetic published findings")
        services.runs.publish(run, findings)
        app.run(timeout=15)
        assert not app.exception
        assert (
            next(e for e in app.expander if e.label == "Activity").proto.id
            == activity_id
        )
        assert (
            sum(m.value == "Synthetic question before activity" for m in app.markdown)
            == 1
        )
        assert sum(m.value == "Synthetic published findings" for m in app.markdown) == 1
        assert sum(e.label == "Activity" for e in app.expander) == 1
        services.runs.fail(run, "Report rendering needs retry")
        services.conversations.fail_run(thread, run)
        app.run(timeout=15)
        assert any(
            "Findings saved · Report generation failed" in m.value for m in app.markdown
        )
        assert any(b.label == "Retry report" for b in app.button)
        services.conversations.begin_run(thread, run)
        services.manager()._finish(run, findings)
        app.run(timeout=15)
        assert not app.exception
        assert (
            next(e for e in app.expander if e.label == "Activity").proto.id
            == activity_id
        )
        assert (
            sum(m.value == "Synthetic question before activity" for m in app.markdown)
            == 1
        )
        assert sum(m.value == "Synthetic published findings" for m in app.markdown) == 1
        assert sum(e.label == "Activity" for e in app.expander) == 1


def test_live_model_status_retains_fast_tool_result_context(test_settings, monkeypatch):
    from data_analytics_agent.schemas import ActivityTool

    services = Services(settings=test_settings, agent=Graph([]))
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Count artists")
    services.conversations.begin_run(thread, run)
    services.runs.start_active(run)
    services.runs.add_event(
        run,
        "tool",
        "Task",
        phase="started",
        agent="coordinator",
        tool=ActivityTool(
            call_id="task",
            name="task",
            input={"subagent_type": "text-to-sql", "description": "Count artists"},
        ),
    )
    services.runs.add_event(
        run,
        "tool",
        "Execute sql",
        phase="started",
        agent="text-to-sql",
        tool=ActivityTool(
            call_id="sql", name="execute_sql", input={"purpose": "Count artists"}
        ),
    )
    services.runs.add_event(
        run,
        "tool",
        "Execute sql",
        phase="completed",
        agent="text-to-sql",
        tool=ActivityTool(call_id="sql", name="execute_sql", output={"ok": True}),
    )
    services.runs.start_model_call(run, "model", agent="text-to-sql")
    with TestClient(create_app(services)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        for _ in range(2):
            app.run(timeout=15)
            assert not app.exception
            assert any(
                "Text-to-SQL · Reviewing SQL results · Count artists" in item.value
                for item in app.markdown
            )
