"""Persistent background-run lifecycle over DeepAgents v3 event streaming."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Mapping
from typing import Any, BinaryIO

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.config import Settings
from general_agent.observability import log_event
from general_agent.schemas import Attachment, RunStatus
from general_agent.store import Store
from general_agent.workspace import Workspace

logger = logging.getLogger("general_agent.run_manager")


class TokenBudgetExceeded(RuntimeError):
    """Raised after provider-reported usage crosses the configured run ceiling."""


class RunUsageCallback(BaseCallbackHandler):
    """Record only model calls that actually execute during the current run."""

    def __init__(self, store: Store, run_id: str, corp_id: str) -> None:
        super().__init__()
        self.store = store
        self.run_id = run_id
        self.corp_id = corp_id
        self.active: dict[str, tuple[str, float]] = {}
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
        call_id = str(run_id)
        agent = _agent_from_model_metadata(metadata)
        self.active[call_id] = (agent, time.monotonic())
        log_event(
            logger,
            logging.INFO,
            "agent.model.started",
            run_id=self.run_id,
            corp_id=self.corp_id,
            model_call_id=call_id,
            agent=agent,
        )

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
        self._finish(str(run_id), usage, status="completed")

    def on_llm_error(
        self, error: BaseException, *, run_id: Any, **kwargs: Any
    ) -> None:
        del kwargs
        self._finish(
            str(run_id),
            None,
            status="failed",
            error_type=type(error).__name__,
        )

    def finalize_incomplete(self) -> None:
        for call_id in list(self.active):
            self._finish(call_id, None, status="incomplete")

    def _finish(
        self,
        call_id: str,
        usage: Mapping[str, Any] | None,
        *,
        status: str,
        error_type: str | None = None,
    ) -> None:
        active = self.active.pop(call_id, ("advisor-match-agent", time.monotonic()))
        agent, started_at = active
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
        event = {
            "completed": "agent.model.completed",
            "failed": "agent.model.failed",
            "incomplete": "agent.model.incomplete",
        }[status]
        level = {
            "completed": logging.INFO,
            "failed": logging.ERROR,
            "incomplete": logging.WARNING,
        }[status]
        log_event(
            logger,
            level,
            event,
            run_id=self.run_id,
            corp_id=self.corp_id,
            model_call_id=call_id,
            agent=agent,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            input_tokens=_usage_int(usage, "input_tokens"),
            output_tokens=_usage_int(usage, "output_tokens"),
            total_tokens=_usage_int(usage, "total_tokens"),
            error_type=error_type,
        )


class RunManager:
    """Start, stream, stop, and finalize one trusted local run at a time."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        workspace: Workspace,
        backend: AdvisorWorkspaceBackend,
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
        log_event(
            logger,
            logging.INFO,
            "agent.run.created",
            run_id=run_id,
            conversation_id=conversation_id,
            corp_id=corp_id,
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
        log_event(
            logger,
            logging.INFO,
            "api.upload.accepted",
            run_id=run_id,
            conversation_id=conversation_id,
            corp_id=corp_id,
            attachment_id=attachment.attachment_id,
            size_bytes=attachment.size_bytes,
        )
        return attachment

    def start(
        self, run_id: str, corp_id: str, attachments: list[Attachment]
    ) -> None:
        self._run_corps[run_id] = corp_id
        log_event(
            logger,
            logging.INFO,
            "agent.run.scheduled",
            run_id=run_id,
            corp_id=corp_id,
            attachments=len(attachments),
        )
        task = asyncio.create_task(
            self._drive(run_id, corp_id, attachments),
            name=f"advisor-match-agent-{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._forget_run(run_id))

    def _forget_run(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._run_corps.pop(run_id, None)

    @property
    def active_run_count(self) -> int:
        return len(self._tasks)

    async def stop(self, run_id: str, corp_id: str) -> bool:
        if not self.store.request_stop(run_id, corp_id=corp_id):
            log_event(
                logger,
                logging.WARNING,
                "agent.run.stop_ignored",
                run_id=run_id,
                corp_id=corp_id,
            )
            return False
        log_event(
            logger,
            logging.INFO,
            "agent.run.stop_requested",
            run_id=run_id,
            corp_id=corp_id,
        )
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
        log_event(
            logger,
            logging.INFO,
            "agent.manager.shutdown_started",
            active_runs=len(run_ids),
        )
        await asyncio.gather(
            *(
                self.stop(run_id, self._run_corps[run_id])
                for run_id in run_ids
                if run_id in self._run_corps
            ),
            return_exceptions=True,
        )
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        log_event(
            logger,
            logging.INFO,
            "agent.manager.shutdown_completed",
            active_runs=0,
        )

    async def _drive(
        self, run_id: str, corp_id: str, attachments: list[Attachment]
    ) -> None:
        started_at = time.monotonic()
        run = self.store.get_run(run_id, corp_id=corp_id)
        history = self.store.completed_history(
            run.conversation_id, corp_id=corp_id
        )
        message = _attachment_message(
            run.question,
            attachments,
        )
        agent_input = {"messages": [*history, {"role": "user", "content": message}]}
        final_status = RunStatus.FAILED
        final_text = ""
        error: str | None = None
        try:
            log_event(
                logger,
                logging.INFO,
                "agent.run.started",
                run_id=run_id,
                conversation_id=run.conversation_id,
                corp_id=corp_id,
                attachments=len(attachments),
            )
            self.store.add_event(
                run_id,
                "run_status",
                "started",
                "Advisor Match Agent is working",
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
            log_event(
                logger,
                logging.INFO,
                "agent.run.cancelled",
                run_id=run_id,
                corp_id=corp_id,
            )
        except TimeoutError:
            await self.backend.cancel_run(run_id)
            final_status = RunStatus.FAILED
            error = f"The run exceeded {self.settings.run_timeout_seconds} seconds."
            log_event(
                logger,
                logging.ERROR,
                "agent.run.timed_out",
                run_id=run_id,
                corp_id=corp_id,
                timeout_seconds=self.settings.run_timeout_seconds,
            )
        except Exception as exc:
            final_status = RunStatus.FAILED
            error = self._redact(str(exc)) or type(exc).__name__
            log_event(
                logger,
                logging.ERROR,
                "agent.run.failed",
                run_id=run_id,
                corp_id=corp_id,
                exception_type=type(exc).__name__,
                exc_info=True,
            )
        finally:
            stream = self._streams.pop(run_id, None)
            if stream is not None:
                if final_status != RunStatus.COMPLETED:
                    log_event(
                        logger,
                        logging.WARNING,
                        "agent.stream.aborted",
                        run_id=run_id,
                        corp_id=corp_id,
                        status=final_status,
                    )
                with contextlib.suppress(Exception):
                    await stream.abort()
            await self.backend.cancel_run(run_id)
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
            log_event(
                logger,
                logging.INFO if final_status == RunStatus.COMPLETED else logging.WARNING,
                "agent.run.finished",
                run_id=run_id,
                conversation_id=run.conversation_id,
                corp_id=corp_id,
                status=final_status,
                duration_ms=int((time.monotonic() - started_at) * 1000),
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
        log_event(
            logger,
            logging.INFO,
            "agent.stream.opened",
            run_id=run_id,
            corp_id=corp_id,
            version="v3",
        )
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
                        log_event(
                            logger,
                            logging.DEBUG,
                            "agent.plan.updated",
                            run_id=run_id,
                            corp_id=corp_id,
                            agent=agent,
                            items=len(todos) if isinstance(todos, list) else 1,
                        )
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
                    log_event(
                        logger,
                        logging.ERROR,
                        "agent.token_budget.exceeded",
                        run_id=run_id,
                        corp_id=corp_id,
                        reported_tokens=usage_callback.reported_tokens,
                        max_tokens=self.settings.max_run_tokens,
                    )
                    raise TokenBudgetExceeded(
                        "The run exceeded the configured provider-reported "
                        f"token limit of {self.settings.max_run_tokens:,}."
                    )
        finally:
            usage_callback.finalize_incomplete()
        output = await stream.output()
        log_event(
            logger,
            logging.INFO,
            "agent.stream.completed",
            run_id=run_id,
            corp_id=corp_id,
        )
        return output

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
            label = f"Using tool · {tool_name}"
            self.store.add_event(
                run_id,
                "tool_started",
                "started",
                label,
                agent=agent,
                data={"call_id": call_id, "tool_name": tool_name, "input": tool_input},
                corp_id=corp_id,
            )
            log_event(
                logger,
                logging.INFO,
                "agent.tool.started",
                run_id=run_id,
                corp_id=corp_id,
                agent=agent,
                tool=tool_name,
                tool_call_id=call_id,
            )
        elif lifecycle in {"tool-finished", "tool-error"}:
            started_at, recorded_name, recorded_agent = started.pop(
                call_id, (time.monotonic(), tool_name, agent)
            )
            failed = lifecycle == "tool-error"
            output = data.get("error") if failed else data.get("output")
            safe_output = self._redact_value(output)
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
            log_event(
                logger,
                logging.ERROR if failed else logging.INFO,
                "agent.tool.failed" if failed else "agent.tool.completed",
                run_id=run_id,
                corp_id=corp_id,
                agent=recorded_agent,
                tool=recorded_name,
                tool_call_id=call_id,
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )

    def _handle_lifecycle(
        self, run_id: str, corp_id: str, data: Mapping[str, Any]
    ) -> None:
        graph_name = str(data.get("graph_name") or _agent_from_namespace(data.get("namespace") or []))
        if graph_name in {"advisor-match-agent", "model", "tools"}:
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
            log_event(
                logger,
                logging.INFO,
                "agent.subgraph.started",
                run_id=run_id,
                corp_id=corp_id,
                graph=graph_name,
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
            log_event(
                logger,
                logging.INFO if lifecycle == "completed" else logging.WARNING,
                "agent.subgraph.finished",
                run_id=run_id,
                corp_id=corp_id,
                graph=graph_name,
                status=lifecycle,
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
) -> str:
    lines = [
        question or "Match the advisors in the attached file.",
        "",
        "Advisor match context:",
        "- Use only typed advisor tools to inspect the upload, match rows, review decisions, and generate the export.",
    ]
    if not attachments:
        return "\n".join(lines)
    lines.extend(["", "Attached advisor file:"])
    for item in attachments:
        lines.append(
            f"- Attachment ID: {item.attachment_id} (original name: {item.original_name}; "
            f"type: {item.content_type or 'unknown'}; bytes: {item.size_bytes})"
        )
    lines.append("Profile only bounded samples; never use generic filesystem tools on the upload.")
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
        return "advisor-match-agent"
    segment = str(namespace[-1])
    name = segment.split(":", 1)[0]
    return name or "advisor-match-agent"


def _agent_from_model_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return "advisor-match-agent"
    value = metadata.get("lc_agent_name")
    return str(value) if isinstance(value, str) and value else "advisor-match-agent"


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


def _usage_int(usage: Mapping[str, Any] | None, key: str) -> int | None:
    if not usage:
        return None
    value = usage.get(key)
    return int(value) if isinstance(value, int) else None


def _secret_values() -> tuple[str, ...]:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    values = {
        value
        for key, value in os.environ.items()
        if any(marker in key.upper() for marker in markers) and len(value) >= 7
    }
    return tuple(sorted(values, key=len, reverse=True))
