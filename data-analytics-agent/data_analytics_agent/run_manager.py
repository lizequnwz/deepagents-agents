"""Non-token-streaming Deep Agent run lifecycle and HITL resume handling."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from langgraph.types import Command

from data_analytics_agent.agents.text_to_sql.tools import (
    validate_readonly_sql,
)
from data_analytics_agent.agents.visualization.schemas import (
    ChartSpec,
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
    FinalAnswer,
    RunStatus,
    SQLAnalysisResult,
)
from data_analytics_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
    StoreNotFound,
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
    if tool_name == "get_saved_result":
        return ("result", "Reading a saved result")
    if tool_name == "inspect_result_for_chart":
        return ("chart_data", "Inspecting chart-ready result data")
    if tool_name == "validate_chart":
        return ("chart_check", "Checking the chart specification")
    if tool_name == "create_chart":
        return _chart_activity(tool_input)
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
    ) -> None:
        if agent is None and agent_resolver is None:
            raise ValueError("An agent or agent_resolver is required.")
        self.agent = agent
        self.agent_resolver = agent_resolver
        self.source_resolver = source_resolver
        self.conversations = conversations
        self.runs = runs
        self.results = results

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
                if method == "tools" and data.get("event") == "tool-started":
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
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.runs.add_event(run_id, "error", "The run failed")
            self.runs.fail(run_id, message)
            self.conversations.fail_run(thread_id, run_id)
