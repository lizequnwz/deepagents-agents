"""The event attachment is a scoped public projection, never an execution path."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ag_ui.core import Event
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.schemas import (
    ActivityTool,
    AgentStateSnapshot,
    ApprovalAction,
    ApprovalRequest,
    ClarificationRequest,
    FinalAnswer,
    RunStatus,
)
from data_analytics_agent.ui_events import attach_run_events


def frames(body):
    parsed = []
    for frame in body.split("\n\n"):
        lines = frame.splitlines()
        payload = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if payload is None:
            continue
        value = json.loads(payload)
        TypeAdapter(Event).validate_python(value)
        parsed.append(
            (next((line[4:] for line in lines if line.startswith("id: ")), None), value)
        )
    return parsed


@pytest.fixture
def attached(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "PRIVATE question")
    # Observation cannot initialize a model, source, worker, or query.
    for name in (
        "manager",
        "agent_for_source",
        "backend_for_source",
        "require_ready_source",
        "source",
    ):
        setattr(
            services,
            name,
            Mock(side_effect=AssertionError(f"Unexpected execution: {name}")),
        )
    return SimpleNamespace(
        services=services,
        thread=thread,
        run=run,
        url=f"/api/conversations/{thread}/runs/{run}/events",
    )


def complete(w):
    w.services.runs.complete(w.run, FinalAnswer(answer="PRIVATE analytical answer"))


def test_official_events_replay_retained_ids_before_terminal_snapshot(attached):
    w = attached
    w.services.runs.add_event(
        w.run,
        "tool",
        "PRIVATE label",
        phase="started",
        tool=ActivityTool(name="execute_sql"),
    )
    w.services.runs.add_event(
        w.run,
        "tool",
        "PRIVATE label",
        phase="completed",
        tool=ActivityTool(name="execute_sql"),
    )
    complete(w)
    with TestClient(create_app(w.services)) as client:
        response = client.get(w.url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    events = frames(response.text)
    assert [e["type"] for _, e in events] == [
        "RUN_STARTED",
        "STATE_SNAPSHOT",
        "CUSTOM",
        "CUSTOM",
        "STATE_SNAPSHOT",
        "RUN_FINISHED",
    ]
    assert [identity for identity, _ in events if identity] == [
        f"{w.run}:1",
        f"{w.run}:2",
    ]
    assert events[0][1]["runId"] == w.run
    assert events[-2][1]["snapshot"]["status"] == "completed"
    assert events[-2][1]["snapshot"]["next_event_id"] == 2
    assert events[-1][1]["outcome"] == {"type": "success"}
    assert "PRIVATE" not in response.text


def test_reconnect_uses_current_state_and_header_cursor_without_source_work(attached):
    w = attached
    for phase in ("started", "completed"):
        w.services.runs.add_event(
            w.run, "tool", "Query", phase=phase, tool=ActivityTool(name="execute_sql")
        )
    complete(w)
    # Reopen stores to prove that the cursor belongs to durable events, not a
    # live stream, worker, or transport session.
    reopened = Services(settings=w.services.settings)
    reopened.manager = Mock(side_effect=AssertionError("Must not resume"))
    with TestClient(create_app(reopened)) as client:
        response = client.get(
            w.url + "?after_event_id=0", headers={"Last-Event-ID": f"{w.run}:1"}
        )
        tail = client.get(w.url + "?after_event_id=2")
    events = frames(response.text)
    assert [identity for identity, _ in events if identity] == [f"{w.run}:2"]
    assert events[1][1]["snapshot"]["answer_ready"] is True
    assert [identity for identity, _ in frames(tail.text) if identity] == []
    assert frames(tail.text)[-1][1]["type"] == "RUN_FINISHED"
    assert reopened.runs.get(w.run).status == RunStatus.COMPLETED
    reopened.manager.assert_not_called()


@pytest.mark.parametrize(
    "cursor",
    ["other-run:0", "invalid", "run:-1", "run:999999999999999999999", "run:１"],
)
def test_invalid_reconnect_headers_are_rejected(attached, cursor):
    w = attached
    complete(w)
    cursor = cursor.replace("run:", f"{w.run}:")
    with TestClient(create_app(w.services)) as client:
        if not cursor.isascii():
            # HTTP headers are Latin-1. Test the parser directly for Unicode.
            from fastapi import HTTPException

            from data_analytics_agent.ui_events import _cursor

            with pytest.raises(HTTPException):
                _cursor(w.run, 0, cursor)
        else:
            assert (
                client.get(w.url, headers={"Last-Event-ID": cursor}).status_code == 422
            )


def test_scope_deletion_and_ahead_cursor_are_checked_before_stream(attached):
    w = attached
    complete(w)
    other_thread = w.services.conversations.create("test")
    foreign_source_run = w.services.runs.create(
        w.thread, "other-source", "PRIVATE source"
    )
    with TestClient(create_app(w.services)) as client:
        assert (
            client.get(
                f"/api/conversations/{other_thread}/runs/{w.run}/events"
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/conversations/{w.thread}/runs/{foreign_source_run}/events"
            ).status_code
            == 404
        )
        assert client.get(w.url + "?after_event_id=1").status_code == 409
        assert client.get(w.url + "?after_event_id=-1").status_code == 422
        w.services.deleting_conversations.add(w.thread)
        assert client.get(w.url).status_code == 409
    assert not w.services.manager.called


def test_public_allowlist_excludes_graph_state_code_rows_and_error_details(attached):
    w = attached
    private = "PRIVATE_SQL_ROWS_PROMPT_SECRET"
    w.services.runs.add_event(
        w.run,
        private,
        private,
        agent=private,
        phase="failed",
        tool=ActivityTool(
            name=private, call_id=private, input={private: [1, 2]}, output=private
        ),
    )
    w.services.runs.add_event(
        w.run,
        "tool",
        private,
        phase="completed",
        agent="text-to-sql",
        tool=ActivityTool(
            name="execute_sql", input={"query": private}, output={"rows": [private]}
        ),
    )
    w.services.runs.set_debug_state(
        w.run, AgentStateSnapshot(agent="coordinator", state={"messages": private})
    )
    w.services.runs.set_phase(w.run, private)
    w.services.runs.accept_correction(w.run, private)
    w.services.runs.fail(w.run, private)
    with TestClient(create_app(w.services)) as client:
        response = client.get(w.url)
    events = frames(response.text)
    assert private not in response.text
    assert "PRIVATE" not in response.text
    assert events[1][1]["snapshot"]["phase"] == "working"
    activity = [e["value"] for _, e in events if e["type"] == "CUSTOM"]
    assert activity[0]["tool_name"] is None and activity[0]["agent"] is None
    assert activity[1]["label"] == "Retrieve data"
    assert events[-1][1]["type"] == "RUN_ERROR"
    assert events[-1][1]["code"] == "RUN_FAILED"
    assert not any(e["type"] == "RUN_FINISHED" for _, e in events)


@pytest.mark.parametrize(
    "status", ["paused", "approval_required", "clarification_required"]
)
def test_paused_review_and_clarification_close_with_explicit_outcomes(attached, status):
    w = attached
    private = "PRIVATE review code or clarification text"
    if status == "paused":
        w.services.runs.pause(w.run)
    elif status == "approval_required":
        w.services.runs.require_approval(
            w.run,
            ApprovalRequest(
                interrupt_id="review-1",
                actions=[
                    ApprovalAction(
                        action_name=private,
                        query=private,
                        arguments={"rows": private},
                        allowed_decisions=["approve"],
                        review_type="sql",
                        description=private,
                    )
                ],
            ),
        )
    else:
        w.services.runs.require_clarification(
            w.run,
            ClarificationRequest(
                interrupt_id="clarify-1", question=private, choices=[private]
            ),
        )
    with TestClient(create_app(w.services)) as client:
        response = client.get(w.url)
    events = frames(response.text)
    assert private not in response.text
    assert events[-2][1]["snapshot"]["status"] == status
    terminal = events[-1][1]
    assert terminal["type"] == "RUN_FINISHED"
    assert terminal["result"] == {"status": status}
    assert terminal["outcome"]["type"] == (
        "cancelled" if status == "paused" else "interrupt"
    )
    assert w.services.runs.get(w.run).status == status


class Connection:
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


async def test_live_attachment_observes_completion_without_owning_execution(attached):
    w = attached
    w.services.runs.start_active(w.run)
    connection = Connection()
    stream = attach_run_events(w.services, connection, w.services.runs.get(w.run), 0)
    assert frames(await anext(stream))[0][1]["type"] == "RUN_STARTED"
    assert frames(await anext(stream))[0][1]["snapshot"]["status"] == "running"
    w.services.runs.add_event(
        w.run,
        "tool",
        "Execute SQL",
        phase="completed",
        tool=ActivityTool(name="execute_sql"),
    )
    complete(w)
    tail = frames("".join([chunk async for chunk in stream]))
    assert [e["type"] for _, e in tail] == ["CUSTOM", "STATE_SNAPSHOT", "RUN_FINISHED"]
    assert tail[-2][1]["snapshot"]["status"] == "completed"
    assert not w.services.manager.called


async def test_disconnect_and_generator_close_do_not_stop_or_resume_run(attached):
    w = attached
    w.services.runs.start_active(w.run)
    for disconnect in (False, True):
        connection = Connection()
        stream = attach_run_events(
            w.services, connection, w.services.runs.get(w.run), 0
        )
        await anext(stream)
        await anext(stream)
        if disconnect:
            connection.disconnected = True
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        else:
            await stream.aclose()
        assert w.services.runs.get(w.run).status == RunStatus.RUNNING
        assert not w.services.runs.cancel_event(w.run).is_set()
    assert not w.services.manager.called


async def test_scope_revocation_during_attachment_closes_without_private_details(
    attached,
):
    w = attached
    stream = attach_run_events(w.services, Connection(), w.services.runs.get(w.run), 0)
    await anext(stream)
    await anext(stream)
    w.services.deleting_conversations.add(w.thread)
    tail = frames("".join([chunk async for chunk in stream]))
    assert len(tail) == 1
    assert tail[0][1]["code"] == "ATTACHMENT_UNAVAILABLE"
    assert not w.services.manager.called
