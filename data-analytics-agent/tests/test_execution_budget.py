from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.middleware.model_call_limit import (
    ModelCallLimitExceededError,
    ModelCallLimitMiddleware,
)
from langchain.agents.middleware.tool_call_limit import (
    ToolCallLimitExceededError,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
import pytest

from data_analytics_agent.agents.text_to_sql.agent import (
    build_text_to_sql_subagent,
)
from data_analytics_agent.backends import create_backend
from data_analytics_agent.config import Settings
from data_analytics_agent.data_sources import load_data_source_catalog
from data_analytics_agent.execution_budget import (
    execution_budget_middleware,
)
from data_analytics_agent.stores import ResultStore


@pytest.fixture(autouse=True)
def disable_langsmith_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


class LoopingToolModel(BaseChatModel):
    calls: int = 0
    parallel: bool = False

    @property
    def _llm_type(self) -> str:
        return "execution-budget-test"

    def bind_tools(self, _tools: Any, **_kwargs: Any) -> LoopingToolModel:
        return self

    def _generate(
        self,
        _messages: list[BaseMessage],
        **_kwargs: Any,
    ) -> ChatResult:
        self.calls += 1
        tool_calls = [
            {
                "name": "ping",
                "args": {"value": self.calls},
                "id": f"ping-{self.calls}-1",
            }
        ]
        if self.parallel:
            tool_calls.append(
                {
                    "name": "ping",
                    "args": {"value": self.calls},
                    "id": f"ping-{self.calls}-2",
                }
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content="", tool_calls=tool_calls)
                )
            ]
        )


class ReviewingModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "execution-budget-hitl-test"

    def bind_tools(self, _tools: Any, **_kwargs: Any) -> ReviewingModel:
        return self

    def _generate(
        self,
        _messages: list[BaseMessage],
        **_kwargs: Any,
    ) -> ChatResult:
        self.calls += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "execute_sql",
                                "args": {
                                    "query": f"SELECT {self.calls}"
                                },
                                "id": f"execute-{self.calls}",
                            }
                        ],
                    )
                )
            ]
        )


@tool
def ping(value: int) -> int:
    """Return one integer."""

    return value


@tool
def execute_sql(query: str) -> str:
    """Execute reviewed SQL."""

    return query


