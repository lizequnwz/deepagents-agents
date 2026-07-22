"""Non-token-streaming Deep Agent run lifecycle and HITL resume handling."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
import json
import re
from typing import Any

from langchain.agents.middleware.model_call_limit import (
    ModelCallLimitExceededError,
)
from langchain.agents.middleware.tool_call_limit import (
    ToolCallLimitExceededError,
)
from langgraph.types import Command
from pydantic import BaseModel

from data_analytics_agent.agents.text_to_sql.tools import (
    validate_readonly_sql,
)
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
    VisualizationOutcome,
    VisualizationResult,
)
from data_analytics_agent.agents.visualization.tools import (
    chart_success_message,
)
from data_analytics_agent.agents.visualization.validation import (
    validate_chart_spec,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.schemas import (
    AgentStateSnapshot,
    ApprovalRequest,
    ActivityTool,
    ChatTurn,
    Decision,
    ExecutionBudgetDiagnostics,
    FinalAnswer,
    RunStatus,
    SQLAnalysisResult,
    ToolCallDiagnostic,
)
from data_analytics_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
    StoreNotFound,
)

RESHAPE_ACTIVITY_LABEL = "Chart data needs SQL reshaping"
BUDGET_ERROR_MESSAGE = (
    "This analysis exceeded its execution budget and was stopped before "
    "completion. Start a new request with narrower or clearer instructions."
)
DEBUG_VALUE_CHAR_LIMIT = 4_000
DEBUG_TOTAL_CHAR_LIMIT = 25_000
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


def _sanitize_debug_value(value: Any, *, depth: int = 0) -> Any:
    """Convert a tool payload to bounded, JSON-safe, secret-redacted data."""

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
                else _sanitize_debug_value(item, depth=depth + 1)
            )
        if len(items) > 50:
            sanitized["__truncated_items__"] = len(items) - 50
        return sanitized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        items = list(value)
        sanitized_items = [
            _sanitize_debug_value(item, depth=depth + 1)
            for item in items[:50]
        ]
        if len(items) > 50:
            sanitized_items.append(
                f"[{len(items) - 50} additional items truncated]"
            )
        return sanitized_items
    if isinstance(value, bytes | bytearray):
        return f"[{type(value).__name__} containing {len(value)} bytes]"
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _bounded_debug_value(value: Any) -> Any:
    """Return structured debug data when small, otherwise a bounded preview."""

    sanitized = _sanitize_debug_value(value)
    serialized = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if len(serialized) <= DEBUG_VALUE_CHAR_LIMIT:
        return sanitized
    omitted = len(serialized) - DEBUG_VALUE_CHAR_LIMIT
    return {
        "preview": serialized[:DEBUG_VALUE_CHAR_LIMIT],
        "truncated_characters": omitted,
    }


def _serialize_debug_value(value: Any) -> str | None:
    if value is None:
        return None
    serialized = json.dumps(
        _sanitize_debug_value(value),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if len(serialized) <= DEBUG_VALUE_CHAR_LIMIT:
        return serialized
    omitted = len(serialized) - DEBUG_VALUE_CHAR_LIMIT
    suffix = f"… [{omitted} characters truncated]"
    return serialized[: DEBUG_VALUE_CHAR_LIMIT - len(suffix)] + suffix


def _agent_name(graph_name: str) -> str | None:
    normalized = graph_name.casefold()
    if "text-to-sql" in normalized:
        return "text-to-sql"
    if "data-visualization" in normalized:
        return "data-visualization"
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


def _sanitize_state_snapshot(
    value: Mapping[str, Any],
    *,
    agent: str,
    namespace: Sequence[Any],
) -> AgentStateSnapshot:
    """Create a bounded state view suitable only for trusted debug mode."""

    stats = {"omitted_items": 0, "omitted_messages": 0, "truncated": False}

    def sanitize(item: Any, *, depth: int = 0) -> Any:
        if depth >= 8:
            stats["omitted_items"] += 1
            stats["truncated"] = True
            return "[maximum depth reached]"
        if isinstance(item, BaseModel):
            item = item.model_dump(mode="json")
        elif is_dataclass(item) and not isinstance(item, type):
            item = asdict(item)
        if isinstance(item, Mapping):
            clean: dict[str, Any] = {}
            pairs = list(item.items())
            for key, nested in pairs[:50]:
                key_text = str(key)
                clean[key_text] = (
                    "[REDACTED]"
                    if _is_secret_key(key_text)
                    else sanitize(nested, depth=depth + 1)
                )
            if len(pairs) > 50:
                omitted = len(pairs) - 50
                stats["omitted_items"] += omitted
                stats["truncated"] = True
                clean["__truncated_items__"] = omitted
            return clean
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            items = list(item)
            clean_items = [
                sanitize(nested, depth=depth + 1) for nested in items[:25]
            ]
            if len(items) > 25:
                omitted = len(items) - 25
                stats["omitted_items"] += omitted
                stats["truncated"] = True
                clean_items.append(f"[{omitted} additional items truncated]")
            return clean_items
        if isinstance(item, bytes | bytearray):
            return f"[{type(item).__name__} containing {len(item)} bytes]"
        if isinstance(item, str):
            if len(item) <= DEBUG_STATE_STRING_LIMIT:
                return item
            stats["omitted_items"] += 1
            stats["truncated"] = True
            omitted = len(item) - DEBUG_STATE_STRING_LIMIT
            return (
                item[:DEBUG_STATE_STRING_LIMIT]
                + f"… [{omitted} characters truncated]"
            )
        if item is None or isinstance(item, int | float | bool):
            return item
        return str(item)

    clean_state: dict[str, Any] = {}
    state_items = list(value.items())
    for key, item in state_items[:50]:
        key_text = str(key)
        if _is_secret_key(key_text):
            clean_state[key_text] = "[REDACTED]"
            continue
        if (
            key_text == "messages"
            and isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
        ):
            messages = list(item)
            omitted = max(0, len(messages) - DEBUG_STATE_MESSAGE_LIMIT)
            stats["omitted_messages"] += omitted
            if omitted:
                stats["truncated"] = True
            clean_state[key_text] = [
                sanitize(message, depth=1)
                for message in messages[-DEBUG_STATE_MESSAGE_LIMIT:]
            ]
            continue
        if key_text == "memory_contents" and isinstance(item, Mapping):
            clean_state[key_text] = {
                str(path): {"characters": len(str(contents))}
                for path, contents in list(item.items())[:25]
            }
            if len(item) > 25:
                omitted = len(item) - 25
                stats["omitted_items"] += omitted
                stats["truncated"] = True
            continue
        if (
            key_text == "skills_metadata"
            and isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
        ):
            skills: list[dict[str, Any]] = []
            for metadata in list(item)[:25]:
                raw = (
                    metadata.model_dump(mode="json")
                    if isinstance(metadata, BaseModel)
                    else metadata
                )
                if not isinstance(raw, Mapping):
                    skills.append({"value": sanitize(raw, depth=1)})
                    continue
                skills.append(
                    {
                        field: sanitize(raw[field], depth=1)
                        for field in ("name", "path", "source")
                        if field in raw
                    }
                )
            clean_state[key_text] = skills
            if len(item) > 25:
                omitted = len(item) - 25
                stats["omitted_items"] += omitted
                stats["truncated"] = True
            continue
        clean_state[key_text] = sanitize(item, depth=1)
    if len(state_items) > 50:
        omitted = len(state_items) - 50
        stats["omitted_items"] += omitted
        stats["truncated"] = True
        clean_state["__truncated_fields__"] = omitted

    def serialized_length() -> int:
        return len(
            json.dumps(clean_state, ensure_ascii=False, default=str)
        )

    protected = {"thread_id", "run_id", "source_id", "question"}
    while serialized_length() > DEBUG_STATE_CHAR_LIMIT:
        candidates = [
            key
            for key in clean_state
            if key not in protected
            and clean_state[key] != "[omitted: snapshot size limit]"
        ]
        if not candidates:
            break
        largest = max(
            candidates,
            key=lambda key: len(
                json.dumps(clean_state[key], ensure_ascii=False, default=str)
            ),
        )
        clean_state[largest] = "[omitted: snapshot size limit]"
        stats["omitted_items"] += 1
        stats["truncated"] = True

    return AgentStateSnapshot(
        agent=agent,
        namespace=[str(item) for item in namespace],
        state=clean_state,
        truncated=bool(stats["truncated"]),
        omitted_items=int(stats["omitted_items"]),
        omitted_messages=int(stats["omitted_messages"]),
    )


def _record_tool_event(
    events: deque[dict[str, Any]],
    data: dict[str, Any],
    *,
    agent: str,
) -> None:
    event_type = data.get("event")
    tool_call_id = str(data.get("tool_call_id") or "")
    if event_type == "tool-started":
        events.append(
            {
                "tool_call_id": tool_call_id,
                "agent": agent,
                "tool_name": str(data.get("tool_name") or "unknown"),
                "input": data.get("input"),
                "output": None,
                "error": None,
            }
        )
        return
    if event_type not in {"tool-finished", "tool-error"}:
        return
    matching = next(
        (
            item
            for item in reversed(events)
            if tool_call_id and item["tool_call_id"] == tool_call_id
        ),
        None,
    )
    if matching is None:
        matching = {
            "tool_call_id": tool_call_id,
            "agent": agent,
            "tool_name": str(data.get("tool_name") or "unknown"),
            "input": None,
            "output": None,
            "error": None,
        }
        events.append(matching)
    if event_type == "tool-finished":
        matching["output"] = data.get("output")
    else:
        matching["error"] = str(data.get("message") or "Tool call failed.")


def _debug_tool_calls(
    events: deque[dict[str, Any]],
    *,
    agent: str,
) -> list[ToolCallDiagnostic]:
    matching = [item for item in events if item["agent"] == agent]
    if not matching:
        matching = list(events)
    selected: list[ToolCallDiagnostic] = []
    total_chars = 0
    for item in reversed(matching):
        diagnostic = ToolCallDiagnostic(
            tool_name=item["tool_name"],
            input=_serialize_debug_value(item.get("input")),
            output=_serialize_debug_value(item.get("output")),
            error=_serialize_debug_value(item.get("error")),
        )
        size = len(diagnostic.model_dump_json(exclude_none=True))
        if total_chars + size > DEBUG_TOTAL_CHAR_LIMIT:
            break
        selected.append(diagnostic)
        total_chars += size
    return list(reversed(selected))


def _budget_diagnostics(
    exc: ModelCallLimitExceededError | ToolCallLimitExceededError,
    *,
    run_id: str,
    agent: str,
    events: deque[dict[str, Any]],
    include_debug_details: bool,
) -> ExecutionBudgetDiagnostics:
    if isinstance(exc, ModelCallLimitExceededError):
        budget_type = "model_calls"
        tool_name = None
        attempted_count = exc.thread_count + 1
        limit = exc.thread_limit or exc.run_limit
    else:
        budget_type = "tool_calls"
        tool_name = exc.tool_name
        attempted_count = exc.thread_count
        limit = exc.thread_limit or exc.run_limit
    assert limit is not None
    return ExecutionBudgetDiagnostics(
        agent=agent,
        budget_type=budget_type,
        limit=limit,
        attempted_count=attempted_count,
        run_id=run_id,
        tool_name=tool_name,
        recent_tool_calls=(
            _debug_tool_calls(events, agent=agent)
            if include_debug_details
            else []
        ),
    )


def _single_decision(
    approval: ApprovalRequest,
    decisions: list[Decision],
) -> Decision:
    if len(decisions) != 1:
        raise ValueError("Exactly one decision is required for this review.")
    decision = decisions[0]
    if decision.action not in approval.allowed_decisions:
        raise ValueError(f"Decision {decision.action!r} is not allowed.")
    return decision


def decisions_to_command(
    approval: ApprovalRequest,
    decisions: list[Decision],
) -> Command:
    """Validate and translate API decisions to LangGraph's resume shape."""

    decision = _single_decision(approval, decisions)

    if decision.action == "reject":
        translated = {
            "type": "reject",
            "message": (
                decision.feedback
                or "Revise the query and submit it for review again."
            ),
        }
        return Command(resume={"decisions": [translated]})

    if decision.action == "approve":
        validate_readonly_sql(approval.query, approval.dialect)
        translated = {"type": "approve"}
    else:
        if not decision.edited_sql:
            raise ValueError("edited_sql is required for an edit decision.")
        validate_readonly_sql(decision.edited_sql, approval.dialect)
        translated = {
            "type": "edit",
            "edited_action": {
                "name": approval.action_name,
                "args": {"query": decision.edited_sql},
            },
        }
    return Command(resume={"decisions": [translated]})


