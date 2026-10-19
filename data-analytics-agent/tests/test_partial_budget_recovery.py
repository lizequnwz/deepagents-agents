"""Native framework limits preserve evidence and reserve bounded presentation."""

from dataclasses import replace
from pathlib import Path
import shutil

from langchain_core.messages import ToolMessage
import pytest

from data_analytics_agent.api import Services
from data_analytics_agent import coordinator
from tests.test_agent_workflow import AnalystModel


class RecoveryModel(AnalystModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # Repair blocked proposals rather than mistaking an error for success.
        return super()._generate(
            [
                message
                for message in messages
                if not isinstance(message, ToolMessage) or message.status != "error"
            ],
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


@pytest.mark.parametrize(
    "limits",
    [
        {"coordinator_model_call_limit": 1},
        {"coordinator_tool_call_limit": 1},
        {"sql_agent_model_call_limit": 1},
        {"sql_agent_tool_call_limit": 1},
    ],
)
async def test_native_hard_limit_yields_partial_report_without_resetting_counts(
    test_settings, monkeypatch, limits
):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    root = Path(__file__).parents[1]
    shutil.copy(root / "AGENTS.md", test_settings.project_root / "AGENTS.md")
    shutil.copytree(root / "skills", test_settings.project_root / "skills")
    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *a, **k: RecoveryModel()
    )
    services = Services(settings=replace(test_settings, **limits))
    thread = services.conversations.create("test")
    run_id = services.runs.create(thread, "test", "How many artists are there?")
    services.conversations.begin_run(thread, run_id)
    await services.manager().start(run_id)
    run = services.runs.get(run_id)
    assert run.status == "completed", run.error
    assert run.answer.partial and run.answer.unresolved_questions
    assert run.answer.report
    report = services.reports.get(run.answer.report.report_id, thread)
    assert "Partial investigation" in report.html
    assert len(services.results.list_for_conversation(thread, source_id="test")) == 1
    assert services.runs.analysis_stop_reason(run_id)
    state = await services.agent_for_source("test").aget_state(
        {"configurable": {"thread_id": run_id}}
    )
    if "coordinator_model_call_limit" in limits:
        assert 1 < state.values["thread_model_call_count"] <= 9
    if "coordinator_tool_call_limit" in limits:
        assert 1 < state.values["thread_tool_call_count"]["__all__"] <= 17
    stored = services.runs._get_mutable(run_id)
    assert stored.presentation_model_calls <= 8 and stored.presentation_tool_calls <= 16
