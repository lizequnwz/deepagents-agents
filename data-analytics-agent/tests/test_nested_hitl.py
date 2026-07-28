from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from data_analytics_agent.agents.text_to_sql.agent import (
    SQL_OUTPUT_RETRY_MESSAGE,
)
from data_analytics_agent.run_manager import (
    _extract_approval,
    decisions_to_command,
)
from data_analytics_agent.schemas import Decision, SQLAnalysisResult

GENERATED_SQL = "SELECT Name FROM Artist LIMIT 5"
EDITED_SQL = "SELECT Name FROM Artist ORDER BY Name LIMIT 3"
REVISED_SQL = (
    "SELECT Country, COUNT(*) AS customer_count "
    "FROM Customer GROUP BY Country ORDER BY customer_count DESC LIMIT 5"
)
PROFILE = {
    "scope": "stored_rows",
    "row_count": 1,
    "columns": [
        {
            "name": "Name",
            "physical_kind": "text",
            "role_candidates": [
                {"role": "categorical", "confidence": 1.0}
            ],
            "temporal_kind": None,
            "null_count": 0,
            "non_null_count": 1,
            "distinct_count": 1,
            "minimum": "AC/DC",
            "maximum": "AC/DC",
            "representative_values": ["AC/DC"],
        }
    ],
}


@pytest.fixture(autouse=True)
def disable_langsmith_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@dataclass
class ScriptState:
    executed: list[str] = field(default_factory=list)
    rejection_feedback: str | None = None
    validation_retry_seen: bool = False


class ScriptedChatModel(BaseChatModel):
    role: str
    script_state: Any

    @property
    def _llm_type(self) -> str:
        return "scripted-hitl-regression"

    def bind_tools(
        self,
        _tools: Any,
        *,
        tool_choice: str | None = None,
        **_kwargs: Any,
    ) -> ScriptedChatModel:
        del tool_choice
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **_kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        message = (
            self._coordinator_response(messages)
            if self.role == "coordinator"
            else self._sql_response(messages)
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _coordinator_response(
        self,
        messages: list[BaseMessage],
    ) -> AIMessage:
        if any(
            isinstance(message, ToolMessage) and message.name == "task"
            for message in messages
        ):
            return AIMessage(content="SQL analysis completed.")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {
                        "description": "Answer the database question with SQL.",
                        "subagent_type": "text-to-sql",
                    },
                    "id": "task-call",
                }
            ],
        )

    def _sql_response(self, messages: list[BaseMessage]) -> AIMessage:
        tool_messages = [
            message
            for message in messages
            if isinstance(message, ToolMessage)
        ]
        if not tool_messages:
            return self._execute_call(GENERATED_SQL, "generated-sql")

        latest = tool_messages[-1]
        if latest.name == "execute_sql" and latest.status == "error":
            self.script_state.rejection_feedback = str(latest.content)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "SQLAnalysisResult",
                        "args": {
                            "answer": "The query was rejected.",
                            "sql": GENERATED_SQL,
                            "result_id": None,
                            "row_count": None,
                            "assumptions": [],
                            "interpretation": "No query was executed.",
                        },
                        "id": "invalid-completion",
                    }
                ],
            )

        if latest.name == "SQLAnalysisResult":
            self.script_state.validation_retry_seen = True
            assert SQL_OUTPUT_RETRY_MESSAGE.strip() in str(latest.content)
            return self._execute_call(REVISED_SQL, "revised-sql")

        if latest.name == "execute_sql":
            executed_sql = self.script_state.executed[-1]
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "SQLAnalysisResult",
                        "args": {
                            "answer": "The reviewed query executed.",
                            "sql": executed_sql,
                            "result_id": "result-1",
                            "columns": ["Name"],
                            "sample_rows": [{"Name": "AC/DC"}],
                            "profile": PROFILE,
                            "row_count": 1,
                            "truncated": False,
                            "assumptions": [],
                            "interpretation": "One result was returned.",
                        },
                        "id": "valid-completion",
                    }
                ],
            )

        raise AssertionError(f"Unexpected tool message: {latest}")

    @staticmethod
    def _execute_call(query: str, call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "execute_sql",
                    "args": {"query": query},
                    "id": call_id,
                }
            ],
        )


class ParallelCoordinatorModel(ScriptedChatModel):
    """Issue two SQL assignments to reproduce parallel nested interrupts."""

    def _coordinator_response(
        self,
        messages: list[BaseMessage],
    ) -> AIMessage:
        if any(
            isinstance(message, ToolMessage) and message.name == "task"
            for message in messages
        ):
            return AIMessage(content="Both SQL analyses completed.")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {
                        "description": "Answer database question A with SQL.",
                        "subagent_type": "text-to-sql",
                    },
                    "id": "task-call-a",
                },
                {
                    "name": "task",
                    "args": {
                        "description": "Answer database question B with SQL.",
                        "subagent_type": "text-to-sql",
                    },
                    "id": "task-call-b",
                },
            ],
        )


