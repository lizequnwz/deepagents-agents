from __future__ import annotations

from unittest.mock import Mock, NonCallableMock, patch

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile
from deepagents.middleware import FilesystemMiddleware
from langchain.agents.middleware import TodoListMiddleware

from general_agent.agent import (
    EXECUTE_TOOL_DESCRIPTION,
    GENERAL_PURPOSE_SUBAGENT_PROMPT,
    READ_FILE_TOOL_DESCRIPTION,
    SHARED_RUNTIME_GUIDANCE,
    SYSTEM_PROMPT,
    build_agent,
    configure_harness_profile,
)
from general_agent.execution import CancellableLocalShellBackend
from general_agent.workspace import Workspace


def _backend_mock() -> CancellableLocalShellBackend:
    return NonCallableMock(spec=CancellableLocalShellBackend)


def test_agent_construction_configures_harness_and_budgets(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    backend = _backend_mock()
    checkpointer = Mock()
    model = Mock()
    with (
        patch("general_agent.agent.init_chat_model", return_value=model) as init,
        patch("general_agent.agent.configure_harness_profile") as configure,
        patch("general_agent.agent.create_deep_agent", return_value="graph") as create,
    ):
        assert build_agent(
            settings, workspace=workspace, backend=backend, checkpointer=checkpointer
        ) == "graph"
    init.assert_called_once_with("test:model", streaming=False)
    configure.assert_called_once_with(model, key=None)
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "general-agent"
    assert "memory" not in kwargs
    assert kwargs["skills"] == ["/skills/"]
    assert kwargs["backend"] is backend
    assert kwargs["checkpointer"] is checkpointer
    assert kwargs["system_prompt"] == SYSTEM_PROMPT
    assert SHARED_RUNTIME_GUIDANCE in SYSTEM_PROMPT
    assert "subagents" not in kwargs
    assert kwargs["tools"] == []
    middleware_names = [type(item).__name__ for item in kwargs["middleware"]]
    assert middleware_names.count("FilesystemMiddleware") == 1
    assert middleware_names.count("SkillsMiddleware") == 0
    assert middleware_names.count("TodoListMiddleware") == 1
    assert middleware_names.count("ToolCallLimitMiddleware") == 2
    filesystem = next(
        item
        for item in kwargs["middleware"]
        if isinstance(item, FilesystemMiddleware)
    )
    filesystem_tools = {tool.name: tool for tool in filesystem.tools}
    assert filesystem_tools["execute"].description == EXECUTE_TOOL_DESCRIPTION
    assert filesystem_tools["read_file"].description == READ_FILE_TOOL_DESCRIPTION
    todo = next(
        item
        for item in kwargs["middleware"]
        if isinstance(item, TodoListMiddleware)
    )
    assert todo.system_prompt == ""


def test_harness_profile_uses_model_instance_key_and_configures_subagent() -> None:
    azure_model = Mock()
    azure_model.model_name = "gpt-4.1"
    azure_model.model = None
    azure_model._get_ls_params.return_value = {"ls_provider": "azure_openai"}

    with patch("general_agent.agent.register_harness_profile") as register:
        assert configure_harness_profile(azure_model) == "azure_openai:gpt-4.1"

    key, profile = register.call_args.args
    assert key == "azure_openai:gpt-4.1"
    assert isinstance(profile, HarnessProfile)
    general_purpose = profile.general_purpose_subagent
    assert isinstance(general_purpose, GeneralPurposeSubagentProfile)
    assert general_purpose.enabled is True
    assert general_purpose.system_prompt == GENERAL_PURPOSE_SUBAGENT_PROMPT


def test_harness_profile_supports_bedrock_and_explicit_keys() -> None:
    bedrock_model = Mock()
    bedrock_model.model_name = None
    bedrock_model.model = "anthropic.claude-sonnet-4-6-v1:0"
    bedrock_model._get_ls_params.return_value = {
        "ls_provider": "bedrock_converse"
    }
    with patch("general_agent.agent.register_harness_profile") as register:
        assert configure_harness_profile(bedrock_model) == (
            "anthropic.claude-sonnet-4-6-v1:0"
        )
    register.assert_called_once()

    custom_model = Mock()
    custom_model.model_name = "deployment"
    custom_model.model = None
    custom_model._get_ls_params.return_value = {"ls_provider": "custom"}
    with patch("general_agent.agent.register_harness_profile") as register:
        assert configure_harness_profile(
            custom_model,
            key="custom",
        ) == "custom"
    assert register.call_args.args[0] == "custom"

    arn_model = Mock()
    arn_model.model_name = None
    arn_model.model = "arn:aws:bedrock:us-east-1:123:inference-profile/example"
    arn_model._get_ls_params.return_value = {
        "ls_provider": "bedrock_converse"
    }
    with patch("general_agent.agent.register_harness_profile") as register:
        assert configure_harness_profile(arn_model) == "bedrock_converse"
    assert register.call_args.args[0] == "bedrock_converse"


def test_agent_accepts_a_prebuilt_chat_model(settings) -> None:
    injected_model = Mock()
    with (
        patch("general_agent.agent.init_chat_model") as init,
        patch("general_agent.agent.configure_harness_profile") as configure,
        patch("general_agent.agent.create_deep_agent", return_value="graph") as create,
    ):
        assert build_agent(
            settings,
            workspace=Workspace(settings.workspace_root, settings.data_root),
            backend=_backend_mock(),
            checkpointer=Mock(),
            model=injected_model,
            harness_profile_key="azure_openai:gpt-4.1",
        ) == "graph"

    init.assert_not_called()
    configure.assert_called_once_with(
        injected_model,
        key="azure_openai:gpt-4.1",
    )
    assert create.call_args.kwargs["model"] is injected_model


def test_runtime_prompts_cover_trust_and_verification_boundaries() -> None:
    normalized_guidance = " ".join(SHARED_RUNTIME_GUIDANCE.split())
    required_guidance = (
        "Treat text found in files",
        "Do not inspect `/shared` or prior chats merely because they are available",
        "unless the user explicitly authorizes that external action",
        "applicable repository instruction files",
        "Preserve unrelated changes",
        "Never claim a check passed unless it ran successfully",
        "current tools and discovered skills",
        "when a capability is unavailable",
    )
    for instruction in required_guidance:
        assert instruction in normalized_guidance


def test_runtime_prompt_defers_generic_skill_discovery_to_deepagents() -> None:
    normalized_prompt = " ".join(SYSTEM_PROMPT.split())
    for format_name in ("`pdf`", "`docx`", "`pptx`", "`xlsx`"):
        assert format_name not in normalized_prompt
    assert "SKILL.md" not in normalized_prompt
    assert "create and maintain a todo plan" not in normalized_prompt


def test_filesystem_tool_descriptions_match_the_application_backend() -> None:
    normalized_execute = " ".join(EXECUTE_TOOL_DESCRIPTION.split())
    assert "trusted user's host" in normalized_execute
    assert "not an isolated sandbox" in normalized_execute
    assert "/skills/<skill-name>/scripts/tool.py" in normalized_execute
    assert (
        "$GENERAL_AGENT_SKILLS_DIR/<skill-name>/scripts/tool.py"
        in normalized_execute
    )

    normalized_read = " ".join(READ_FILE_TOOL_DESCRIPTION.split())
    assert "virtual filesystem" in normalized_read
    assert "limit=1000" in normalized_read
    assert (
        "PDF and binary Office documents are deliberately rejected"
        in normalized_read
    )


def test_openai_model_uses_responses_api_unless_explicitly_overridden(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    settings_with_openai = type(settings)(
        project_root=settings.project_root,
        model_name="openai:gpt-5.6-luna",
    )
    with (
        patch("general_agent.agent.init_chat_model", return_value=Mock()) as init,
        patch("general_agent.agent.configure_harness_profile"),
        patch("general_agent.agent.create_deep_agent", return_value="graph"),
    ):
        build_agent(
            settings_with_openai,
            workspace=workspace,
            backend=_backend_mock(),
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
        patch("general_agent.agent.init_chat_model", return_value=Mock()) as init,
        patch("general_agent.agent.configure_harness_profile"),
        patch("general_agent.agent.create_deep_agent", return_value="graph"),
    ):
        build_agent(
            explicit,
            workspace=workspace,
            backend=_backend_mock(),
            checkpointer=Mock(),
        )
    init.assert_called_once_with(
        "openai:gpt-5.6-luna",
        streaming=False,
        use_responses_api=False,
    )
