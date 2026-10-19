"""Streamlit's supported UI harness verifies stable navigation and run controls."""

from pathlib import Path
from types import SimpleNamespace

import pytest
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
        assert app.chat_input[0].proto.accept_file
        composer_id = app.chat_input[0].proto.id
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
        assert app.chat_input[0].proto.id == composer_id
        services.runs.fail(run, "Report rendering needs retry")
        services.conversations.fail_run(thread, run)
        app.run(timeout=15)
        assert any(
            "Findings saved · Report generation failed" in m.value for m in app.markdown
        )
        assert any(b.label == "Retry report" for b in app.button)
        assert app.chat_input[0].proto.id == composer_id
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

        assert app.chat_input[0].proto.id == composer_id


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
                "Reviewing retrieved data · Count artists" in item.value
                for item in app.markdown
            )


def test_chat_attachment_preserves_question_until_review(test_settings, monkeypatch):
    from types import SimpleNamespace
    from data_analytics_agent.ui import uploads

    services = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Ready to help."))]),
    )
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
        native = uploads.chat_submission
        submitted = [
            SimpleNamespace(
                text="What can you analyze?",
                files=[
                    SimpleNamespace(
                        name="sales.csv", size=11, getvalue=lambda: b"amount\n1\n2\n"
                    )
                ],
            )
        ]

        def composer(*args, **kwargs):
            native(*args, **kwargs)
            return submitted.pop() if submitted else None

        monkeypatch.setattr(uploads, "chat_submission", composer)
        app = AppTest.from_file(
            str(Path(__file__).parents[1] / "streamlit_app.py")
        ).run(timeout=15)
        assert not app.exception
        thread = app.query_params["thread_id"][0]
        assert services.conversations.get(thread).source_id.startswith("upload:")
        assert not services.conversations.get(thread).run_ids
        assert any("What can you analyze?" in i.value for i in app.info)
        next(
            b for b in app.button if b.label == "Confirm data and continue"
        ).click().run(timeout=15)
        assert not app.exception
        conversation = services.conversations.get(thread)
        assert len(conversation.turns) == 1
        assert conversation.turns[0].user_message == "What can you analyze?"
        reopened = AppTest.from_file(
            str(Path(__file__).parents[1] / "streamlit_app.py")
        )
        reopened.query_params["thread_id"] = thread
        reopened.run(timeout=15)
        assert not reopened.exception
        assert len(services.conversations.get(thread).turns) == 1
        assert reopened.chat_input[0].proto.accept_file


@pytest.mark.parametrize(
    "source_kind,filename,content,needs_review",
    [
        ("file", "more.csv", b"amount\n3\n4\n", True),
        ("file", "notes.md", b"# Context\nAmounts are source units.", False),
        ("warehouse", "notes.txt", b"Amounts are source units.", False),
    ],
)
def test_composer_attachments_keep_conversation_and_question(
    test_settings, monkeypatch, source_kind, filename, content, needs_review
):
    from data_analytics_agent.ui import uploads
    from data_analytics_agent.uploads import stage_upload, uploads_for_thread
    from tests.test_file_workspace import confirm

    services = Services(
        settings=test_settings,
        agent=Graph([
            Stream(CoordinatorResponse(answer="Existing context.")),
            Stream(CoordinatorResponse(answer="Attachment received.")),
        ]),
    )
    if source_kind == "file":
        original = confirm(services, stage_upload(services, b"id\n1\n", "original.csv"))
        thread = original.thread_id
    else:
        thread = services.conversations.create("test")
    source_id = services.conversations.get(thread).source_id
    with TestClient(create_app(services)) as api:
        api.post(f"/api/conversations/{thread}/messages", json={"message": "Hello"}).raise_for_status()

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(str(response.json().get("detail")), status_code=response.status_code)
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        native = uploads.chat_submission
        submissions = [SimpleNamespace(
            text="What can you tell me about this attachment?",
            files=[SimpleNamespace(name=filename, size=len(content), getvalue=lambda: content)],
        )]

        def composer(*args, **kwargs):
            native(*args, **kwargs)
            return submissions.pop() if submissions else None

        monkeypatch.setattr(uploads, "chat_submission", composer)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        assert not app.exception
        assert app.query_params["thread_id"] == [thread]
        assert len(services.conversations.list()) == 1
        if needs_review:
            assert len(services.conversations.get(thread).turns) == 1
            assert len(uploads_for_thread(services, thread)) == 2
            assert any("What can you tell me" in item.value for item in app.info)
            next(b for b in app.button if b.label == "Confirm data and continue").click().run(timeout=15)
        else:
            documents = api.get(f"/api/conversations/{thread}/documents").json()["documents"]
            assert len(documents) == 1 and documents[0]["filename"] == filename
        assert not app.exception
        current = services.conversations.get(thread)
        assert current.source_id == source_id
        assert len(current.turns) == 2
        assert current.turns[-1].user_message == "What can you tell me about this attachment?"
        assert not any(item.label == "Analyze" for item in app.selectbox)
        assert not any(item.label == "Add data and documents" for item in app.expander)
        assert not app.get("file_uploader")
        reopened = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        reopened.query_params["thread_id"] = thread
        reopened.run(timeout=15)
        assert not reopened.exception
        assert len(services.conversations.get(thread).turns) == 2


@pytest.mark.parametrize("accept", [True, False])
def test_table_attachment_in_established_warehouse_requires_file_conversation(
    test_settings, monkeypatch, accept
):
    from data_analytics_agent.ui import uploads

    services = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Warehouse context."))]),
    )
    thread = services.conversations.create("test")
    with TestClient(create_app(services)) as api:
        api.post(f"/api/conversations/{thread}/messages", json={"message": "Hello"}).raise_for_status()

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(str(response.json().get("detail")), status_code=response.status_code)
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        native = uploads.chat_submission
        submissions = [SimpleNamespace(
            text="Explore this table",
            files=[SimpleNamespace(name="new.csv", size=4, getvalue=lambda: b"x\n1\n")],
        )]

        def composer(*args, **kwargs):
            native(*args, **kwargs)
            return submissions.pop() if submissions else None

        monkeypatch.setattr(uploads, "chat_submission", composer)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        assert not app.exception
        assert len(services.conversations.list()) == 1
        label = "Start file conversation" if accept else "Cancel attachment"
        next(button for button in app.button if button.label == label).click().run(timeout=15)
        assert not app.exception
        assert services.conversations.get(thread).source_id == "test"
        assert len(services.conversations.get(thread).turns) == 1
        if accept:
            new_thread = app.query_params["thread_id"][0]
            assert new_thread != thread
            assert services.conversations.get(new_thread).source_id.startswith("upload:")
            assert not services.conversations.get(new_thread).run_ids
            assert any("Explore this table" in item.value for item in app.info)
        else:
            assert len(services.conversations.list()) == 1
            assert app.chat_input[0].value == "Explore this table"
