"""Run-wide admission limits shared by the agent and all delegated work."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class RunBudgetExceeded(RuntimeError):
    """An invocation was denied before its model or tool could execute."""


class RunBudget:
    """Count admitted logical invocations, including failed invocations.

    Reservations are shared across threads and async tasks. A denied admission
    makes exhaustion sticky so an exception swallowed by a tool or by the
    summarizer cannot permit more work or a successful run finalization.

    These are invocation limits, not token estimates. Provider-reported tokens
    remain a separate limit; missing usage is never inferred from call counts.
    Provider-internal HTTP retries do not start new logical invocations.
    """

    def __init__(
        self,
        *,
        max_model_calls: int,
        max_tool_calls: int,
        max_task_calls: int,
    ) -> None:
        limits = {
            "model": max_model_calls,
            "tool": max_tool_calls,
            "task": max_task_calls,
        }
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ValueError("Run call limits must be positive integers.")
        self._limits = limits
        self._counts = dict.fromkeys(limits, 0)
        self._lock = threading.Lock()
        self._exhaustion: str | None = None

    def reserve_model_call(self) -> None:
        """Admit one model invocation, including auxiliary summarization."""

        self._reserve(("model",))

    def reserve_tool_call(self, tool_name: str) -> None:
        """Admit a tool invocation and atomically reserve delegation if needed."""

        self._reserve(("tool", "task") if tool_name == "task" else ("tool",))

    def _reserve(self, kinds: tuple[str, ...]) -> None:
        with self._lock:
            self._raise_if_exceeded()
            for kind in kinds:
                if self._counts[kind] >= self._limits[kind]:
                    self._exhaustion = (
                        f"The run exceeded the configured {kind}-call limit "
                        f"of {self._limits[kind]:,}."
                    )
                    self._raise_if_exceeded()
            for kind in kinds:
                self._counts[kind] += 1

    def _raise_if_exceeded(self) -> None:
        if self._exhaustion is not None:
            raise RunBudgetExceeded(self._exhaustion)

    def raise_if_exceeded(self) -> None:
        """Reject finalization when any nested component swallowed exhaustion."""

        with self._lock:
            self._raise_if_exceeded()

    def snapshot(self) -> dict[str, int]:
        """Return admitted counts without exposing mutable budget state."""

        with self._lock:
            return {f"{kind}_calls": count for kind, count in self._counts.items()}


_CURRENT_RUN_BUDGET: contextvars.ContextVar[RunBudget | None] = contextvars.ContextVar(
    "general_agent_run_budget", default=None
)


@contextmanager
def run_budget_scope(budget: RunBudget) -> Iterator[None]:
    """Bind one budget across stream creation, consumption and finalization."""

    token = _CURRENT_RUN_BUDGET.set(budget)
    try:
        yield
    finally:
        _CURRENT_RUN_BUDGET.reset(token)


def _current_budget() -> RunBudget:
    budget = _CURRENT_RUN_BUDGET.get()
    if budget is None:
        raise RuntimeError("Model/tool admission requires an active run budget.")
    return budget


class RunBudgetCallback(BaseCallbackHandler):
    """Admit work at LangChain's inherited model/tool start boundary.

    Use this handler first in a run's callbacks. Synchronous hooks with
    ``raise_error=True`` propagate in both the sync and async callback manager;
    ``run_inline=True`` admits before async observers record a started call.
    Config inheritance also covers general-purpose/declarative subagents and
    summarization's direct model invocations. No per-run state is registered in
    a global harness profile or captured by the shared graph.
    """

    raise_error = True
    run_inline = True

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        del serialized, messages, kwargs
        _current_budget().reserve_model_call()

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        del serialized, prompts, kwargs
        _current_budget().reserve_model_call()

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        del input_str, kwargs
        _current_budget().reserve_tool_call(str(serialized.get("name") or "unknown"))
