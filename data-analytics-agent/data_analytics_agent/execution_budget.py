"""Execution-budget middleware construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)


def execution_budget_middleware(
    *,
    model_calls: int,
    tool_calls: int,
    specific_tool_calls: Mapping[str, int] | None = None,
) -> list[Any]:
    """Build strict lifecycle limits for one agent graph."""

    middleware: list[Any] = [
        ModelCallLimitMiddleware(
            thread_limit=model_calls,
            exit_behavior="error",
        ),
        ToolCallLimitMiddleware(
            thread_limit=tool_calls,
            exit_behavior="error",
        ),
    ]
    for tool_name, limit in (specific_tool_calls or {}).items():
        middleware.append(
            ToolCallLimitMiddleware(
                tool_name=tool_name,
                thread_limit=limit,
                exit_behavior="error",
            )
        )
    return middleware
