from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from deepagents import GeneralPurposeSubagentProfile, HarnessProfile
from deepagents.middleware import FilesystemMiddleware
from langchain.agents.middleware import ToolErrorMiddleware

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.index import ReferenceDataQualityError
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource
from general_agent.advisor_tools import build_advisor_tools
from general_agent.agent import (
    READ_FILE_TOOL_DESCRIPTION,
    SHARED_RUNTIME_GUIDANCE,
    SYSTEM_PROMPT,
    _recoverable_tool_error,
    build_agent,
    configure_harness_profile,
)
from general_agent.store import Store
from general_agent.workspace import Workspace


def test_agent_construction_is_advisor_only(settings) -> None:
    workspace = Workspace(settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    store = Store(settings.application_db, settings.data_root)
    source_path = settings.project_root / "master.csv"
    source = SyntheticAdvisorReferenceSource(source_path)
    model = Mock()
    advisor_tool = Mock(name="advisor_tool")
    with (
        patch("general_agent.agent.init_chat_model", return_value=model),
        patch("general_agent.agent.configure_harness_profile") as configure,
        patch("general_agent.agent.build_advisor_tools", return_value=[advisor_tool]),
        patch("general_agent.agent.create_deep_agent", return_value="graph") as create,
    ):
        assert build_agent(
            settings, workspace=workspace, backend=backend, store=store,
            advisor_source=source, checkpointer=Mock(),
        ) == "graph"
    store.close()
    configure.assert_called_once_with(model, key=None)
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "advisor-match-agent"
    assert kwargs["tools"] == [advisor_tool]
    assert kwargs["skills"] == ["/skills/"]
    middleware = kwargs["middleware"]
    filesystem = next(item for item in middleware if isinstance(item, FilesystemMiddleware))
    assert {tool.name for tool in filesystem.tools} == {"ls", "read_file", "glob"}
    assert any(isinstance(item, ToolErrorMiddleware) for item in middleware)
    assert "task" not in {getattr(item, "tool_name", None) for item in middleware}


def test_harness_profile_disables_general_purpose_subagent() -> None:
    model = Mock()
    model.model_name = "gpt-test"
    model.model = None
    model._get_ls_params.return_value = {"ls_provider": "openai"}
    with patch("general_agent.agent.register_harness_profile") as register:
        configure_harness_profile(model)
    _, profile = register.call_args.args
    assert isinstance(profile, HarnessProfile)
    assert isinstance(profile.general_purpose_subagent, GeneralPurposeSubagentProfile)
    assert profile.general_purpose_subagent.enabled is False


def test_expected_tool_errors_are_returned_for_correction() -> None:
    request = Mock()
    request.tool.name = "list_advisor_match_results"
    message = _recoverable_tool_error(ValueError("bad status"), request)
    assert message == (
        "list_advisor_match_results could not complete: bad status. "
        "Correct the input and retry."
    )
    assert _recoverable_tool_error(RuntimeError("internal failure"), request) is None
    blocker = _recoverable_tool_error(
        ReferenceDataQualityError({"DUP-1": 2}), request
    )
    assert "authoritative advisor source" in blocker
    assert "do not change the uploaded input" in blocker
    assert "Correct the input and retry" not in blocker


def test_prompt_enforces_matching_and_review_boundaries() -> None:
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert SHARED_RUNTIME_GUIDANCE in SYSTEM_PROMPT
    for required in (
        "Your purpose", "advisor-match skill", "never decide identities row by row",
        "exact column indexes and observed headers",
        "Always call the mapping-validation tool before matching",
        "pass that exact text as `all_rows_firm` in the same turn",
        "Do not ask the user to repeat it",
        "firm_clarification_required",
        "authoritative source must be corrected",
        "get_current_advisor_input",
        "Never overwrite the original upload",
        "retrieves or reuses the attachment's authoritative snapshot internally",
        "Treat the returned manifest and snapshot ID as opaque",
        "qualitative supporting and conflicting evidence",
        "unlisted advisor requires an exact user-supplied CRD",
        "correct the input and retry", "profile building is not implemented",
        "Refuse unrelated",
    ):
        assert required in normalized
    for unsupported in ("pip install", "Delegate only", "general-purpose subagent"):
        assert unsupported not in normalized


def test_read_file_description_is_skill_only() -> None:
    normalized = " ".join(READ_FILE_TOOL_DESCRIPTION.split())
    assert "Only `/skills/...` is available" in normalized
    assert "limit=1000" in normalized


def test_advisor_tool_schemas_do_not_expose_runtime_or_host_paths(settings) -> None:
    workspace = Workspace(settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    store = Store(settings.application_db, settings.data_root)
    tools = build_advisor_tools(
        settings=settings, workspace=workspace, backend=backend, store=store,
        advisor_source=SyntheticAdvisorReferenceSource(Path("missing")),
    )
    store.close()
    assert {item.name for item in tools} == {
        "inspect_advisor_upload",
        "validate_advisor_input",
        "get_current_advisor_input",
        "create_advisor_match",
        "get_current_advisor_match",
        "list_advisor_match_results",
        "propose_crd_match",
        "apply_advisor_match_decisions",
    }
    for item in tools:
        fields = item.args_schema.model_fields
        assert "runtime" not in fields
        assert "host_path" not in fields
    create_match = next(item for item in tools if item.name == "create_advisor_match")
    assert "reference_snapshot_id" not in create_match.args_schema.model_fields
    assert {"all_rows_firm", "firm_resolution"} <= set(
        create_match.args_schema.model_fields
    )


@pytest.mark.asyncio
async def test_backend_has_no_shell_and_rejects_non_skill_paths(settings) -> None:
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    assert not hasattr(backend, "execute")
    async with backend.run_scope("run-test", "A123456", "chat-test"):
        with pytest.raises(ValueError, match="installed skills only"):
            backend._resolve_path("/attachments/advisors.csv")


def test_openai_model_uses_responses_api(settings) -> None:
    configured = type(settings)(project_root=settings.project_root, model_name="openai:gpt-test")
    workspace = Workspace(settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    store = Store(settings.application_db, settings.data_root)
    with (
        patch("general_agent.agent.init_chat_model", return_value=Mock()) as init,
        patch("general_agent.agent.configure_harness_profile"),
        patch("general_agent.agent.build_advisor_tools", return_value=[]),
        patch("general_agent.agent.create_deep_agent", return_value="graph"),
    ):
        build_agent(
            configured, workspace=workspace, backend=backend, store=store,
            advisor_source=SyntheticAdvisorReferenceSource(Path("missing")),
            checkpointer=Mock(),
        )
    store.close()
    init.assert_called_once_with("openai:gpt-test", streaming=False, use_responses_api=True)
