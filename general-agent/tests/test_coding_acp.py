"""Official SDK routing with synthetic application API records; no providers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from acp import PROTOCOL_VERSION, spawn_agent_process
from acp.agent.connection import AgentSideConnection
from acp.client.connection import ClientSideConnection
from acp._transport import memory_transport_pair
from acp.exceptions import RequestError
from acp.schema import (
    AllowedOutcome, ClientCapabilities, DeniedOutcome, FileSystemCapabilities,
    RequestPermissionResponse, ResourceContentBlock, TextContentBlock,
)

from general_agent.coding.acp import CodingACPAgent, CodingAPI


class FixtureAPI:
    def __init__(self):
        self.requests = []
        self.run_state = "completed"
        self.plan_status = "pending"
        self.diff_truncated = False
        self.diff_binary = False
        self.apply_conflict = False
        self.waiting_mode = "plan"
        self.input_status = "pending"
        self.input_conflict = False

    def handle(self, request):
        payload = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, payload, request.headers.get("X-Corp-ID")))
        assert request.headers.get("X-Corp-ID") == "CORP_A"
        path = request.url.path
        record = {"id": "plan", "session_id": "session", "mode": "plan", "status": self.run_state,
                  "answer": "Review this plan", "message": "Fix the task", "outcome": "not_verified",
                  "decision_id": "decision", "events": [], "has_more": False}
        if self.run_state == "waiting_input":
            record.update(mode=self.waiting_mode, input_decision_id="question", answer="")
        if path == "/health":
            value = {"status": "ok"}
        elif path == "/projects":
            value = [{"id": "project", "root": "/approved/project"}]
        elif path == "/projects/project/sessions":
            value = {"id": "session"}
        elif path == "/sessions/session":
            value = {"id": "session", "project": {"root": "/approved/project"},
                     "attempts": [record, {**record, "status": "failed", "answer": "DO_NOT_REPLAY"}]}
        elif path == "/sessions/session/tasks":
            value = record
        elif path == "/coding/runs/plan":
            value = record
        elif path == "/decisions/decision":
            value = {"id": "decision", "session_id": "session", "attempt_id": "plan",
                     "revision": "source-revision", "status": self.plan_status, "kind": "plan"}
        elif path == "/decisions/question":
            value = {"id": "question", "session_id": "session", "attempt_id": "plan", "kind": "input",
                     "revision": "source-revision", "status": self.input_status,
                     "question": "Which increment?", "options": ["Two", "Three"]}
        elif path == "/decisions/question/input":
            if self.input_conflict:
                return httpx.Response(409, json={"detail": "Source changed while waiting."})
            self.run_state = "completed"
            self.input_status = "answered"
            value = {"id": "plan"}
        elif path == "/decisions/decision/respond":
            value = {"id": "implementation"} if payload["response"] == "approve" else {"status": "rejected"}
        elif path == "/coding/runs/implementation":
            value = {**record, "id": "implementation", "mode": "implement", "answer": "Implemented task",
                     "change_id": "proposal", "outcome": "verified"}
        elif path == "/changes/proposal/diff":
            value = {"text": "--- a/main.py\n+++ b/main.py\n-old\n+new\n", "revision": "exact-proposal-revision",
                     "files": [{"path": "main.py", "binary": self.diff_binary}],
                     "truncated": self.diff_truncated, "review_status": "pending"}
        elif path == "/changes/proposal/apply":
            if self.apply_conflict:
                return httpx.Response(409, json={"detail": "Original source changed."})
            value = {"status": "applied"}
        elif path == "/coding/runs/plan/stop":
            self.run_state = "stopped"
            value = {"status": "stopped"}
        else:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=value)


class FixtureClient:
    def __init__(self, answers=()):
        self.answers = iter(answers)
        self.updates = []
        self.permissions = []
        self.permission_started = asyncio.Event()
        self.permission_wait = None

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append((session_id, update))

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        self.permissions.append((session_id, tool_call, options))
        self.permission_started.set()
        if self.permission_wait:
            await self.permission_wait.wait()
        answer = next(self.answers, None)
        return RequestPermissionResponse(outcome=AllowedOutcome(option_id=answer, outcome="selected")
                                         if answer else DeniedOutcome(outcome="cancelled"))

    async def read_text_file(self, **kwargs):
        pytest.fail("Original editor files must never be read")

    async def write_text_file(self, **kwargs):
        pytest.fail("Original editor files must never be written")

    async def create_terminal(self, **kwargs):
        pytest.fail("Editor terminals must never execute agent work")


@pytest.fixture
async def acp_connection():
    fixture = FixtureAPI()
    api = CodingAPI("http://127.0.0.1:8001", "CORP_A", transport=httpx.MockTransport(fixture.handle))
    adapter = CodingACPAgent(api, poll_seconds=0.01)
    client = FixtureClient()
    left, right = memory_transport_pair()
    server = AgentSideConnection(adapter, left)
    connection = ClientSideConnection(client, right)
    yield fixture, adapter, client, connection
    await connection.close()
    await server.close()
    await adapter.close()
    await api.close()


async def open_session(connection):
    initialized = await connection.initialize(
        protocol_version=PROTOCOL_VERSION,
        client_capabilities=ClientCapabilities(fs=FileSystemCapabilities(read_text_file=True, write_text_file=True), terminal=True),
    )
    created = await connection.new_session(cwd="/approved/project", mcp_servers=[])
    return initialized, created


async def test_native_sdk_initialization_plan_and_scoped_copy_only(acp_connection):
    fixture, adapter, client, connection = acp_connection
    initialized, created = await open_session(connection)
    assert initialized.protocol_version == 1
    assert initialized.agent_capabilities.load_session
    assert not initialized.agent_capabilities.prompt_capabilities.embedded_context
    assert created.modes.current_mode_id == "plan"
    response = await connection.prompt(session_id=created.session_id, prompt=[TextContentBlock(type="text", text="Fix task")])
    assert response.stop_reason == "end_turn"
    assert not client.permissions
    assert next(body for method, path, body, corp in fixture.requests if path.endswith("/tasks"))["mode"] == "plan"
    assert not any(path.endswith("/respond") or path.endswith("/apply") for _, path, _, _ in fixture.requests)


async def test_two_explicit_permissions_apply_exact_immutable_revision(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    client.answers = iter(["approve", "approve"])
    await connection.set_session_mode(session_id="session", mode_id="implement")
    response = await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement task")])
    assert response.stop_reason == "end_turn"
    assert len(client.permissions) == 2
    assert client.permissions[0][1].raw_input["revision"] == "source-revision"
    assert client.permissions[1][1].raw_input["revision"] == "exact-proposal-revision"
    assert all({option.kind for option in options} == {"allow_once", "reject_once"} for _, _, options in client.permissions)
    applied = next(body for method, path, body, corp in fixture.requests if path.endswith("/apply"))
    assert applied == {"expected_revision": "exact-proposal-revision", "paths": ["main.py"]}
    assert all(corp == "CORP_A" for _, _, _, corp in fixture.requests)


@pytest.mark.parametrize("answers", [("reject",), (None,), ("approve", "reject"), ("approve", None)])
async def test_permission_rejection_and_cancellation_never_apply(acp_connection, answers):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    client.answers = iter(answers)
    await connection.set_session_mode(session_id="session", mode_id="implement")
    await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement task")])
    assert not any(path.endswith("/apply") for _, path, _, _ in fixture.requests)
    if answers[0] != "approve":
        assert not any(path == "/coding/runs/implementation" for _, path, _, _ in fixture.requests)


async def test_cancel_active_attempt_uses_service_stop(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    fixture.run_state = "running"
    prompt = asyncio.create_task(connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Inspect")]))
    while not any(path == "/coding/runs/plan" for _, path, _, _ in fixture.requests):
        await asyncio.sleep(0)
    await connection.cancel(session_id="session")
    response = await asyncio.wait_for(prompt, 2)
    assert response.stop_reason == "cancelled"
    assert any(path.endswith("/stop") for _, path, _, _ in fixture.requests)


async def test_cancel_permission_and_reload_race_never_approves(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    await connection.set_session_mode(session_id="session", mode_id="implement")
    client.permission_wait = asyncio.Event()
    prompt = asyncio.create_task(connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement")]))
    await asyncio.wait_for(client.permission_started.wait(), 2)
    with pytest.raises(RequestError):
        await connection.load_session(session_id="session", cwd="/approved/project", mcp_servers=[])
    await connection.cancel(session_id="session")
    assert (await asyncio.wait_for(prompt, 2)).stop_reason == "cancelled"
    assert not any(path.endswith("/respond") or path.endswith("/apply") for _, path, _, _ in fixture.requests)


async def test_load_replays_completed_history_and_checks_scope(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await connection.initialize(protocol_version=PROTOCOL_VERSION)
    await connection.load_session(session_id="session", cwd="/approved/project", mcp_servers=[])
    assert any(update.content.text == "Review this plan" for _, update in client.updates)
    assert all("DO_NOT_REPLAY" not in update.content.text for _, update in client.updates)
    with pytest.raises(RequestError):
        await connection.load_session(session_id="session", cwd="/foreign/project", mcp_servers=[])
    with pytest.raises(RequestError):
        await connection.load_session(session_id="foreign", cwd="/approved/project", mcp_servers=[])


async def test_resource_links_are_virtual_context_without_host_reads(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Inspect"),
        ResourceContentBlock(type="resource_link", name="main.py", uri="file:///approved/project/main.py")])
    body = next(body for _, path, body, _ in fixture.requests if path.endswith("/tasks"))
    assert "/repo/main.py" in body["message"] and "file:///" not in body["message"]
    for uri in ("file:///foreign/secret.py", "file:///approved/project/.env", "https://example.com/a", "file:///approved/project/../outside.py"):
        with pytest.raises(RequestError):
            await connection.prompt(session_id="session", prompt=[ResourceContentBlock(type="resource_link", name="selected", uri=uri)])


@pytest.mark.parametrize("field", ["diff_truncated", "diff_binary"])
async def test_incomplete_editor_review_requires_workbench(acp_connection, field):
    fixture, adapter, client, connection = acp_connection
    setattr(fixture, field, True)
    await open_session(connection)
    client.answers = iter(["approve", "approve"])
    await connection.set_session_mode(session_id="session", mode_id="implement")
    await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement")])
    assert len(client.permissions) == 1
    assert not any(path.endswith("/apply") for _, path, _, _ in fixture.requests)


async def test_stale_plan_and_original_conflicts_are_not_retried(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    client.answers = iter(["approve", "approve"])
    await connection.set_session_mode(session_id="session", mode_id="implement")
    fixture.plan_status = "rejected"
    with pytest.raises(RequestError):
        await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement")])
    assert not client.permissions
    fixture.plan_status = "pending"
    fixture.apply_conflict = True
    with pytest.raises(RequestError):
        await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Implement")])
    assert sum(path.endswith("/apply") for _, path, _, _ in fixture.requests) == 1


async def test_unsupported_protocol_actions_and_additional_roots(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    with pytest.raises(RequestError, match="Method not found"):
        await connection.authenticate(method_id="anything")
    with pytest.raises(RequestError):
        await connection.new_session(cwd="/approved/project", additional_directories=["/foreign"])
    with pytest.raises(RequestError):
        await connection.new_session(cwd="/unregistered/project", mcp_servers=[])


async def test_paused_question_waits_for_next_human_prompt_before_resuming(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    fixture.run_state = "waiting_input"
    await connection.set_session_mode(session_id="session", mode_id="implement")
    result = await asyncio.wait_for(connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Fix")]), 2)
    assert result.stop_reason == "end_turn"
    assert adapter.sessions["session"].pending_input == "question"
    assert any("Which increment?" in update.content.text for _, update in client.updates)
    assert not any(path.endswith("/input") or path.endswith("/respond") for _, path, _, _ in fixture.requests)
    with pytest.raises(RequestError):
        await connection.set_session_mode(session_id="session", mode_id="review")
    client.answers = iter(["approve", "reject"])
    result = await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Two")])
    assert result.stop_reason == "end_turn"
    assert adapter.sessions["session"].pending_input is None
    assert next(body for _, path, body, _ in fixture.requests if path.endswith("/input")) == {"message": "Two"}
    assert sum(path.endswith("/tasks") for _, path, _, _ in fixture.requests) == 1
    assert len(client.permissions) == 2
    assert not any(path.endswith("/apply") for _, path, _, _ in fixture.requests)


async def test_loading_question_and_cancel_use_existing_attempt(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await connection.initialize(protocol_version=PROTOCOL_VERSION)
    fixture.run_state = "waiting_input"
    loaded = await connection.load_session(session_id="session", cwd="/approved/project", mcp_servers=[])
    assert loaded.modes.current_mode_id == "plan"
    assert adapter.sessions["session"].pending_input == "question"
    assert not any(path.endswith("/input") for _, path, _, _ in fixture.requests)
    await connection.cancel(session_id="session")
    async with asyncio.timeout(2):
        while fixture.run_state != "stopped":
            await asyncio.sleep(0.01)
    assert fixture.run_state == "stopped"
    assert adapter.sessions["session"].pending_input is None


async def test_stale_input_answer_is_not_retried_or_replaced_with_new_task(acp_connection):
    fixture, adapter, client, connection = acp_connection
    await open_session(connection)
    fixture.run_state = "waiting_input"
    await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Plan")])
    fixture.input_conflict = True
    with pytest.raises(RequestError):
        await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Two")])
    assert sum(path.endswith("/input") for _, path, _, _ in fixture.requests) == 1
    assert sum(path.endswith("/tasks") for _, path, _, _ in fixture.requests) == 1
    assert adapter.sessions["session"].pending_input == "question"


@pytest.mark.parametrize("url", ["https://127.0.0.1:8001", "http://example.com", "http://localhost:8001",
                                  "http://user:secret@127.0.0.1:8001", "http://127.0.0.1:8001/path"])
def test_adapter_rejects_remote_ambiguous_or_credential_urls(url):
    with pytest.raises(ValueError):
        CodingAPI(url, "CORP_A")


async def test_native_stdio_entrypoint_uses_official_sdk_transport():
    fixture = FixtureAPI()

    class Handler(BaseHTTPRequestHandler):
        def serve_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            response = fixture.handle(httpx.Request(self.command, "http://127.0.0.1" + self.path,
                                                    headers=dict(self.headers), content=body))
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = serve_request

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        client = FixtureClient()
        try:
            async with asyncio.timeout(8):
                async with spawn_agent_process(client, sys.executable, "-m", "general_agent.coding.acp",
                    "--corp-id", "CORP_A", "--api-url", f"http://127.0.0.1:{server.server_port}",
                    env={"PATH": os.path.dirname(sys.executable), "PYTHONDONTWRITEBYTECODE": "1"}) as (connection, process):
                    await open_session(connection)
                    response = await connection.prompt(session_id="session", prompt=[TextContentBlock(type="text", text="Plan")])
                    assert response.stop_reason == "end_turn"
                    assert process.returncode is None
                    assert any(update.content.text == "Review this plan" for _, update in client.updates)
        finally:
            server.shutdown()
            worker.join(2)


async def test_sdk_through_shared_service_question_plan_checks_and_apply(settings):
    from fastapi.testclient import TestClient
    from langchain_core.messages import AIMessage

    from general_agent.api import create_app
    from tests.fakes import FakeGraph
    from tests.test_budgets import ScriptedModel
    from tests.test_coding_api import FixtureRuntime, fixture_project, tool_call

    root = fixture_project(settings)
    model = ScriptedModel(responses=[
        tool_call("request_input", {"question": "Which increment?", "options": ["Two", "Three"]}, "ask"),
        AIMessage(content="Change increment to add two and run the approved tests."),
        tool_call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, "edit"),
        tool_call("run_check", {"name": "tests"}, "check"), AIMessage(content="Implemented and checked."),
    ])
    app = create_app(settings=settings, graph_override=FakeGraph(), coding_model=model,
                     coding_runtime_factory=FixtureRuntime)
    requests = []

    class CheckingClient(FixtureClient):
        async def request_permission(self, *args, **kwargs):
            assert "value + 1" in (root / "increment.py").read_text()
            return await super().request_permission(*args, **kwargs)

    with TestClient(app) as workbench:
        registered = workbench.post("/projects", headers={"X-Corp-ID": "CORP_A"}, json={
            "root": str(root), "name": "ACP Fixture", "checks": {"tests": "python -m unittest discover -s tests"}})
        assert registered.status_code == 201, registered.text

        def forward(request):
            body = json.loads(request.content) if request.content else None
            requests.append((request.method, request.url.path, body, request.headers["X-Corp-ID"]))
            result = workbench.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(result.status_code, content=result.content, headers=result.headers)

        api = CodingAPI("http://127.0.0.1:8001", "CORP_A", transport=httpx.MockTransport(forward))
        adapter = CodingACPAgent(api, poll_seconds=0.01)
        client = CheckingClient(["approve", "approve"])
        left, right = memory_transport_pair()
        server = AgentSideConnection(adapter, left)
        connection = ClientSideConnection(client, right)
        try:
            await connection.initialize(protocol_version=PROTOCOL_VERSION)
            created = await connection.new_session(cwd=str(root), mcp_servers=[])
            await connection.set_session_mode(session_id=created.session_id, mode_id="implement")
            question = await connection.prompt(session_id=created.session_id, prompt=[TextContentBlock(type="text", text="Fix increment")])
            assert question.stop_reason == "end_turn" and not client.permissions
            assert "value + 1" in (root / "increment.py").read_text()
            finished = await connection.prompt(session_id=created.session_id, prompt=[TextContentBlock(type="text", text="Two")])
            assert finished.stop_reason == "end_turn"
            assert len(client.permissions) == 2, [update.content.text for _, update in client.updates]
            assert "value + 2" in (root / "increment.py").read_text()
            assert (root / "user.txt").read_text() == "unrelated dirty user file"
            applied = next(body for _, path, body, _ in requests if path.endswith("/apply"))
            assert applied["expected_revision"] == client.permissions[1][1].raw_input["revision"]
            assert all(corp == "CORP_A" for _, _, _, corp in requests)
            assert any("verified" in update.content.text for _, update in client.updates)
            assert workbench.get(f"/sessions/{created.session_id}", headers={"X-Corp-ID": "OTHER_CORP"}).status_code == 404
        finally:
            await connection.close()
            await server.close()
            await adapter.close()
            await api.close()
