"""Bounded native subagent calls with isolated analytical execution ownership."""

import asyncio
from dataclasses import replace
from threading import BoundedSemaphore

from langchain.agents.middleware import AgentMiddleware
from langgraph.types import Command
from langchain_core.messages import AIMessage, ToolMessage


class DelegationMiddleware(AgentMiddleware):
    """Use the framework's task/checkpoint machinery; limit concurrent assignments."""

    def __init__(self, runs, parallel_analyses):
        self.runs = runs
        self.analysis_slots = BoundedSemaphore(parallel_analyses)
        self.source_slot = BoundedSemaphore(1)

    def _slot(self, request):
        if request.tool_call["name"] != "task":
            return None
        specialist = request.tool_call["args"].get("subagent_type")
        return (
            self.analysis_slots if specialist == "data-analysis" else self.source_slot
        )

    @staticmethod
    def _missing_parallel_plan(request):
        if request.tool_call["name"] != "task" or request.state.get("todos"):
            return None
        message = next(
            (
                m
                for m in reversed(request.state.get("messages", []))
                if isinstance(m, AIMessage)
            ),
            None,
        )
        assignments = (
            [c for c in message.tool_calls if c["name"] == "task"] if message else []
        )
        if len(assignments) > 1:
            return ToolMessage(
                content="Before dispatching parallel assignments, use write_todos to show a concise analysis plan. Then dispatch these independent assignments together.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return None

    @staticmethod
    def _result(result):
        if isinstance(result, Command) and isinstance(result.update, dict):
            # The coordinator owns these fields. Native tasks otherwise echo them
            # back, producing conflicting writes when two assignments complete.
            result = replace(
                result,
                update={
                    k: v
                    for k, v in result.update.items()
                    if k not in {"thread_id", "run_id", "source_id", "question"}
                },
            )
        return result

    def wrap_tool_call(self, request, handler):
        if reminder := self._missing_parallel_plan(request):
            return reminder
        slot = self._slot(request)
        if slot is None:
            return handler(request)
        with slot:
            if self.runs.cancel_event(request.state["run_id"]).is_set():
                raise InterruptedError("Run stopped before assignment.")
            return self._result(handler(request))

    async def awrap_tool_call(self, request, handler):
        if reminder := self._missing_parallel_plan(request):
            return reminder
        slot = self._slot(request)
        if slot is None:
            return await handler(request)
        # Nonblocking acquisition is cancellation-safe: no background acquire can
        # take a slot after the awaiting task has already been cancelled.
        while not slot.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            if self.runs.cancel_event(request.state["run_id"]).is_set():
                raise InterruptedError("Run stopped before assignment.")
            return self._result(await handler(request))
        finally:
            slot.release()
