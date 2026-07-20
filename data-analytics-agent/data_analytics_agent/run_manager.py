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
    ApprovalRequest,
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


def _activity_for_tool(tool_name: str, tool_input: Any) -> tuple[str, str] | None:
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "task":
        subagent_type = data.get("subagent_type")
        if subagent_type == "data-visualization":
            return ("subagent", "Delegating to the visualization analyst")
        return ("subagent", "Delegating to the text-to-SQL analyst")
    if tool_name == "read_file":
        path = str(data.get("file_path") or data.get("path") or "")
        if "semantic/" in path:
            return ("semantic", "Inspecting the OSI semantic model")
        if "SKILL.md" in path or "/skills/" in path:
            return ("skill", "Loading an analysis skill")
        if "AGENTS.md" in path:
            return ("context", "Loading coordinator context")
        return ("context", "Reading analysis context")
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
    return None


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
        self.runs.add_event(run_id, "resume", label)
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
                run_id, "interpretation", "Interpreting the request"
            )
            self.runs.add_event(
                run_id, "context", "Loading coordinator context"
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
            seen_labels: set[str] = set()
            async for event in stream:
                method = event.get("method")
                params = event.get("params") or {}
                data = params.get("data") or {}
                if method == "tools":
                    _record_tool_event(
                        diagnostic_events,
                        data,
                        agent=active_agents[-1],
                    )
                    if data.get("event") == "tool-started":
                        activity = _activity_for_tool(
                            str(data.get("tool_name") or ""),
                            data.get("input"),
                        )
                        if activity and activity[1] not in seen_labels:
                            seen_labels.add(activity[1])
                            self.runs.add_event(run_id, *activity)
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
                        if label not in seen_labels:
                            seen_labels.add(label)
                            self.runs.add_event(run_id, "subagent", label)
                    elif (
                        "text-to-sql" in graph_name
                        and lifecycle == "completed"
                    ):
                        self.runs.add_event(
                            run_id, "subagent", "Text-to-SQL analyst completed"
                        )
                    elif (
                        "data-visualization" in graph_name
                        and lifecycle == "started"
                    ):
                        label = "Visualization analyst started"
                        if label not in seen_labels:
                            seen_labels.add(label)
                            self.runs.add_event(run_id, "subagent", label)
                    elif (
                        "data-visualization" in graph_name
                        and lifecycle == "completed"
                    ):
                        self.runs.add_event(
                            run_id,
                            "subagent",
                            "Visualization analyst completed",
                        )

            interrupted = await stream.interrupted()
            if interrupted:
                reshape_requests = sum(
                    event.label == RESHAPE_ACTIVITY_LABEL
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
            self.runs.add_event(run_id, "answer", "Preparing the final answer")
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
                run_id, "error", "Execution budget exceeded"
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
            self.runs.add_event(run_id, "error", "The run failed")
            self.runs.fail(run_id, message)
            self.conversations.fail_run(thread_id, run_id)
