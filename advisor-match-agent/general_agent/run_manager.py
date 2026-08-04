"""Background lifecycle for the explicit Advisor Match LangGraph."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any, BinaryIO

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.types import Command

from general_agent.advisor_repository import AdvisorRepository
from general_agent.config import Settings
from general_agent.observability import log_event
from general_agent.runtime_store import RuntimeStore
from general_agent.schemas import Attachment, RunStatus
from general_agent.workspace import Workspace

logger = logging.getLogger("general_agent.run_manager")

_NODE_LABELS = {
    "route": "Understanding your request",
    "inspect": "Reading the uploaded file",
    "map_input": "Identifying advisor columns",
    "resolve_mapping": "Applying your column clarification",
    "validate": "Validating advisor rows",
    "remap_firm": "Updating the firm-column mapping",
    "match": "Comparing advisors with the master database",
    "clarify": "Waiting for your clarification",
    "review": "Preparing advisor review details",
    "propose_crd": "Checking the requested CRD",
    "confirm_manual": "Applying the confirmed manual match",
    "cancel_manual": "Cancelling the proposed manual match",
    "approve": "Approving the matching results",
    "status": "Checking matching status",
    "reset": "Resetting the matching workflow",
    "greeting": "Preparing guidance",
    "capabilities": "Preparing guidance",
    "unsupported": "Preparing guidance",
}


class RuntimeUsageCallback(BaseCallbackHandler):
    """Capture provider usage in memory without enforcing a token budget."""

    def __init__(self, runtime: RuntimeStore, run_id: str, corp_id: str) -> None:
        super().__init__()
        self.runtime = runtime
        self.run_id = run_id
        self.corp_id = corp_id

    def on_llm_end(self, response: LLMResult, **_kwargs: Any) -> None:
        usage: Mapping[str, Any] | None = None
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            generation = None
        if isinstance(generation, ChatGeneration) and isinstance(
            generation.message, AIMessage
        ):
            usage = generation.message.usage_metadata
            if not usage:
                usage = _response_usage(generation.message.response_metadata)
        if not usage:
            usage = _response_usage(response.llm_output)
        self.runtime.record_model_call(
            self.run_id, usage, corp_id=self.corp_id
        )

    def on_llm_error(self, _error: BaseException, **_kwargs: Any) -> None:
        self.runtime.record_model_call(
            self.run_id, None, corp_id=self.corp_id
        )


class RunManager:
    """Run one graph task per conversation; different conversations may overlap."""

    def __init__(
        self,
        *,
        settings: Settings,
        runtime: RuntimeStore,
        repository: AdvisorRepository,
        workspace: Workspace,
        graph: Any,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.repository = repository
        self.workspace = workspace
        self.graph = graph
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._run_corps: dict[str, str] = {}

    @property
    def active_run_count(self) -> int:
        return len(self._tasks)

    def create_run(self, corp_id: str, conversation_id: str, question: str) -> str:
        run_id, _ = self.runtime.create_run(
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
        self.repository.add_attachment(
            corp_id=corp_id,
            conversation_id=conversation_id,
            run_id=run_id,
            attachment=attachment,
            protected_path=protected,
        )
        self.runtime.add_attachment(run_id, attachment, corp_id=corp_id)
        return attachment

    def start(self, run_id: str, corp_id: str, attachments: list[Attachment]) -> None:
        self._run_corps[run_id] = corp_id
        task = asyncio.create_task(
            self._drive(run_id, corp_id, attachments),
            name=f"advisor-match-graph-{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._forget(run_id))

    async def stop(self, run_id: str, corp_id: str) -> bool:
        if not self.runtime.request_stop(run_id, corp_id=corp_id):
            return False
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _forget(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._run_corps.pop(run_id, None)

    async def _drive(
        self, run_id: str, corp_id: str, attachments: list[Attachment]
    ) -> None:
        run = self.runtime.get_run(run_id, corp_id=corp_id)
        thread_id = f"{corp_id}:{run.conversation_id}"
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [RuntimeUsageCallback(self.runtime, run_id, corp_id)],
        }
        started = time.monotonic()
        final_status = RunStatus.FAILED
        final_text = ""
        error: str | None = None
        try:
            self.runtime.add_event(
                run_id,
                "run_status",
                "started",
                "Advisor Match Agent is working",
                data={"status": RunStatus.RUNNING},
                corp_id=corp_id,
            )
            if attachments:
                await self._delete_thread(thread_id)
                graph_input: Any = {
                    "corp_id": corp_id,
                    "conversation_id": run.conversation_id,
                    "run_id": run_id,
                    "user_message": run.question,
                    "attachment_id": attachments[0].attachment_id,
                    "is_new_attachment": True,
                    "phase": "idle",
                    "response": "",
                    "error": None,
                }
            elif await self._has_interrupt(config):
                graph_input = Command(
                    resume={"message": run.question, "run_id": run_id}
                )
            else:
                graph_input = {
                    "corp_id": corp_id,
                    "conversation_id": run.conversation_id,
                    "run_id": run_id,
                    "user_message": run.question,
                    "is_new_attachment": False,
                    "response": "",
                    "error": None,
                }
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                final_text = await self._consume(run_id, corp_id, graph_input, config)
            final_status = RunStatus.COMPLETED
        except asyncio.CancelledError:
            final_status = RunStatus.STOPPED
            error = "The run was stopped by the user."
        except TimeoutError:
            error = "The run exceeded the configured time limit."
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            log_event(
                logger,
                logging.ERROR,
                "graph.run.failed",
                run_id=run_id,
                corp_id=corp_id,
                exception_type=type(exc).__name__,
                exc_info=True,
            )
        finally:
            self.runtime.finish_run(
                run_id,
                final_status,
                assistant_text=final_text,
                error=error,
                corp_id=corp_id,
            )
            self.runtime.add_event(
                run_id,
                "run_status",
                "completed" if final_status == RunStatus.COMPLETED else "failed",
                {
                    RunStatus.COMPLETED: "Run completed",
                    RunStatus.STOPPED: "Run stopped",
                    RunStatus.FAILED: "Run failed",
                }[final_status],
                data={
                    "status": final_status,
                    "error": error,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
                corp_id=corp_id,
            )

    async def _consume(
        self,
        run_id: str,
        corp_id: str,
        graph_input: Any,
        config: dict[str, Any],
    ) -> str:
        response = ""
        async for update in self.graph.astream(
            graph_input, config=config, stream_mode=["tasks", "updates"]
        ):
            mode = "updates"
            if isinstance(update, tuple) and len(update) == 2:
                mode, update = update
            if not isinstance(update, Mapping):
                continue
            if mode == "tasks":
                node_name = str(update.get("name") or "graph node")
                finished = "result" in update or "error" in update
                failed = update.get("error") is not None
                self.runtime.add_event(
                    run_id,
                    "node_failed"
                    if failed
                    else ("node_completed" if finished else "node_started"),
                    "failed" if failed else ("completed" if finished else "started"),
                    _node_label(node_name),
                    data={
                        "node": node_name,
                        "error_type": type(update["error"]).__name__ if failed else None,
                    },
                    corp_id=corp_id,
                )
                continue
            for node, value in update.items():
                if node == "__interrupt__":
                    payload = _interrupt_payload(value)
                    response = str(payload.get("question") or "Clarification is required.")
                    self.runtime.add_event(
                        run_id,
                        "clarification_required",
                        "completed",
                        response,
                        data=payload,
                        corp_id=corp_id,
                    )
                    continue
                if isinstance(value, Mapping) and value.get("response"):
                    response = str(value["response"])
                if isinstance(value, Mapping):
                    result = value.get("result")
                    if isinstance(result, Mapping) and result.get("output_artifact_id"):
                        self.runtime.add_event(
                            run_id,
                            "artifact_published",
                            "completed",
                            "Published advisor match workbook",
                            data={
                                "artifact_id": result["output_artifact_id"],
                                "match_session_id": result.get("match_session_id"),
                            },
                            corp_id=corp_id,
                        )
                    if (
                        isinstance(result, Mapping)
                        and result.get("workflow_status") == "match_created"
                        and isinstance(result.get("counts"), Mapping)
                    ):
                        counts = result["counts"]
                        unresolved = int(counts.get("ambiguous_match") or 0) + int(
                            counts.get("no_match") or 0
                        )
                        if unresolved:
                            self.runtime.add_event(
                                run_id,
                                "review_required",
                                "completed",
                                f"{unresolved} advisor row(s) require review",
                                data={"counts": dict(counts)},
                                corp_id=corp_id,
                            )
        return response

    async def _has_interrupt(self, config: dict[str, Any]) -> bool:
        snapshot = await self.graph.aget_state(config)
        return any(getattr(task, "interrupts", ()) for task in snapshot.tasks)

    async def _delete_thread(self, thread_id: str) -> None:
        checkpointer = getattr(self.graph, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(thread_id)


def _interrupt_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)) and value:
        item = value[0]
        payload = getattr(item, "value", item)
        return dict(payload) if isinstance(payload, Mapping) else {"question": str(payload)}
    return {"question": "Clarification is required."}


def _node_label(node_name: str) -> str:
    return _NODE_LABELS.get(node_name, node_name.replace("_", " ").title())


def _response_usage(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    candidate = value.get("token_usage") or value.get("usage") or value
    if not isinstance(candidate, Mapping):
        return None
    if all(key in candidate for key in ("input_tokens", "output_tokens", "total_tokens")):
        return candidate
    if all(key in candidate for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
        return {
            "input_tokens": candidate["prompt_tokens"],
            "output_tokens": candidate["completion_tokens"],
            "total_tokens": candidate["total_tokens"],
        }
    return None
