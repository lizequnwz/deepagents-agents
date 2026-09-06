"""Non-token-streaming Deep Agent run lifecycle and HITL resume handling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
import json
import logging
import re
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from pydantic import BaseModel

from data_analytics_agent.schemas import ActivityTool
from data_analytics_agent.stores import (
    RunStore,
)

logger = logging.getLogger(__name__)

RESHAPE_ACTIVITY_LABEL = "Chart data needs SQL reshaping"
TOOL_VALUE_CHAR_LIMIT = 4_000
TOOL_DIAGNOSTIC_TOTAL_CHAR_LIMIT = 25_000
DEBUG_STATE_CHAR_LIMIT = 20_000
DEBUG_STATE_STRING_LIMIT = 2_000
DEBUG_STATE_MESSAGE_LIMIT = 10
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "connection_string",
    "cookie",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
    "access_token",
}


def _is_secret_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return normalized in _SECRET_KEYS or normalized.endswith("_api_key")


def _sanitize_tool_value(value: Any, *, depth: int = 0) -> Any:
    """Convert a tool payload to JSON-safe, secret-redacted data."""

    if depth >= 8:
        return "[maximum depth reached]"
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:50]:
            key_text = str(key)
            sanitized[key_text] = (
                "[REDACTED]"
                if _is_secret_key(key_text)
                else _sanitize_tool_value(item, depth=depth + 1)
            )
        if len(items) > 50:
            sanitized["__truncated_items__"] = len(items) - 50
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
        sanitized_items = [
            _sanitize_tool_value(item, depth=depth + 1) for item in items[:50]
        ]
        if len(items) > 50:
            sanitized_items.append(f"[{len(items) - 50} additional items truncated]")
        return sanitized_items
    if isinstance(value, bytes | bytearray):
        return f"[{type(value).__name__} containing {len(value)} bytes]"
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _bounded_tool_value(value: Any) -> Any:
    """Return structured tool data when small, otherwise a bounded preview."""

    sanitized = _sanitize_tool_value(value)
    serialized = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if len(serialized) <= TOOL_VALUE_CHAR_LIMIT:
        return sanitized
    omitted = len(serialized) - TOOL_VALUE_CHAR_LIMIT
    return {
        "preview": serialized[:TOOL_VALUE_CHAR_LIMIT],
        "truncated_characters": omitted,
    }


def _serialize_tool_value(value: Any) -> str | None:
    if value is None:
        return None
    serialized = json.dumps(
        _sanitize_tool_value(value),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if len(serialized) <= TOOL_VALUE_CHAR_LIMIT:
        return serialized
    omitted = len(serialized) - TOOL_VALUE_CHAR_LIMIT
    suffix = f"… [{omitted} characters truncated]"
    return serialized[: TOOL_VALUE_CHAR_LIMIT - len(suffix)] + suffix


def _tool_output_is_error(value: Any) -> bool:
    """Recognize handled tool failures returned as completed observations."""

    if isinstance(value, ToolMessage):
        return value.status == "error" or _tool_output_is_error(value.content)
    if isinstance(value, Mapping):
        return value.get("status") == "error" or value.get("ok") is False
    if isinstance(value, str):
        try:
            return _tool_output_is_error(json.loads(value))
        except (ValueError, TypeError):
            pass
    return False


def _tool_output_is_approval_interrupt(value: Any) -> bool:
    """Recognize the expected task interruption used for human review."""

    if not isinstance(value, Mapping):
        return False
    error = value.get("error")
    if not isinstance(error, str):
        return False
    return "Interrupt(value=" in error and "action_requests" in error


def _agent_name(graph_name: str) -> str | None:
    normalized = graph_name.casefold()
    if "text-to-sql" in normalized:
        return "text-to-sql"
    if "data-analysis" in normalized:
        return "data-analysis"
    if "data-analytics-agent" in normalized:
        return "coordinator"
    return None


def _agent_for_namespace(
    namespace: Sequence[Any],
    *,
    fallback: str = "coordinator",
) -> str:
    """Resolve a stable product agent name from a v3 event namespace."""

    if not namespace:
        return "coordinator"
    joined = "/".join(str(item) for item in namespace)
    return _agent_name(joined) or fallback


def _agent_for_model_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return "unknown"
    candidate = metadata.get("lc_agent_name")
    if isinstance(candidate, str):
        return _agent_name(candidate) or "unknown"
    return "unknown"


class RunDiagnosticsCallback(BaseCallbackHandler):
    """Aggregate completed model-call diagnostics into the current run."""

    run_inline = True

    def __init__(self, runs: RunStore, run_id: str) -> None:
        super().__init__()
        self.runs = runs
        self.run_id = run_id
        self._tools: dict[str, tuple[str, str, str]] = {}

    def on_tool_start(
        self, serialized, input_str, *, run_id, metadata=None, inputs=None, **kwargs
    ):
        call_id = str(kwargs.get("tool_call_id") or run_id)
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        agent = _agent_for_model_metadata(metadata)
        self._tools[str(run_id)] = (call_id, name, agent)
        self.runs.start_tool_call(self.run_id, call_id, agent=agent)
        self.runs.add_event(
            self.run_id,
            "tool",
            name.replace("_", " ").capitalize(),
            phase="started",
            agent=agent,
            tool=ActivityTool(
                call_id=call_id,
                name=name,
                input=_bounded_tool_value(inputs if inputs is not None else input_str),
            ),
        )

    def _finish_tool(self, run_id, output, *, failed):
        identity = self._tools.pop(str(run_id), None)
        if identity is None:
            return
        call_id, name, agent = identity
        duration = self.runs.finish_tool_call(
            self.run_id, call_id, agent=agent, failed=failed
        )
        self.runs.add_event(
            self.run_id,
            "tool",
            name.replace("_", " ").capitalize(),
            phase="failed" if failed else "completed",
            agent=agent,
            duration_ms=duration,
            tool=ActivityTool(
                call_id=call_id, name=name, output=_bounded_tool_value(output)
            ),
        )

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._finish_tool(run_id, output, failed=_tool_output_is_error(output))

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._finish_tool(run_id, {"error": str(error)}, failed=True)

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
        self.runs.start_model_call(
            self.run_id,
            str(run_id),
            agent=_agent_for_model_metadata(metadata),
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        del kwargs
        usage = None
        try:
            generation = response.generations[0][0]
        except IndexError:
            generation = None
        if isinstance(generation, ChatGeneration):
            message = generation.message
            if isinstance(message, AIMessage):
                usage = message.usage_metadata
        self.runs.finish_model_call(
            self.run_id,
            str(run_id),
            usage=usage,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        del error, kwargs
        self.runs.finish_model_call(
            self.run_id,
            str(run_id),
            usage=None,
            failed=True,
        )
