from __future__ import annotations

from unittest.mock import Mock, patch

from general_agent.agent import build_agent
from general_agent.workspace import Workspace


def test_agent_construction_retains_default_subagent_and_budgets(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    backend = Mock()
    checkpointer = Mock()
    with (
        patch("general_agent.agent.init_chat_model", return_value="model") as init,
        patch("general_agent.agent.create_deep_agent", return_value="graph") as create,
    ):
        assert build_agent(
            settings, workspace=workspace, backend=backend, checkpointer=checkpointer
        ) == "graph"
    init.assert_called_once_with("test:model", streaming=False)
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "general-agent"
    assert "memory" not in kwargs
    assert kwargs["skills"] == ["/skills/"]
    assert kwargs["backend"] is backend
    assert kwargs["checkpointer"] is checkpointer
    assert "subagents" not in kwargs
    assert kwargs["tools"] == []
    middleware_names = [type(item).__name__ for item in kwargs["middleware"]]
    assert middleware_names.count("TodoListMiddleware") == 1
    assert middleware_names.count("ToolCallLimitMiddleware") == 2


def test_openai_model_uses_responses_api_unless_explicitly_overridden(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    settings_with_openai = type(settings)(
        project_root=settings.project_root,
        model_name="openai:gpt-5.6-luna",
    )
    with (
        patch("general_agent.agent.init_chat_model", return_value="model") as init,
        patch("general_agent.agent.create_deep_agent", return_value="graph"),
    ):
        build_agent(
            settings_with_openai,
            workspace=workspace,
            backend=Mock(),
            checkpointer=Mock(),
        )
    init.assert_called_once_with(
        "openai:gpt-5.6-luna",
        streaming=False,
        use_responses_api=True,
    )

    explicit = type(settings)(
        project_root=settings.project_root,
        model_name="openai:gpt-5.6-luna",
        model_kwargs={"use_responses_api": False, "streaming": True},
    )
    with (
        patch("general_agent.agent.init_chat_model", return_value="model") as init,
        patch("general_agent.agent.create_deep_agent", return_value="graph"),
    ):
        build_agent(
            explicit,
            workspace=workspace,
            backend=Mock(),
            checkpointer=Mock(),
        )
    init.assert_called_once_with(
        "openai:gpt-5.6-luna",
        streaming=False,
        use_responses_api=False,
    )
