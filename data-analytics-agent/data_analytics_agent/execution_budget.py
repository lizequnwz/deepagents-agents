"""Execution-budget middleware construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware import hook_config
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage, HumanMessage


def execution_budget_middleware(
    *,
    model_calls: int,
    tool_calls: int,
    specific_tool_calls: Mapping[str, int] | None = None,
    runs=None,
    coordinator: bool = False,
) -> list[Any]:
    """Build strict lifecycle limits for one agent graph."""

    middleware: list[Any] = (
        [
            _PresentationModelLimit(
                runs=runs,
                coordinator=coordinator,
                thread_limit=model_calls,
                exit_behavior="error",
            ),
            _PresentationToolLimit(
                runs=runs,
                coordinator=coordinator,
                thread_limit=tool_calls,
                exit_behavior="continue",
            ),
        ]
        if runs is not None
        else [
            ModelCallLimitMiddleware(thread_limit=model_calls, exit_behavior="error"),
            ToolCallLimitMiddleware(thread_limit=tool_calls, exit_behavior="error"),
        ]
    )
    for tool_name, limit in (specific_tool_calls or {}).items():
        middleware.append(
            ToolCallLimitMiddleware(
                tool_name=tool_name,
                thread_limit=limit,
                exit_behavior="error",
            )
        )
    return middleware


_PARTIAL_INSTRUCTION = (
    "The analysis call budget has ended. Do not retrieve or compute more data or "
    "delegate new work. Inspect committed evidence, publish supported partial "
    "findings with unresolved questions, and create their HTML report."
)


class _PresentationModelLimit(ModelCallLimitMiddleware):
    """Retain native counters while reserving bounded coordinator synthesis."""

    def __init__(self, *, runs, coordinator, **kwargs):
        super().__init__(**kwargs)
        self.runs, self.coordinator = runs, coordinator

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        run_id = state["run_id"]
        phase = bool(
            self.runs.analysis_exhausted_reason(run_id)
            or self.runs.get(run_id).findings
        )
        if not phase:
            try:
                return super().before_model(state, runtime)
            except ModelCallLimitExceededError:
                self.runs.exhaust_analysis(
                    run_id, "The model-call analysis limit ended before completion."
                )
        if not self.coordinator:
            return {
                "jump_to": "end",
                "messages": [AIMessage(content=_PARTIAL_INSTRUCTION)],
            }
        if not self.runs.reserve_presentation_calls(run_id, "model", 1, 8):
            raise RuntimeError(
                "Presentation model-call reserve exhausted. Saved evidence remains available."
            )
        return (
            {"messages": [HumanMessage(content=_PARTIAL_INSTRUCTION)]}
            if not self.runs.get(run_id).findings
            else None
        )

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)


class _PresentationToolLimit(ToolCallLimitMiddleware):
    """Native tool-message accounting; analysis tools also enforce the durable stop."""

    def __init__(self, *, runs, coordinator, **kwargs):
        super().__init__(**kwargs)
        self.runs, self.coordinator = runs, coordinator

    def after_model(self, state, runtime):
        run_id = state["run_id"]
        if (
            self.runs.analysis_exhausted_reason(run_id)
            or self.runs.get(run_id).findings
        ):
            message = next(
                (
                    m
                    for m in reversed(state.get("messages", []))
                    if isinstance(m, AIMessage)
                ),
                None,
            )
            calls = len(message.tool_calls) if message else 0
            allowed = (
                self.runs.reserve_presentation_calls(run_id, "tool", calls, 16)
                if self.coordinator
                else 0
            )
            count = state.get("thread_tool_call_count", {}).get("__all__", 0)
            limiter = ToolCallLimitMiddleware(
                thread_limit=count + allowed, exit_behavior="continue"
            )
            return limiter.after_model(state, runtime)
        update = super().after_model(state, runtime)
        if update and update.get("messages"):
            self.runs.exhaust_analysis(
                run_id, "The tool-call analysis limit ended before completion."
            )
        return update

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)
