"""Official ACP stdio adapter for the existing loopback coding service."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, unquote, urlsplit

import httpx
from acp import Agent, PROTOCOL_VERSION, run_agent, text_block, tool_content
from acp.exceptions import RequestError
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities, AgentMessageChunk, InitializeResponse, Implementation,
    LoadSessionResponse, NewSessionResponse, PermissionOption, PromptCapabilities,
    PromptResponse, ResourceContentBlock, SessionMode, SessionModeState,
    SetSessionModeResponse, TextContentBlock, ToolCallUpdate, UserMessageChunk,
)

from general_agent.coding.source import validate_source_path
from general_agent.workspace import validate_corp_id


_MODES = (
    SessionMode(id="plan", name="Plan", description="Inspect the session source and draft a plan."),
    SessionMode(id="implement", name="Implement", description="Review a plan, approve implementation, then review changes."),
    SessionMode(id="review", name="Review", description="Inspect source and static diagnostics without editing or executing code."),
)


class CodingAPI:
    """One explicitly scoped connection; never start another scheduler/store."""

    def __init__(self, url: str, corp_id: str, *, transport=None):
        parsed = urlsplit(url)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if (parsed.scheme != "http" or not loopback or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("ACP requires an explicit HTTP API URL on a loopback IP address.")
        self.corp_id = validate_corp_id(corp_id)
        self.client = httpx.AsyncClient(
            base_url=url.rstrip("/"), headers={"X-Corp-ID": self.corp_id},
            timeout=30, trust_env=False, follow_redirects=False, transport=transport,
        )

    async def request(self, method: str, path: str, **kwargs):
        try:
            async with self.client.stream(method, path, **kwargs) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 8 * 1024 * 1024:
                        raise RequestError.internal_error({"reason": "Application response exceeds the editor transfer limit."})
                if response.status_code == 404:
                    raise RequestError.resource_not_found()
                if response.is_redirect:
                    raise RequestError.internal_error({"reason": "Application API redirects are not permitted."})
                decoded = httpx.Response(response.status_code, content=bytes(body)).json()
                if response.is_error:
                    detail = str(decoded.get("detail", "Coding operation failed."))[:2000]
                    raise RequestError.invalid_params({"reason": detail})
                return decoded
        except httpx.HTTPError as exc:
            raise RequestError.internal_error({"reason": "The loopback application API is unavailable."}) from exc

    async def ready(self):
        health = await self.request("GET", "/health")
        if health.get("status") != "ok":
            raise RuntimeError("Start the General Agent API before launching its editor adapter.")

    async def close(self):
        await self.client.aclose()


@dataclass
class _ActivePrompt:
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    attempt_id: str | None = None


@dataclass
class _EditorSession:
    root: Path
    mode: str = "plan"
    active: _ActivePrompt | None = None
    pending_input: str | None = None


class CodingACPAgent:
    """Structural implementation of the SDK's Agent protocol.

    Unsupported SDK methods are absent so its router returns method-not-found,
    rather than inheriting no-op bodies from the Agent typing Protocol.
    """

    def __init__(self, api: CodingAPI, *, poll_seconds: float = 0.5):
        self.api = api
        self.poll_seconds = poll_seconds
        self.sessions: dict[str, _EditorSession] = {}
        self.connection: Client | None = None

    def on_connect(self, conn: Client):
        self.connection = conn

    async def initialize(self, protocol_version: int, client_capabilities=None,
                         client_info=None, **kwargs: Any):
        if protocol_version < PROTOCOL_VERSION:
            raise RequestError.invalid_params({"reason": "This adapter requires ACP protocol version 1."})
        await self.api.ready()
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(name="general-agent", title="General Agent Coding", version="0.1.0"),
            agent_capabilities=AgentCapabilities(
                load_session=True, prompt_capabilities=PromptCapabilities(image=False, audio=False, embedded_context=False),
            ),
        )

    @staticmethod
    def _cwd(cwd: str) -> Path:
        path = Path(cwd)
        if not path.is_absolute() or any(part in {"..", "~"} for part in path.parts):
            raise RequestError.invalid_params({"reason": "An exact, registered absolute project root is required."})
        return path

    @staticmethod
    def _roots(additional_directories, mcp_servers):
        if additional_directories or mcp_servers:
            raise RequestError.invalid_params({"reason": "Additional roots and editor-provided MCP servers are unsupported."})

    @staticmethod
    def _modes(mode: str):
        return SessionModeState(current_mode_id=mode, available_modes=list(_MODES))

    def _session(self, session_id: str) -> _EditorSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise RequestError.resource_not_found() from exc

    async def new_session(self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs: Any):
        self._roots(additional_directories, mcp_servers)
        root = self._cwd(cwd)
        projects = await self.api.request("GET", "/projects")
        project = next((item for item in projects if Path(item["root"]) == root), None)
        if project is None:
            raise RequestError.invalid_params({"reason": "Register this project and approve its checks in the workbench first."})
        session = await self.api.request("POST", f"/projects/{quote(project['id'], safe='')}/sessions")
        self.sessions[session["id"]] = _EditorSession(root)
        return NewSessionResponse(session_id=session["id"], modes=self._modes("plan"))

    async def load_session(self, cwd: str, session_id: str, mcp_servers=None,
                           additional_directories=None, **kwargs: Any):
        self._roots(additional_directories, mcp_servers)
        if session_id in self.sessions and self.sessions[session_id].active:
            raise RequestError.invalid_request({"reason": "Finish the active prompt before reloading this session."})
        root = self._cwd(cwd)
        session = await self.api.request("GET", f"/sessions/{quote(session_id, safe='')}")
        if Path(session["project"]["root"]) != root:
            raise RequestError.invalid_params({"reason": "The editor root differs from this session's registered project."})
        self.sessions[session_id] = _EditorSession(root)
        # The API exposes the bounded latest fifty attempts. Failed/stopped work
        # never enters replay, matching application history policy.
        for attempt in session.get("attempts", []):
            if attempt["status"] == "completed":
                await self._update(session_id, UserMessageChunk(session_update="user_message_chunk", content=text_block(attempt["message"][:20_000])))
                if attempt.get("answer"):
                    await self._message(session_id, attempt["answer"])
        waiting = next((item for item in reversed(session.get("attempts", []))
                        if item["status"] == "waiting_input"), None)
        if waiting:
            self.sessions[session_id].mode = waiting["mode"]
            await self._input_question(session_id, waiting)
        return LoadSessionResponse(modes=self._modes(self.sessions[session_id].mode))

    async def set_session_mode(self, session_id: str, mode_id: str, **kwargs: Any):
        session = self._session(session_id)
        if mode_id not in {item.id for item in _MODES} or session.active or session.pending_input:
            raise RequestError.invalid_params({"reason": "Select an available mode after the current prompt finishes."})
        session.mode = mode_id
        return SetSessionModeResponse()

    async def _update(self, session_id: str, update):
        if self.connection is None:
            raise RuntimeError("ACP client is not connected.")
        await self.connection.session_update(session_id=session_id, update=update)

    async def _message(self, session_id: str, text: str):
        await self._update(session_id, AgentMessageChunk(session_update="agent_message_chunk", content=text_block(text[:200_000])))

    def _prompt_text(self, session: _EditorSession, blocks) -> str:
        if len(blocks) > 100:
            raise RequestError.invalid_params({"reason": "Prompt context exceeds its block limit."})
        pieces = []
        for block in blocks:
            if isinstance(block, TextContentBlock):
                pieces.append(block.text)
            elif isinstance(block, ResourceContentBlock):
                resource = urlsplit(block.uri)
                if resource.scheme != "file" or resource.netloc not in {"", "localhost"} or resource.query or resource.fragment:
                    raise RequestError.invalid_params({"reason": "Resource links must identify approved files within this project."})
                try:
                    selected = Path(unquote(resource.path)).relative_to(session.root)
                    path = validate_source_path(selected.as_posix()).as_posix()
                except ValueError as exc:
                    raise RequestError.invalid_params({"reason": "Resource link lies outside approved project source."}) from exc
                pieces.append(f"Selected source context: /repo/{path}. Read the isolated session copy.")
            else:
                raise RequestError.invalid_params({"reason": "This adapter supports text and approved source links; save buffers before creating a session."})
        text = "\n\n".join(pieces).strip()
        if not text or len(text) > 20_000:
            raise RequestError.invalid_params({"reason": "A text prompt within 20,000 characters is required."})
        return text

    async def _input_question(self, session_id: str, attempt: dict):
        decision_id = attempt.get("input_decision_id")
        if not decision_id:
            raise RequestError.internal_error({"reason": "Paused task has no durable question."})
        decision = await self.api.request("GET", f"/decisions/{quote(decision_id, safe='')}")
        if (decision["session_id"] != session_id or decision["attempt_id"] != attempt["id"]
                or decision["status"] != "pending" or decision.get("kind") != "input"):
            raise RequestError.invalid_params({"reason": "This task's question is no longer awaiting input."})
        self._session(session_id).pending_input = decision_id
        options = "\n".join(f"- {option}" for option in decision.get("options", []))
        await self._message(session_id, decision["question"] + ("\n" + options if options else "")
                            + "\nReply with your answer to resume this task, or cancel it.")

    async def _wait_attempt(self, session_id: str, active: _ActivePrompt, attempt: dict):
        active.attempt_id = attempt["id"]
        cursor = 0
        published = 0
        while True:
            if active.cancelled.is_set():
                await self._stop(active)
                return None
            record = await self.api.request("GET", f"/coding/runs/{quote(attempt['id'], safe='')}",
                                            params={"after": cursor})
            if active.cancelled.is_set():
                await self._stop(active)
                return None
            for event in record.get("events", []):
                cursor = max(cursor, event["seq"])
                if published < 1000 and event.get("kind") != "finished":
                    await self._message(session_id, f"{event.get('label', 'Working')}\n{event.get('output', '')}"[:12_000])
                    published += 1
            if record["status"] not in {"queued", "running", "stopping"} and not record.get("has_more"):
                if record.get("answer"):
                    await self._message(session_id, record["answer"])
                await self._message(session_id, f"Task {record['status']} · {record.get('outcome', 'not_verified')}."
                                    + ("\n" + record["error"] if record.get("error") else ""))
                if record["status"] == "waiting_input":
                    await self._input_question(session_id, record)
                    if active.cancelled.is_set():
                        await self._stop(_ActivePrompt(attempt_id=record["id"]))
                        self._session(session_id).pending_input = None
                        return None
                active.attempt_id = None
                return record
            if not record.get("has_more"):
                try:
                    await asyncio.wait_for(active.cancelled.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass

    async def _permission(self, session_id: str, active: _ActivePrompt, *, identifier: str,
                          title: str, content: str, revision: str, approve: str, decline: str):
        if active.cancelled.is_set():
            return None
        assert self.connection is not None
        request = asyncio.create_task(self.connection.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id=identifier, title=title, kind="edit", status="pending",
                                    content=[tool_content(text_block(content))], raw_input={"revision": revision}),
            options=[PermissionOption(option_id="approve", name=approve, kind="allow_once"),
                     PermissionOption(option_id="reject", name=decline, kind="reject_once")],
        ))
        cancellation = asyncio.create_task(active.cancelled.wait())
        try:
            await asyncio.wait((request, cancellation), return_when=asyncio.FIRST_COMPLETED)
            if active.cancelled.is_set():
                return None
            response = await request
            return response.outcome.option_id if response.outcome.outcome == "selected" else None
        finally:
            request.cancel()
            cancellation.cancel()
            await asyncio.gather(request, cancellation, return_exceptions=True)

    async def _review_changes(self, session_id: str, active: _ActivePrompt, attempt: dict):
        if not attempt.get("change_id"):
            return
        change_id = attempt["change_id"]
        diff = await self.api.request("GET", f"/changes/{quote(change_id, safe='')}/diff")
        if not diff["files"] or diff.get("review_status") == "rejected" or diff.get("apply_journal"):
            return
        await self._message(session_id, "Proposed changes in the session copy:\n" + diff["text"])
        if diff.get("truncated") or any(item.get("binary") for item in diff["files"]):
            await self._message(session_id, "This proposal needs complete file review in the workbench before applying.")
            return
        selected = await self._permission(
            session_id, active, identifier=change_id, title="Apply reviewed changes to the original checkout",
            content=diff["text"], revision=diff["revision"],
            approve="Apply these changes once", decline="Keep changes in the session",
        )
        if selected == "approve" and not active.cancelled.is_set():
            result = await self.api.request("POST", f"/changes/{quote(change_id, safe='')}/apply",
                                            json={"expected_revision": diff["revision"],
                                                  "paths": [item["path"] for item in diff["files"]]})
            await self._message(session_id, f"Changes {result['status']}. Original-checkout verification: stale; recheck before publishing.")
        else:
            await self._message(session_id, "Changes remain in the session for review; the original checkout was not changed.")

    async def prompt(self, session_id: str, prompt, **kwargs: Any):
        session = self._session(session_id)
        if session.active:
            raise RequestError.invalid_request({"reason": "A prompt is already active for this editor session."})
        message = self._prompt_text(session, prompt)
        active = session.active = _ActivePrompt()
        try:
            if session.pending_input:
                attempt = await self.api.request("POST", f"/decisions/{quote(session.pending_input, safe='')}/input",
                                                 json={"message": message})
                session.pending_input = None
            else:
                mode = "plan" if session.mode == "implement" else session.mode
                attempt = await self.api.request("POST", f"/sessions/{quote(session_id, safe='')}/tasks",
                                                 json={"message": message, "mode": mode})
            result = await self._wait_attempt(session_id, active, attempt)
            if result and result["status"] == "completed" and result["mode"] == "plan" and session.mode == "implement":
                decision_id = result.get("decision_id")
                if not decision_id:
                    raise RequestError.internal_error({"reason": "Completed plan has no durable decision."})
                decision = await self.api.request("GET", f"/decisions/{quote(decision_id, safe='')}")
                if (decision["session_id"] != session_id or decision["attempt_id"] != result["id"]
                        or decision["status"] != "pending" or decision.get("kind") != "plan"):
                    raise RequestError.invalid_params({"reason": "Plan approval is unavailable or already answered."})
                selected = await self._permission(
                    session_id, active, identifier=decision_id, title="Approve this plan for the isolated session",
                    content=result["answer"], revision=decision["revision"],
                    approve="Implement this plan once", decline="Reject this plan",
                )
                if selected in {"approve", "reject"} and not active.cancelled.is_set():
                    response = await self.api.request("POST", f"/decisions/{quote(decision_id, safe='')}/respond",
                                                      json={"response": selected})
                    if selected == "approve":
                        result = await self._wait_attempt(session_id, active, response)
            if result and result["mode"] == "implement":
                if result["status"] == "completed":
                    await self._review_changes(session_id, active, result)
                elif result.get("change_id") and result["status"] != "waiting_input":
                    await self._message(session_id, "Partial changes were saved in the session; inspect them in the workbench before applying.")
            cancelled = active.cancelled.is_set() or result is None or result["status"] == "stopped"
            return PromptResponse(stop_reason="cancelled" if cancelled else "end_turn")
        finally:
            if active.attempt_id:
                await asyncio.shield(self._stop(active))
            session.active = None

    async def _stop(self, active: _ActivePrompt):
        if active.attempt_id:
            async with asyncio.timeout(5):
                await self.api.request("POST", f"/coding/runs/{quote(active.attempt_id, safe='')}/stop")
            active.attempt_id = None

    async def cancel(self, session_id: str, **kwargs: Any):
        session = self._session(session_id)
        active = session.active
        if active:
            active.cancelled.set()
            await self._stop(active)
        if session.pending_input:
            decision = await self.api.request("GET", f"/decisions/{quote(session.pending_input, safe='')}")
            if decision["session_id"] == session_id and decision.get("kind") == "input" and decision["status"] == "pending":
                await self._stop(_ActivePrompt(attempt_id=decision["attempt_id"]))
            session.pending_input = None

    async def close(self):
        for session_id, session in self.sessions.items():
            if session.active:
                with contextlib.suppress(Exception):
                    await self.cancel(session_id)


async def serve(url: str, corp_id: str):
    api = CodingAPI(url, corp_id)
    adapter = CodingACPAgent(api)
    try:
        await api.ready()
        await run_agent(cast(Agent, adapter), stdio_buffer_limit_bytes=1024 * 1024)
    finally:
        await adapter.close()
        await api.close()


def main():
    parser = argparse.ArgumentParser(description="General Agent ACP adapter for an existing loopback API.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8001")
    parser.add_argument("--corp-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)  # stderr only; stdout belongs to ACP.
    try:
        asyncio.run(serve(args.api_url, args.corp_id))
    except (RequestError, ValueError, RuntimeError) as exc:
        logging.error("Cannot start editor adapter: %s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