def _safe_activity_value(value: Any, *, limit: int = 36) -> str:
    """Bound model-authored chart arguments before showing them in progress."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"[^A-Za-z0-9 _./:-]", "", text)
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def _bounded_activity_text(value: Any, *, limit: int = 500) -> str:
    """Keep a readable argument preview without altering its meaning."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def _project_relative_path(value: Any) -> str:
    path = str(value or "").strip()
    if path.startswith("/project/"):
        return path.removeprefix("/project/")
    return path


def _skill_name(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if parts and parts[-1] == "SKILL.md" and len(parts) > 1:
        return parts[-2]
    if "skills" in parts:
        index = parts.index("skills")
        if index + 1 < len(parts):
            return parts[index + 1]
    return "analysis skill"


def _chart_activity(tool_input: Any) -> tuple[str, str]:
    """Describe a safe, useful subset of a create_chart call."""

    data = tool_input if isinstance(tool_input, dict) else {}
    raw_spec = data.get("spec")
    if not isinstance(raw_spec, dict):
        return ("chart", "Generating chart")
    try:
        spec = ChartSpec.model_validate(raw_spec)
    except ValueError:
        return ("chart", "Generating chart")

    arguments: list[str] = []
    if spec.x:
        arguments.append(f"x={_safe_activity_value(spec.x)}")
    if spec.y:
        y_columns = ", ".join(
            _safe_activity_value(column) for column in spec.y[:3]
        )
        if len(spec.y) > 3:
            y_columns = f"{y_columns}, …"
        arguments.append(f"y={y_columns}")
    if spec.secondary_y:
        arguments.append(
            f"secondary y={_safe_activity_value(spec.secondary_y)}"
        )
    if spec.value:
        arguments.append(f"value={_safe_activity_value(spec.value)}")
    if spec.location:
        arguments.append(f"location={_safe_activity_value(spec.location)}")
    if spec.orientation == "horizontal":
        arguments.append("horizontal")
    if spec.category_limit is not None:
        arguments.append(f"top {spec.category_limit}")

    label = f"Generating {spec.chart_type.value} chart"
    if arguments:
        label = f"{label} · {' · '.join(arguments[:4])}"
    return ("chart", label)


def _chart_arguments(tool_input: Any) -> dict[str, Any]:
    data = tool_input if isinstance(tool_input, dict) else {}
    raw_spec = data.get("spec")
    if not isinstance(raw_spec, dict):
        return {}
    try:
        spec = ChartSpec.model_validate(raw_spec)
    except ValueError:
        return {}
    arguments: dict[str, Any] = {"chart_type": spec.chart_type.value}
    for field in ("x", "secondary_y", "value", "location"):
        value = getattr(spec, field)
        if value:
            arguments[field] = _safe_activity_value(value, limit=80)
    if spec.y:
        arguments["y"] = [
            _safe_activity_value(column, limit=80) for column in spec.y[:3]
        ]
        if len(spec.y) > 3:
            arguments["omitted_y_columns"] = len(spec.y) - 3
    if spec.orientation == "horizontal":
        arguments["orientation"] = "horizontal"
    if spec.category_limit is not None:
        arguments["category_limit"] = spec.category_limit
    return arguments


def _activity_arguments(tool_name: str, tool_input: Any) -> dict[str, Any]:
    """Return the explicit safe argument allowlist for one known tool."""

    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "task":
        return {
            "subagent_type": _safe_activity_value(
                data.get("subagent_type") or "text-to-sql", limit=80
            )
        }
    if tool_name == "read_file":
        path = _project_relative_path(
            data.get("file_path") or data.get("path")
        )
        arguments: dict[str, Any] = {"path": path}
        for field in ("offset", "limit"):
            if data.get(field) is not None:
                arguments[field] = data[field]
        if "SKILL.md" in path or "/skills/" in f"/{path}":
            arguments["skill"] = _skill_name(path)
        return arguments
    if tool_name in {"grep", "glob"}:
        arguments = {}
        for field in ("pattern", "query", "path", "glob"):
            if data.get(field) is not None:
                value = data[field]
                arguments[field] = (
                    _project_relative_path(value)
                    if field == "path"
                    else _bounded_activity_text(value, limit=160)
                )
        return arguments
    if tool_name == "write_todos":
        todos = data.get("todos")
        return {
            "step_count": len(todos)
            if isinstance(todos, Sequence)
            and not isinstance(todos, (str, bytes, bytearray))
            else 0
        }
    if tool_name == "get_table_schema":
        names = data.get("table_names") or []
        if not isinstance(names, Sequence) or isinstance(names, str):
            return {}
        clean_names = [
            _safe_activity_value(name, limit=80) for name in list(names)[:10]
        ]
        arguments = {"table_names": clean_names}
        if len(names) > 10:
            arguments["omitted_tables"] = len(names) - 10
        return arguments
    if tool_name in {"validate_sql", "execute_sql"}:
        query = data.get("query")
        return (
            {"query": _bounded_activity_text(query)}
            if query is not None
            else {}
        )
    if tool_name in {
        "inspect_conversation_result",
        "inspect_result_for_chart",
    }:
        result_id = str(data.get("result_id") or "")
        return {"result": result_id[:8]} if result_id else {}
    if tool_name in {"validate_chart", "create_chart"}:
        return _chart_arguments(tool_input)
    if tool_name == "finish_visualization":
        arguments = {}
        if data.get("outcome"):
            arguments["outcome"] = _safe_activity_value(
                data["outcome"], limit=80
            )
        if data.get("message"):
            arguments["message"] = _bounded_activity_text(
                data["message"], limit=240
            )
        return arguments
    return {}


def _activity_for_tool(tool_name: str, tool_input: Any) -> tuple[str, str]:
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "task":
        subagent_type = data.get("subagent_type")
        if subagent_type == "data-visualization":
            return ("subagent", "Delegating to the visualization analyst")
        return ("subagent", "Delegating to the text-to-SQL analyst")
    if tool_name == "read_file":
        path = _project_relative_path(
            data.get("file_path") or data.get("path")
        )
        filename = path.rsplit("/", 1)[-1] or "context"
        if "semantic/" in path:
            return ("semantic", f"Inspecting semantic model · {filename}")
        if "SKILL.md" in path or "/skills/" in path:
            return ("skill", f"Loading skill · {_skill_name(path)}")
        if "AGENTS.md" in path:
            return ("context", "Loading coordinator context · AGENTS.md")
        return ("context", f"Reading context · {filename}")
    if tool_name in {"grep", "glob"}:
        return ("search", "Searching semantic context")
    if tool_name == "write_todos":
        return ("planning", "Planning the analysis")
    if tool_name == "list_tables":
        return ("schema", "Checking live table names as fallback")
    if tool_name == "get_table_schema":
        return ("schema", "Checking live table schema as fallback")
    if tool_name == "validate_sql":
        return ("sql_check", "Checking generated SQL")
    if tool_name == "execute_sql":
        return ("execution", "Executing approved SQL")
    if tool_name == "list_conversation_results":
        return ("result", "Listing saved conversation results")
    if tool_name == "inspect_conversation_result":
        return ("result", "Inspecting a saved conversation result")
    if tool_name == "inspect_result_for_chart":
        return ("chart_data", "Inspecting chart-ready result data")
    if tool_name == "validate_chart":
        return ("chart_check", "Checking the chart specification")
    if tool_name == "create_chart":
        return _chart_activity(tool_input)
    if tool_name == "finish_visualization":
        outcome = str(data.get("outcome") or "")
        if outcome == "needs_sql_reshape":
            return ("chart", RESHAPE_ACTIVITY_LABEL)
        return ("chart", "Requested chart cannot be created")
    return ("tool", f"Using tool · {tool_name or 'unknown'}")


def _completed_activity_label(label: str) -> str:
    replacements = {
        "Loading ": "Loaded ",
        "Inspecting ": "Inspected ",
        "Reading ": "Read ",
        "Searching ": "Searched ",
        "Planning ": "Planned ",
        "Checking ": "Checked ",
        "Executing ": "Executed ",
        "Listing ": "Listed ",
        "Generating ": "Generated ",
        "Delegating ": "Delegated ",
        "Using ": "Used ",
    }
    for prefix, replacement in replacements.items():
        if label.startswith(prefix):
            return replacement + label[len(prefix) :]
    return label


def _extract_approval(
    interrupts: list[Any],
    *,
    source: DataSource | None = None,
) -> ApprovalRequest:
    for interrupt in interrupts:
        value = getattr(interrupt, "value", interrupt)
        if not isinstance(value, dict):
            continue
        requests = value.get("action_requests") or []
        configs = value.get("review_configs") or []
        for index, action in enumerate(requests):
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            arguments = action.get("args") or action.get("arguments") or {}
            allowed = ["approve", "edit", "reject"]
            if index < len(configs) and isinstance(configs[index], dict):
                configured = configs[index].get("allowed_decisions")
                if isinstance(configured, list):
                    allowed = [
                        item
                        for item in configured
                        if item in {"approve", "edit", "reject"}
                    ]
            if not isinstance(arguments, dict):
                continue
            query = arguments.get("query")
            if name == "execute_sql" and isinstance(query, str):
                return ApprovalRequest(
                    action_name=name,
                    query=query,
                    allowed_decisions=allowed,
                    source_id=source.source_id if source else "",
                    dialect=source.dialect if source else "sqlite",
                    timeout_seconds=(
                        source.limits.timeout_seconds if source else 10
                    ),
                    max_result_rows=(
                        source.limits.max_result_rows if source else 500
                    ),
                    description=(
                        "Review the generated SQL before it is executed. "
                        "The database has not been queried yet."
                    ),
                )
    raise RuntimeError("The run interrupted without a reviewable action.")


def _current_sql_analysis(output: dict[str, Any]) -> SQLAnalysisResult | None:
    """Find the reviewed SQL subagent result from the current user turn."""

    messages = output.get("messages")
    if not isinstance(messages, list):
        return None

    for message in reversed(messages):
        message_type = getattr(message, "type", None)
        if message_type is None and isinstance(message, dict):
            message_type = message.get("type") or message.get("role")
        if message_type in {"human", "user"}:
            return None

        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            return SQLAnalysisResult.model_validate_json(content)
        except ValueError:
            continue
    return None


def _current_visualization(
    output: dict[str, Any],
) -> VisualizationResult | None:
    """Find the reviewed visualization result from the current user turn."""

    messages = output.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        message_type = getattr(message, "type", None)
        if message_type is None and isinstance(message, dict):
            message_type = message.get("type") or message.get("role")
        if message_type in {"human", "user"}:
            return None
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            return VisualizationResult.model_validate_json(content)
        except ValueError:
            continue
    return None


def _apply_sql_analysis(
    answer: FinalAnswer,
    output: dict[str, Any],
) -> FinalAnswer:
    """Prefer the current reviewed SQL result over coordinator paraphrasing."""

    analysis = _current_sql_analysis(output)
    if analysis is None:
        return answer
    if answer.result_id is not None and analysis.result_id != answer.result_id:
        return answer
    updates = {
        "sql": analysis.sql,
        "result_id": analysis.result_id,
        "assumptions": analysis.assumptions,
        "interpretation": analysis.interpretation,
    }
    if _current_visualization(output) is None:
        updates["answer"] = analysis.answer
    return answer.model_copy(update=updates)


def _apply_visualization(
    answer: FinalAnswer,
    output: dict[str, Any],
) -> FinalAnswer:
    """Attach the exact generated chart and authoritative success message."""

    visualization = _current_visualization(output)
    if visualization is None:
        return answer
    if visualization.outcome is not VisualizationOutcome.CHART_CREATED:
        return answer.model_copy(
            update={
                "answer": visualization.answer,
                "result_id": visualization.result_id or answer.result_id,
                "chart": None,
            }
        )
    assert visualization.chart is not None
    if (
        answer.result_id is not None
        and answer.result_id != visualization.chart.result_id
    ):
        return answer
    return answer.model_copy(
        update={
            "answer": chart_success_message(visualization.chart),
            "result_id": visualization.chart.result_id,
            "chart": visualization.chart,
        }
    )


class RunManager:
    def __init__(
        self,
        *,
        agent: Any | None = None,
        agent_resolver: Callable[[str], Any] | None = None,
        source_resolver: Callable[[str], DataSource] | None = None,
        conversations: ConversationStore,
        runs: RunStore,
        results: ResultStore,
        debug_details: bool = False,
    ) -> None:
        if agent is None and agent_resolver is None:
            raise ValueError("An agent or agent_resolver is required.")
        self.agent = agent
        self.agent_resolver = agent_resolver
        self.source_resolver = source_resolver
        self.conversations = conversations
        self.runs = runs
        self.results = results
        self.debug_details = debug_details
        self._diagnostic_events: dict[str, deque[dict[str, Any]]] = {}

    def _validate_answer_provenance(
        self,
        answer: FinalAnswer,
        thread_id: str,
        source_id: str,
    ) -> FinalAnswer:
        """Require executable answers to reference this conversation's result."""

        if answer.result_id is None:
            if answer.chart is not None:
                raise RuntimeError(
                    "Agent returned a chart without an executed result."
                )
            if answer.sql is not None:
                raise RuntimeError(
                    "Agent returned SQL without an executed result."
                )
            return answer

        try:
            result = self.results.get(
                answer.result_id,
                thread_id,
                source_id=source_id,
            )
        except StoreNotFound as exc:
            raise RuntimeError(
                "Agent returned an unknown or out-of-conversation result."
            ) from exc
        if answer.chart is not None:
            if answer.chart.result_id != result.result_id:
                raise RuntimeError(
                    "Agent returned a chart for a different result."
                )
            validate_chart_spec(answer.chart, result)
        return answer.model_copy(update={"sql": result.executed_sql})

    async def start(self, run_id: str) -> None:
        snapshot = self.runs.get(run_id)
        conversation = self.conversations.get(snapshot.thread_id)
        messages: list[dict[str, str]] = []
        for turn in conversation.turns:
            messages.append(
                {"role": "user", "content": turn.user_message}
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.answer.model_dump_json(
                        exclude_none=True
                    ),
                }
            )
        messages.append(
            {"role": "user", "content": snapshot.question}
        )
        await self._drive(
            run_id,
            {
                "messages": messages,
                "thread_id": snapshot.thread_id,
                "run_id": run_id,
                "source_id": snapshot.source_id,
                "question": snapshot.question,
            },
        )

    async def resume(
        self,
        run_id: str,
        command: Command,
    ) -> None:
        decisions = (
            command.resume.get("decisions", [])
            if isinstance(command.resume, dict)
            else []
        )
        decision_type = (
            decisions[0].get("type")
            if decisions and isinstance(decisions[0], dict)
            else None
        )
        if decision_type == "reject":
            label = "Applying feedback and revising SQL"
        else:
            label = "Executing reviewed SQL"
        self.runs.add_event(run_id, "resume", label, agent="coordinator")
        await self._drive(run_id, command)

    async def _drive(self, run_id: str, agent_input: Any) -> None:
        snapshot = self.runs.get(run_id)
        thread_id = snapshot.thread_id
        source_id = snapshot.source_id
        source = (
            self.source_resolver(source_id) if self.source_resolver else None
        )
        graph = (
            self.agent_resolver(source_id)
            if self.agent_resolver is not None
            else self.agent
        )
        self.runs.set_status(run_id, RunStatus.RUNNING)
        diagnostic_events = self._diagnostic_events.setdefault(
            run_id, deque(maxlen=5)
        )
        active_agents = ["coordinator"]
        if not snapshot.events:
            self.runs.add_event(
                run_id,
                "interpretation",
                "Interpreting the request",
                agent="coordinator",
            )
            self.runs.add_event(
                run_id,
                "context",
                "Loading coordinator context · AGENTS.md",
                agent="coordinator",
            )

        # A run owns its checkpoint lifecycle. Conversation history is supplied
        # explicitly in start(), so a directly completed chart cannot leave a
        # stale nested interrupt for the next user turn.
        config = {"configurable": {"thread_id": run_id}}
        try:
            stream = await graph.astream_events(
                agent_input,
                config=config,
                version="v3",
            )
            tool_sequence = 0
            tool_activities: dict[
                str, tuple[str, str, str, str, dict[str, Any]]
            ] = {}
            open_tool_calls: dict[str, list[str]] = {}
            async for event in stream:
                method = event.get("method")
                params = event.get("params") or {}
                data = params.get("data") or {}
                if method == "tools":
                    namespace = params.get("namespace") or []
                    event_agent = _agent_for_namespace(
                        namespace,
                        fallback=active_agents[-1],
                    )
                    _record_tool_event(
                        diagnostic_events,
                        data,
                        agent=event_agent,
                    )
                    lifecycle = data.get("event")
                    tool_name = str(data.get("tool_name") or "unknown")
                    raw_call_id = str(data.get("tool_call_id") or "")
                    if lifecycle == "tool-started":
                        tool_sequence += 1
                        call_id = raw_call_id or f"tool-{tool_sequence}"
                        activity = _activity_for_tool(
                            tool_name,
                            data.get("input"),
                        )
                        arguments = _activity_arguments(
                            tool_name,
                            data.get("input"),
                        )
                        tool_activities[call_id] = (
                            activity[0],
                            activity[1],
                            event_agent,
                            tool_name,
                            arguments,
                        )
                        open_tool_calls.setdefault(tool_name, []).append(call_id)
                        self.runs.add_event(
                            run_id,
                            *activity,
                            phase="started",
                            agent=event_agent,
                            tool=ActivityTool(
                                call_id=call_id,
                                name=tool_name,
                                arguments=arguments,
                                debug_input=(
                                    _bounded_debug_value(data.get("input"))
                                    if self.debug_details
                                    else None
                                ),
                            ),
                        )
                    elif lifecycle in {"tool-finished", "tool-error"}:
                        call_id = raw_call_id
                        if not call_id:
                            candidates = open_tool_calls.get(tool_name) or []
                            call_id = candidates[-1] if candidates else ""
                        recorded = tool_activities.get(call_id)
                        if recorded is None:
                            kind = "tool"
                            label = f"Using tool · {tool_name}"
                            recorded_agent = event_agent
                            arguments = {}
                        else:
                            (
                                kind,
                                label,
                                recorded_agent,
                                recorded_tool_name,
                                arguments,
                            ) = recorded
                            tool_name = recorded_tool_name
                        failed = lifecycle == "tool-error"
                        self.runs.add_event(
                            run_id,
                            kind,
                            (
                                f"Tool failed · {tool_name}"
                                if failed
                                else _completed_activity_label(label)
                            ),
                            phase="failed" if failed else "completed",
                            agent=recorded_agent,
                            tool=ActivityTool(
                                call_id=call_id or None,
                                name=tool_name,
                                arguments=arguments,
                            ),
                        )
                        if call_id:
                            candidates = open_tool_calls.get(tool_name) or []
                            if call_id in candidates:
                                candidates.remove(call_id)
                elif method == "lifecycle":
                    graph_name = str(data.get("graph_name") or "")
                    lifecycle = data.get("event")
                    lifecycle_agent = _agent_name(graph_name)
                    if lifecycle == "started" and lifecycle_agent:
                        if active_agents[-1] != lifecycle_agent:
                            active_agents.append(lifecycle_agent)
                    elif lifecycle == "completed" and lifecycle_agent:
                        for index in range(len(active_agents) - 1, 0, -1):
                            if active_agents[index] == lifecycle_agent:
                                del active_agents[index]
                                break
                    if "text-to-sql" in graph_name and lifecycle == "started":
                        label = "Text-to-SQL analyst started"
                        self.runs.add_event(
                            run_id,
                            "subagent",
                            label,
                            phase="started",
                            agent="text-to-sql",
                        )
                    elif (
                        "text-to-sql" in graph_name
                        and lifecycle == "completed"
                    ):
                        self.runs.add_event(
                            run_id,
                            "subagent",
                            "Text-to-SQL analyst completed",
                            phase="completed",
                            agent="text-to-sql",
                        )
                    elif (
                        "data-visualization" in graph_name
                        and lifecycle == "started"
                    ):
                        label = "Visualization analyst started"
                        self.runs.add_event(
                            run_id,
                            "subagent",
                            label,
                            phase="started",
                            agent="data-visualization",
                        )
                    elif (
                        "data-visualization" in graph_name
                        and lifecycle == "completed"
                    ):
                        self.runs.add_event(
                            run_id,
                            "subagent",
                            "Visualization analyst completed",
                            phase="completed",
                            agent="data-visualization",
                        )
                elif (
                    method == "values"
                    and self.debug_details
                    and isinstance(data, Mapping)
                ):
                    namespace = params.get("namespace") or []
                    state_agent = _agent_for_namespace(
                        namespace,
                        fallback=active_agents[-1],
                    )
                    self.runs.set_debug_state(
                        run_id,
                        _sanitize_state_snapshot(
                            data,
                            agent=state_agent,
                            namespace=namespace,
                        ),
                    )

            interrupted = await stream.interrupted()
            if interrupted:
                reshape_requests = sum(
                    event.label == RESHAPE_ACTIVITY_LABEL
                    and event.phase == "started"
                    for event in self.runs.get(run_id).events
                )
                if reshape_requests > 1:
                    raise RuntimeError(
                        "The requested chart remained incompatible after the "
                        "single allowed SQL-reshape recovery cycle."
                    )
                approval = _extract_approval(
                    await stream.interrupts(),
                    source=source,
                )
                self.runs.add_event(
                    run_id,
                    "approval",
                    "SQL approval required",
                    agent="text-to-sql",
                )
                self.runs.require_approval(run_id, approval)
                return

            output = await stream.output()
            if not output or "structured_response" not in output:
                raise RuntimeError("Agent completed without a structured response.")
            answer_value = output["structured_response"]
            answer = (
                answer_value
                if isinstance(answer_value, FinalAnswer)
                else FinalAnswer.model_validate(answer_value)
            )
            answer = _apply_sql_analysis(answer, output)
            answer = _apply_visualization(answer, output)
            answer = self._validate_answer_provenance(
                answer,
                thread_id,
                source_id,
            )
            self.runs.add_event(
                run_id,
                "answer",
                "Preparing the final answer",
                agent="coordinator",
            )
            self.runs.complete(run_id, answer)
            self._diagnostic_events.pop(run_id, None)
            completed = self.runs.get(run_id)
            self.conversations.complete_run(
                thread_id,
                run_id,
                ChatTurn(
                    user_message=completed.question,
                    answer=answer,
                    activities=completed.events,
                    debug_states=completed.debug_states,
                ),
            )
        except (
            ModelCallLimitExceededError,
            ToolCallLimitExceededError,
        ) as exc:
            diagnostics = _budget_diagnostics(
                exc,
                run_id=run_id,
                agent=active_agents[-1],
                events=diagnostic_events,
                include_debug_details=self.debug_details,
            )
            self._diagnostic_events.pop(run_id, None)
            self.runs.add_event(
                run_id,
                "error",
                "Execution budget exceeded",
                phase="failed",
                agent=active_agents[-1],
            )
            self.runs.fail(
                run_id,
                BUDGET_ERROR_MESSAGE,
                diagnostics=diagnostics,
            )
            self.conversations.fail_run(thread_id, run_id)
        except Exception as exc:
            self._diagnostic_events.pop(run_id, None)
            message = str(exc) or exc.__class__.__name__
            self.runs.add_event(
                run_id,
                "error",
                "The run failed",
                phase="failed",
                agent=active_agents[-1],
            )
            self.runs.fail(run_id, message)
            self.conversations.fail_run(thread_id, run_id)
