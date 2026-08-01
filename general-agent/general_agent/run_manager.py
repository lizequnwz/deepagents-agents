"""Persistent background-run lifecycle over DeepAgents v3 event streaming."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from general_agent.config import Settings
from general_agent.execution import CancellableLocalShellBackend
from general_agent.schemas import Attachment, RunStatus
from general_agent.store import Store
from general_agent.workspace import FileStamp, Workspace, agent_virtual_path


class TokenBudgetExceeded(RuntimeError):
    """Raised after provider-reported usage crosses the configured run ceiling."""


class RunUsageCallback(BaseCallbackHandler):
    """Record only model calls that actually execute during the current run."""

    def __init__(self, store: Store, run_id: str, corp_id: str) -> None:
        super().__init__()
        self.store = store
        self.run_id = run_id
        self.corp_id = corp_id
        self.active: dict[str, str] = {}
        self.reported_tokens = 0

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, messages, kwargs
        self.active[str(run_id)] = _agent_from_model_metadata(metadata)

    def on_llm_end(
        self, response: LLMResult, *, run_id: Any, **kwargs: Any
    ) -> None:
        del kwargs
        usage: Mapping[str, Any] | None = None
        try:
            generation = response.generations[0][0]
        except IndexError:
            generation = None
        if isinstance(generation, ChatGeneration) and isinstance(
            generation.message, AIMessage
        ):
            usage = generation.message.usage_metadata
        self._finish(str(run_id), usage)

    def on_llm_error(
        self, error: BaseException, *, run_id: Any, **kwargs: Any
    ) -> None:
        del error, kwargs
        self._finish(str(run_id), None)

    def finalize_incomplete(self) -> None:
        for call_id in list(self.active):
            self._finish(call_id, None)

    def _finish(
        self, call_id: str, usage: Mapping[str, Any] | None
    ) -> None:
        agent = self.active.pop(call_id, "general-agent")
        self.store.record_model_call(
            self.run_id, agent, usage, corp_id=self.corp_id
        )
        if usage and isinstance(usage.get("total_tokens"), int):
            self.reported_tokens += int(usage["total_tokens"])
        self.store.add_event(
            self.run_id,
            "usage_updated",
            "updated",
            f"Usage updated · {agent}",
            agent=agent,
            data={"usage": _jsonable(usage)},
            corp_id=self.corp_id,
        )


class RunManager:
    """Start, stream, stop, and finalize one trusted local run at a time."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        workspace: Workspace,
        backend: CancellableLocalShellBackend,
        graph: Any,
    ) -> None:
        self.settings = settings
        self.store = store
        self.workspace = workspace
        self.backend = backend
        self.graph = graph
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._streams: dict[str, Any] = {}
        self._run_corps: dict[str, str] = {}
        self._secret_values = _secret_values()

    def create_run(self, corp_id: str, conversation_id: str, question: str) -> str:
        run_id, _turn_id = self.store.create_run(
            conversation_id, question, corp_id=corp_id
        )
        return run_id

    def add_upload(
        self,
        run_id: str,
        corp_id: str,
        conversation_id: str,
        *,
        original_name: str,
        content_type: str | None,
        source: BinaryIO,
    ) -> Attachment:
        attachment, protected = self.workspace.upload(
            corp_id=corp_id,
            conversation_id=conversation_id,
            original_name=original_name,
            content_type=content_type,
            source=source,
            max_bytes=self.settings.max_upload_mb * 1024 * 1024,
        )
        self.store.add_attachment(
            run_id, attachment, protected, corp_id=corp_id
        )
        return attachment

    def start(
        self, run_id: str, corp_id: str, attachments: list[Attachment]
    ) -> None:
        self._run_corps[run_id] = corp_id
        task = asyncio.create_task(
            self._drive(run_id, corp_id, attachments),
            name=f"general-agent-{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._forget_run(run_id))

    def _forget_run(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._run_corps.pop(run_id, None)

    async def stop(self, run_id: str, corp_id: str) -> bool:
        if not self.store.request_stop(run_id, corp_id=corp_id):
            return False
        self.store.add_event(
            run_id,
            "run_status",
            "updated",
            "Stopping the run",
            data={"status": RunStatus.STOPPING},
            corp_id=corp_id,
        )
        await self.backend.cancel_run(run_id)
        stream = self._streams.get(run_id)
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.abort()
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        return True

    async def shutdown(self) -> None:
        run_ids = list(self._tasks)
        await asyncio.gather(
            *(
                self.stop(run_id, self._run_corps[run_id])
                for run_id in run_ids
                if run_id in self._run_corps
            ),
            return_exceptions=True,
        )
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _drive(
        self, run_id: str, corp_id: str, attachments: list[Attachment]
    ) -> None:
        run = self.store.get_run(run_id, corp_id=corp_id)
        history = self.store.completed_history(
            run.conversation_id, corp_id=corp_id
        )
        message = _attachment_message(
            run.question,
            attachments,
            conversation_id=run.conversation_id,
            corp_id=corp_id,
            workspace=self.workspace,
        )
        agent_input = {"messages": [*history, {"role": "user", "content": message}]}
        before: dict[str, FileStamp] = {}
        baseline = self.workspace.user_data_root(corp_id) / "baselines" / run_id
        baseline_ready = False
        final_status = RunStatus.FAILED
        final_text = ""
        error: str | None = None
        try:
            before, baseline = await asyncio.to_thread(
                self.workspace.stage_baseline, corp_id, run_id
            )
            baseline_ready = True
            self.store.add_event(
                run_id,
                "run_status",
                "started",
                "General Agent is working",
                data={"status": RunStatus.RUNNING},
                corp_id=corp_id,
            )
            async with self.backend.run_scope(
                run_id, corp_id, run.conversation_id
            ):
                async with asyncio.timeout(self.settings.run_timeout_seconds):
                    output = await self._consume_stream(
                        run_id, corp_id, agent_input
                    )
            final_text = _final_text(output)
            final_status = RunStatus.COMPLETED
        except asyncio.CancelledError:
            final_status = RunStatus.STOPPED
            error = "The run was stopped by the user."
        except TimeoutError:
            await self.backend.cancel_run(run_id)
            final_status = RunStatus.FAILED
            error = f"The run exceeded {self.settings.run_timeout_seconds} seconds."
        except Exception as exc:
            final_status = RunStatus.FAILED
            error = self._redact(str(exc)) or type(exc).__name__
        finally:
            stream = self._streams.pop(run_id, None)
            if stream is not None:
                with contextlib.suppress(Exception):
                    await stream.abort()
            await self.backend.cancel_run(run_id)
            try:
                await asyncio.to_thread(
                    self.workspace.cleanup_temporary, corp_id, run.conversation_id
                )
                artifacts = (
                    await asyncio.to_thread(
                        self.workspace.snapshot_changes,
                        corp_id=corp_id,
                        run_id=run_id,
                        conversation_id=run.conversation_id,
                        before=before,
                        baseline=baseline,
                    )
                    if baseline_ready
                    else []
                )
                for artifact, snapshot_path in artifacts:
                    self.store.add_artifact(
                        artifact, snapshot_path, corp_id=corp_id
                    )
                    self.store.add_event(
                        run_id,
                        "artifact_changed",
                        "completed",
                        f"{artifact.change_type.capitalize()} file · {artifact.relative_path}",
                        data=artifact.model_dump(mode="json"),
                        corp_id=corp_id,
                    )
            except Exception as snapshot_error:
                if error is None:
                    error = f"Artifact snapshot failed: {self._redact(str(snapshot_error))}"
                    final_status = RunStatus.FAILED
            self.store.finish_run(
                run_id,
                final_status,
                assistant_text=final_text,
                error=error,
                corp_id=corp_id,
            )
            self.store.add_event(
                run_id,
                "run_status",
                "completed" if final_status == RunStatus.COMPLETED else "failed",
                {
                    RunStatus.COMPLETED: "Run completed",
                    RunStatus.STOPPED: "Run stopped",
                    RunStatus.FAILED: "Run failed",
                }[final_status],
                data={"status": final_status, "error": error},
                corp_id=corp_id,
            )

    async def _consume_stream(
        self, run_id: str, corp_id: str, agent_input: dict[str, Any]
    ) -> Any:
        usage_callback = RunUsageCallback(self.store, run_id, corp_id)
        stream = await self.graph.astream_events(
            agent_input,
            config={
                "configurable": {"thread_id": f"{corp_id}:{run_id}"},
                "callbacks": [usage_callback],
            },
            version="v3",
        )
        self._streams[run_id] = stream
        tool_started: dict[str, tuple[float, str, str]] = {}
        last_todos: dict[str, str] = {}
        try:
            async for event in stream:
                method = event.get("method")
                params = event.get("params") or {}
                namespace = params.get("namespace") or []
                data = params.get("data")
                if method == "tools" and isinstance(data, Mapping):
                    self._handle_tool_event(
                        run_id, corp_id, data, namespace, tool_started
                    )
                elif method == "lifecycle" and isinstance(data, Mapping):
                    self._handle_lifecycle(run_id, corp_id, data)
                elif method == "values" and isinstance(data, Mapping):
                    agent = _agent_from_namespace(namespace)
                    todos = data.get("todos")
                    todo_key = json.dumps(
                        _jsonable(todos), sort_keys=True, default=str
                    )
                    if todos and last_todos.get(agent) != todo_key:
                        last_todos[agent] = todo_key
                        self.store.add_event(
                            run_id,
                            "plan_updated",
                            "updated",
                            "Plan updated",
                            agent=agent,
                            data={"todos": _jsonable(todos)},
                            corp_id=corp_id,
                        )
                if usage_callback.reported_tokens > self.settings.max_run_tokens:
                    raise TokenBudgetExceeded(
                        "The run exceeded the configured provider-reported "
                        f"token limit of {self.settings.max_run_tokens:,}."
                    )
        finally:
            usage_callback.finalize_incomplete()
        return await stream.output()

    def _handle_tool_event(
        self,
        run_id: str,
        corp_id: str,
        data: Mapping[str, Any],
        namespace: list[str],
        started: dict[str, tuple[float, str, str]],
    ) -> None:
        lifecycle = str(data.get("event") or "")
        tool_name = str(data.get("tool_name") or "unknown")
        call_id = str(data.get("tool_call_id") or f"{tool_name}-{len(started)+1}")
        agent = _agent_from_namespace(namespace)
        if lifecycle == "tool-started":
            started[call_id] = (time.monotonic(), tool_name, agent)
            self.store.increment_tool_calls(run_id, corp_id=corp_id)
            tool_input = self._redact_value(data.get("input"))
            label = "Executing command" if tool_name == "execute" else f"Using tool · {tool_name}"
            self.store.add_event(
                run_id,
                "tool_started",
                "started",
                label,
                agent=agent,
                data={"call_id": call_id, "tool_name": tool_name, "input": tool_input},
                corp_id=corp_id,
            )
        elif lifecycle in {"tool-finished", "tool-error"}:
            started_at, recorded_name, recorded_agent = started.pop(
                call_id, (time.monotonic(), tool_name, agent)
            )
            failed = lifecycle == "tool-error"
            output = data.get("error") if failed else data.get("output")
            safe_output = self._redact_value(output)
            if recorded_name == "execute":
                safe_output = _normalize_execute_output(safe_output)
            self.store.add_event(
                run_id,
                "tool_finished",
                "failed" if failed else "completed",
                f"{'Failed' if failed else 'Completed'} tool · {recorded_name}",
                agent=recorded_agent,
                data={
                    "call_id": call_id,
                    "tool_name": recorded_name,
                    "output": safe_output,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
                corp_id=corp_id,
            )

    def _handle_lifecycle(
        self, run_id: str, corp_id: str, data: Mapping[str, Any]
    ) -> None:
        graph_name = str(data.get("graph_name") or _agent_from_namespace(data.get("namespace") or []))
        if graph_name in {"general-agent", "model", "tools"}:
            return
        lifecycle = str(data.get("event") or "")
        if lifecycle == "started":
            self.store.add_event(
                run_id,
                "subagent_started",
                "started",
                f"Delegated to {graph_name}",
                agent=graph_name,
                data={"graph_name": graph_name, "trigger_call_id": data.get("trigger_call_id")},
                corp_id=corp_id,
            )
        elif lifecycle in {"completed", "failed", "interrupted", "drained"}:
            self.store.add_event(
                run_id,
                "subagent_finished",
                "completed" if lifecycle == "completed" else "failed",
                f"Subagent {lifecycle} · {graph_name}",
                agent=graph_name,
                data={"graph_name": graph_name, "status": lifecycle, "error": self._redact(str(data.get("error") or "")) or None},
                corp_id=corp_id,
            )

    def _redact(self, text: str) -> str:
        result = text
        for secret in self._secret_values:
            result = result.replace(secret, "[REDACTED]")
        if len(result) <= self.settings.max_event_output_chars:
            return result
        omitted = len(result) - self.settings.max_event_output_chars
        return (
            result[: self.settings.max_event_output_chars]
            + f"\n[Stored event preview truncated; {omitted:,} characters omitted.]"
        )

    def _redact_value(self, value: Any) -> Any:
        serialized = json.dumps(_jsonable(value), ensure_ascii=False, default=str)
        redacted = self._redact(serialized)
        if len(redacted) < len(serialized):
            return redacted
        try:
            return json.loads(redacted)
        except json.JSONDecodeError:
            return redacted


def _attachment_message(
    question: str,
    attachments: list[Attachment],
    *,
    conversation_id: str,
    corp_id: str,
    workspace: Workspace,
) -> str:
    lines = [
        question or "Work with the attached files.",
        "",
        "Workspace context:",
        f"- Current chat ID: {conversation_id}",
        "- `/` is this chat's isolated working directory.",
        "- `/shared` contains files intentionally retained across chats.",
        "- Create ordinary outputs under `/`; use `/shared` only when the user asks to retain them across chats.",
    ]
    if not attachments:
        return "\n".join(lines)
    lines.extend(["", "Attached workspace files:"])
    for item in attachments:
        physical = (
            workspace.user_root(corp_id) / item.relative_path
        ).relative_to(workspace.root).as_posix()
        virtual_path = agent_virtual_path(
            physical, conversation_id=conversation_id, corp_id=corp_id
        )
        shell_path = virtual_path.lstrip("/")
        lines.append(
            f"- {virtual_path} (original name: {item.original_name}; "
            f"shell path: {shell_path}; type: {item.content_type or 'unknown'}; "
            f"bytes: {item.size_bytes})"
        )
    lines.append("Inspect only the portions needed for this request.")
    return "\n".join(lines)


def _final_text(output: Any) -> str:
    if not isinstance(output, Mapping):
        return str(output or "")
    for message in reversed(output.get("messages") or []):
        if isinstance(message, AIMessage):
            try:
                return message.text
            except AttributeError:
                return _message_text(message)
    return ""


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _agent_from_namespace(namespace: Any) -> str:
    if not namespace:
        return "general-agent"
    segment = str(namespace[-1])
    name = segment.split(":", 1)[0]
    return name or "general-agent"


def _agent_from_model_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return "general-agent"
    value = metadata.get("lc_agent_name")
    return str(value) if isinstance(value, str) and value else "general-agent"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def _secret_values() -> tuple[str, ...]:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    values = {
        value
        for key, value in os.environ.items()
        if any(marker in key.upper() for marker in markers) and len(value) >= 7
    }
    return tuple(sorted(values, key=len, reverse=True))


_EXIT_STATUS = re.compile(r"\[Command (?:succeeded|failed) with exit code (-?\d+)\]")


def _normalize_execute_output(value: Any) -> dict[str, Any]:
    """Project DeepAgents' formatted command result into stable UI fields."""

    if isinstance(value, Mapping) and {
        "output",
        "exit_code",
    }.intersection(value):
        return {
            "output": str(value.get("output") or ""),
            "exit_code": value.get("exit_code"),
            "truncated": bool(value.get("truncated")),
        }
    content: Any = value
    if isinstance(value, Mapping):
        content = value.get("content", value)
    if isinstance(content, list):
        text_parts = [
            str(block.get("text") or "")
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text"
        ]
        content = "".join(text_parts)
    text = str(content or "")
    match = _EXIT_STATUS.search(text)
    return {
        "output": text,
        "exit_code": int(match.group(1)) if match else None,
        "truncated": "[Output was truncated" in text
        or "[Output exceeded the capture size limit" in text,
    }