def _build_graph(
    state: ScriptState,
    *,
    coordinator_model: BaseChatModel | None = None,
):
    @tool
    def execute_sql(query: str) -> dict[str, Any]:
        """Execute a human-reviewed SQL query."""

        state.executed.append(query)
        return {
            "result_id": "result-1",
            "executed_sql": query,
            "columns": ["Name"],
            "sample_rows": [{"Name": "AC/DC"}],
            "profile": PROFILE,
            "row_count": 1,
            "truncated": False,
        }

    sql_subagent = {
        "name": "text-to-sql",
        "description": "Generate and execute reviewed SQL.",
        "system_prompt": "Use execute_sql and finish only after it succeeds.",
        "tools": [execute_sql],
        "model": ScriptedChatModel(role="sql", script_state=state),
        "interrupt_on": {
            "execute_sql": {
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        },
        "response_format": ToolStrategy(
            SQLAnalysisResult,
            handle_errors=SQL_OUTPUT_RETRY_MESSAGE,
        ),
    }
    return create_deep_agent(
        model=coordinator_model
        or ScriptedChatModel(role="coordinator", script_state=state),
        subagents=[sql_subagent],
        checkpointer=InMemorySaver(),
    )


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def test_editor_sql_is_the_only_sql_executed() -> None:
    state = ScriptState()
    graph = _build_graph(state)
    config = _config("edited-sql")

    interrupted = graph.invoke(
        {"messages": [{"role": "user", "content": "List artists"}]},
        config,
    )
    assert interrupted["__interrupt__"]
    assert state.executed == []

    approval = _extract_approval(interrupted["__interrupt__"])
    completed = graph.invoke(
        decisions_to_command(
            approval,
            [Decision(action="edit", edited_sql=EDITED_SQL)],
        ),
        config,
    )

    assert "__interrupt__" not in completed
    assert state.executed == [EDITED_SQL]


def test_rejection_feedback_forces_revision_and_invalid_completion_retries() -> None:
    state = ScriptState()
    graph = _build_graph(state)
    config = _config("rejected-sql")
    feedback = "Group customers by country instead."

    interrupted = graph.invoke(
        {"messages": [{"role": "user", "content": "List artists"}]},
        config,
    )
    assert interrupted["__interrupt__"]

    approval = _extract_approval(interrupted["__interrupt__"])
    revised_interrupt = graph.invoke(
        decisions_to_command(
            approval,
            [Decision(action="reject", feedback=feedback)],
        ),
        config,
    )

    assert revised_interrupt["__interrupt__"]
    action = revised_interrupt["__interrupt__"][0].value[
        "action_requests"
    ][0]
    assert action["args"]["query"] == REVISED_SQL
    assert feedback in (state.rejection_feedback or "")
    assert state.validation_retry_seen is True
    assert state.executed == []

    revised_approval = _extract_approval(revised_interrupt["__interrupt__"])
    completed = graph.invoke(
        decisions_to_command(
            revised_approval,
            [Decision(action="approve")],
        ),
        config,
    )

    assert "__interrupt__" not in completed
    assert state.executed == [REVISED_SQL]


def test_parallel_sql_interrupts_are_reviewed_sequentially_by_id() -> None:
    state = ScriptState()
    graph = _build_graph(
        state,
        coordinator_model=ParallelCoordinatorModel(
            role="coordinator",
            script_state=state,
        ),
    )
    config = _config("parallel-sql-reviews")

    interrupted = graph.invoke(
        {"messages": [{"role": "user", "content": "Create a report"}]},
        config,
    )
    pending = interrupted["__interrupt__"]
    assert len(pending) == 2
    assert pending[0].id != pending[1].id
    assert state.executed == []

    first_approval = _extract_approval([pending[0]])
    after_first = graph.invoke(
        decisions_to_command(first_approval, [Decision(action="approve")]),
        config,
    )

    remaining = after_first["__interrupt__"]
    assert len(remaining) == 1
    assert remaining[0].id == pending[1].id
    assert state.executed == [GENERATED_SQL]

    second_approval = _extract_approval(list(remaining))
    completed = graph.invoke(
        decisions_to_command(second_approval, [Decision(action="approve")]),
        config,
    )

    assert "__interrupt__" not in completed
    assert state.executed == [GENERATED_SQL, GENERATED_SQL]
