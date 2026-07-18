"""Non-token-streaming Deep Agent run lifecycle and HITL resume handling."""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from text2sql_agent.schemas import (
    ApprovalRequest,
    ChatTurn,
    Decision,
    FinalAnswer,
    RunStatus,
    SQLAnalysisResult,
)
from text2sql_agent.sql_tools import AgentContext, validate_readonly_sql
from text2sql_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
    StoreNotFound,
)


def decisions_to_command(
    approval: ApprovalRequest, decisions: list[Decision]
) -> Command:
    """Validate and translate API decisions to LangGraph's resume shape."""

    if len(decisions) != 1:
        raise ValueError("Exactly one decision is required for this SQL review.")
    decision = decisions[0]
    if decision.action not in approval.allowed_decisions:
        raise ValueError(f"Decision {decision.action!r} is not allowed.")

    if decision.action == "approve":
        validate_readonly_sql(approval.query)
        translated = {"type": "approve"}
    elif decision.action == "edit":
        if not decision.edited_sql:
            raise ValueError("edited_sql is required for an edit decision.")
        validate_readonly_sql(decision.edited_sql)
        translated = {
            "type": "edit",
            "edited_action": {
                "name": approval.action_name,
                "args": {"query": decision.edited_sql},
            },
        }
    else:
        translated = {
            "type": "reject",
            "message": (
                decision.feedback
                or "Revise the query and submit a new SQL action for review."
            ),
        }
    return Command(resume={"decisions": [translated]})


def _activity_for_tool(tool_name: str, tool_input: Any) -> tuple[str, str] | None:
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "task":
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
    if tool_name == "sql_db_list_tables":
        return ("schema", "Checking live table names as fallback")
    if tool_name == "sql_db_schema":
        return ("schema", "Checking live table schema as fallback")
    if tool_name == "sql_db_query_checker":
        return ("sql_check", "Checking generated SQL")
    if tool_name == "execute_sql":
        return ("execution", "Executing approved SQL")
    if tool_name == "get_saved_result":
        return ("result", "Reading a saved result")
    return None


def _extract_approval(interrupts: list[Any]) -> ApprovalRequest:
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
            query = arguments.get("query") if isinstance(arguments, dict) else None
            if name != "execute_sql" or not isinstance(query, str):
                continue
            allowed = ["approve", "edit", "reject"]
            if index < len(configs) and isinstance(configs[index], dict):
                configured = configs[index].get("allowed_decisions")
                if isinstance(configured, list):
                    allowed = [
                        item
                        for item in configured
                        if item in {"approve", "edit", "reject"}
                    ]
            return ApprovalRequest(
                action_name=name,
                query=query,
                allowed_decisions=allowed,
                description=(
                    "Review the generated SQL before it is executed. "
                    "The database has not been queried yet."
                ),
            )
    raise RuntimeError("The run interrupted without a reviewable SQL action.")


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


def _apply_sql_analysis(
    answer: FinalAnswer,
    output: dict[str, Any],
) -> FinalAnswer:
    """Prefer the current reviewed SQL result over coordinator paraphrasing."""

    analysis = _current_sql_analysis(output)
    if analysis is None or analysis.result_id != answer.result_id:
        return answer
    return FinalAnswer(
        answer=analysis.answer,
        sql=analysis.sql,
        result_id=analysis.result_id,
        assumptions=analysis.assumptions,
        interpretation=analysis.interpretation,
    )


class RunManager:
    def __init__(
        self,
        *,
        agent: Any,
        conversations: ConversationStore,
        runs: RunStore,
        results: ResultStore,
    ) -> None:
        self.agent = agent
        self.conversations = conversations
        self.runs = runs
        self.results = results

    def _validate_answer_provenance(
        self,
        answer: FinalAnswer,
        thread_id: str,
    ) -> FinalAnswer:
        """Require executable answers to reference this conversation's result."""

        if answer.result_id is None:
            if answer.sql is not None:
                raise RuntimeError(
                    "Agent returned SQL without an executed result."
                )
            return answer

        try:
            result = self.results.get(answer.result_id, thread_id)
        except StoreNotFound as exc:
            raise RuntimeError(
                "Agent returned an unknown or out-of-conversation result."
            ) from exc
        return answer.model_copy(update={"sql": result.executed_sql})

    async def start(self, run_id: str) -> None:
        snapshot = self.runs.get(run_id)
        await self._drive(
            run_id,
            {
                "messages": [
                    {"role": "user", "content": snapshot.question}
                ]
            },
        )

    async def resume(self, run_id: str, command: Command) -> None:
        self.runs.resume(run_id)
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
        label = (
            "Applying feedback and revising SQL"
            if decision_type == "reject"
            else "Executing reviewed SQL"
        )
        self.runs.add_event(run_id, "resume", label)
        await self._drive(run_id, command)

    async def _drive(self, run_id: str, agent_input: Any) -> None:
        snapshot = self.runs.get(run_id)
        thread_id = snapshot.thread_id
        self.runs.set_status(run_id, RunStatus.RUNNING)
        if not snapshot.events:
            self.runs.add_event(
                run_id, "interpretation", "Interpreting the request"
            )
            self.runs.add_event(
                run_id, "context", "Loading coordinator context"
            )

        config = {"configurable": {"thread_id": thread_id}}
        context = AgentContext(thread_id=thread_id, run_id=run_id)
        try:
            stream = await self.agent.astream_events(
                agent_input,
                config=config,
                context=context,
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

            interrupted = await stream.interrupted()
            if interrupted:
                approval = _extract_approval(await stream.interrupts())
                self.runs.add_event(
                    run_id, "approval", "SQL approval required"
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
            answer = self._validate_answer_provenance(answer, thread_id)
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