def test_settings_use_confirmed_budget_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = [
        "COORDINATOR_MODEL_CALL_LIMIT",
        "COORDINATOR_TOOL_CALL_LIMIT",
        "COORDINATOR_TASK_CALL_LIMIT",
        "SQL_AGENT_MODEL_CALL_LIMIT",
        "SQL_AGENT_TOOL_CALL_LIMIT",
        "SQL_EXECUTE_CALL_LIMIT",
        "VISUALIZATION_AGENT_MODEL_CALL_LIMIT",
        "VISUALIZATION_AGENT_TOOL_CALL_LIMIT",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.coordinator_model_call_limit == 12
    assert settings.coordinator_tool_call_limit == 12
    assert settings.coordinator_task_call_limit == 4
    assert settings.sql_agent_model_call_limit == 24
    assert settings.sql_agent_tool_call_limit == 30
    assert settings.sql_execute_call_limit == 3
    assert settings.visualization_agent_model_call_limit == 12
    assert settings.visualization_agent_tool_call_limit == 16


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_budget_settings_require_positive_integers(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("COORDINATOR_MODEL_CALL_LIMIT", value)

    with pytest.raises(ValueError, match="positive integer"):
        Settings()


def test_budget_factory_uses_strict_lifecycle_limits() -> None:
    middleware = execution_budget_middleware(
        model_calls=12,
        tool_calls=12,
        specific_tool_calls={"task": 4},
    )

    assert isinstance(middleware[0], ModelCallLimitMiddleware)
    assert middleware[0].thread_limit == 12
    assert middleware[0].run_limit is None
    assert middleware[0].exit_behavior == "error"
    assert isinstance(middleware[1], ToolCallLimitMiddleware)
    assert middleware[1].thread_limit == 12
    assert middleware[1].tool_name is None
    assert isinstance(middleware[2], ToolCallLimitMiddleware)
    assert middleware[2].thread_limit == 4
    assert middleware[2].tool_name == "task"


def test_sql_agent_checks_budgets_before_requesting_review(
    test_settings: Settings,
) -> None:
    catalog = load_data_source_catalog(
        test_settings.project_root,
        config_path=test_settings.data_sources_config_path,
    )
    source = catalog.get("test")
    budget_middleware = execution_budget_middleware(
        model_calls=24,
        tool_calls=30,
        specific_tool_calls={"execute_sql": 3},
    )

    spec = build_text_to_sql_subagent(
        source=source,
        backend=create_backend(source, test_settings.project_root),
        result_store=ResultStore(),
        model=ReviewingModel(),
        permissions=[],
        middleware=budget_middleware,
    )

    middleware = spec["middleware"]
    assert isinstance(middleware[0], HumanInTheLoopMiddleware)
    assert isinstance(middleware[1], ModelCallLimitMiddleware)
    assert isinstance(middleware[2], ToolCallLimitMiddleware)
    assert middleware[2].tool_name is None
    assert isinstance(middleware[3], ToolCallLimitMiddleware)
    assert middleware[3].tool_name == "execute_sql"
    assert "interrupt_on" not in spec


def test_model_budget_resets_for_a_new_thread() -> None:
    model = LoopingToolModel()
    agent = create_agent(
        model,
        tools=[ping],
        middleware=execution_budget_middleware(
            model_calls=2,
            tool_calls=10,
        ),
        checkpointer=InMemorySaver(),
    )

    for thread_id in ("first-user-run", "second-user-run"):
        with pytest.raises(ModelCallLimitExceededError):
            agent.invoke(
                {"messages": [{"role": "user", "content": "Loop"}]},
                {"configurable": {"thread_id": thread_id}},
            )

    assert model.calls == 4


def test_over_budget_parallel_batch_executes_nothing() -> None:
    executed: list[int] = []

    @tool
    def tracked_ping(value: int) -> int:
        """Record and return an integer."""

        executed.append(value)
        return value

    model = LoopingToolModel(parallel=True)
    agent = create_agent(
        model,
        tools=[tracked_ping],
        middleware=[
            ToolCallLimitMiddleware(
                thread_limit=1,
                exit_behavior="error",
            )
        ],
    )

    with pytest.raises(ToolCallLimitExceededError):
        agent.invoke(
            {"messages": [{"role": "user", "content": "Call twice"}]}
        )

    assert executed == []


def test_budget_counts_persist_across_hitl_resume() -> None:
    model = ReviewingModel()
    agent = create_agent(
        model,
        tools=[execute_sql],
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "execute_sql": {
                        "allowed_decisions": ["approve", "reject"]
                    }
                }
            ),
            ToolCallLimitMiddleware(
                tool_name="execute_sql",
                thread_limit=1,
                exit_behavior="error",
            ),
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "review-budget"}}

    interrupted = agent.invoke(
        {"messages": [{"role": "user", "content": "Query"}]},
        config,
    )
    assert interrupted["__interrupt__"]

    with pytest.raises(ToolCallLimitExceededError):
        agent.invoke(
            Command(
                resume={
                    "decisions": [
                        {"type": "reject", "message": "Revise it"}
                    ]
                }
            ),
            config,
        )

    assert model.calls == 2


def test_model_budget_persists_across_hitl_resume() -> None:
    model = ReviewingModel()
    agent = create_agent(
        model,
        tools=[execute_sql],
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "execute_sql": {
                        "allowed_decisions": ["approve", "reject"]
                    }
                }
            ),
            ModelCallLimitMiddleware(
                thread_limit=1,
                exit_behavior="error",
            ),
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "review-model-budget"}}

    interrupted = agent.invoke(
        {"messages": [{"role": "user", "content": "Query"}]},
        config,
    )
    assert interrupted["__interrupt__"]

    with pytest.raises(ModelCallLimitExceededError):
        agent.invoke(
            Command(
                resume={
                    "decisions": [
                        {"type": "reject", "message": "Revise it"}
                    ]
                }
            ),
            config,
        )

    assert model.calls == 1
