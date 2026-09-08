"""Actual Deep Agents wiring, with a deterministic local model (no provider I/O)."""

import json
import re
from dataclasses import replace
from pathlib import Path
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from data_analytics_agent.api import Services


class AnalystModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "local-analyst-workflow-test"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = " ".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )
        tools = [m for m in messages if isinstance(m, ToolMessage)]

        def call(name, args, id):
            return AIMessage(
                content="", tool_calls=[{"name": name, "args": args, "id": id}]
            )

        if "You are the text-to-SQL specialist" in system:
            evidence = next((m for m in tools if m.name == "execute_sql"), None)
            if not evidence:
                message = call(
                    "execute_sql",
                    {
                        "query": "SELECT COUNT(*) AS artists FROM Artist",
                        "purpose": "Count artists",
                    },
                    "source-count",
                )
            else:
                payload = json.loads(evidence.content)
                message = call(
                    "SQLAnalysisResponse",
                    {
                        "answer": "There are no artists in the test table.",
                        "sql": payload["executed_sql"],
                        "result_id": payload["result_id"],
                    },
                    "sql-answer",
                )
        else:
            assignment = next((m for m in tools if m.name == "task"), None)
            if not assignment:
                message = call(
                    "task",
                    {
                        "description": "Count all artists in the configured source using SQL.",
                        "subagent_type": "text-to-sql",
                    },
                    "retrieve-artists",
                )
            else:
                match = re.search(
                    r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}",
                    str(assignment.content),
                )
                assert match, str(assignment.content)
                result = match.group()
                findings = {
                    "answer": "There are no artists in the test table.",
                    "primary_result_id": result,
                    "supporting_result_ids": [result],
                }
                if not any(m.name == "publish_findings" for m in tools):
                    message = call(
                        "publish_findings", {"findings": findings}, "publish"
                    )
                elif not any(m.name == "create_report" for m in tools):
                    message = call(
                        "create_report",
                        {
                            "report_json": json.dumps(
                                {
                                    "title": "Artist count",
                                    "blocks": [
                                        {
                                            "type": "narrative",
                                            "body": findings["answer"],
                                        },
                                        {
                                            "type": "table",
                                            "title": "Evidence",
                                            "result_id": result,
                                        },
                                    ],
                                }
                            )
                        },
                        "report",
                    )
                else:
                    report = next(m for m in tools if m.name == "create_report")
                    assert json.loads(report.content)["ok"], report.content
                    message = AIMessage(content=json.dumps(findings))
        return ChatResult(generations=[ChatGeneration(message=message)])


async def test_descriptive_question_through_real_harness_produces_report(
    test_settings, monkeypatch
):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    from data_analytics_agent import coordinator

    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *args, **kwargs: AnalystModel()
    )
    # Keep the isolated source configuration and use the real project instructions/skills.
    import shutil

    root = Path(__file__).parents[1]
    shutil.copy(root / "AGENTS.md", test_settings.project_root / "AGENTS.md")
    shutil.copytree(root / "skills", test_settings.project_root / "skills")
    services = Services(
        settings=replace(
            test_settings, require_sql_approval=False, require_python_approval=False
        )
    )
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "How many artists are there?")
    services.conversations.begin_run(thread, run)
    await services.manager().start(run)
    state = services.runs.get(run)
    assert state.status == "completed", state.error
    assert state.answer.report and state.findings
    assert not state.answer.analyses and not services.runs.get_python_execution(run)
    assert services.results.get_unscoped(state.answer.primary_result_id).rows == [
        {"artists": 0}
    ]

    calls = {
        e.tool.call_id: e for e in state.events if e.tool and e.phase == "completed"
    }
    assert calls["source-count"].tool.name == "execute_sql"
    assert calls["source-count"].agent == "text-to-sql"
    assert calls["retrieve-artists"].agent == "coordinator"
    assert calls["report"].tool.name == "create_report"
    assert all(e.duration_ms is not None for e in calls.values())
    assert not {
        "get_semantic_context",
        "write_todos",
        "save_investigation",
        "execute_analysis_python",
    } & {e.tool.name for e in calls.values()}
    assert not any(
        e.agent == "text-to-sql" and e.tool.name == "read_file" for e in calls.values()
    )
    trace = {
        "scenario": "synthetic scalar, deterministic scripted model",
        "diagnostics": state.run_diagnostics.model_dump(mode="json"),
        "calls": [
            {"agent": e.agent, "tool": e.tool.name, "duration_ms": e.duration_ms}
            for e in calls.values()
        ],
        "findings_published": bool(state.findings),
        "report_available": bool(state.answer.report),
    }
    (test_settings.project_root / "efficiency-trace.json").write_text(
        json.dumps(trace, indent=2)
    )


def test_tool_failures_keep_identity_and_record_failed_duration(workspace):
    from data_analytics_agent.diagnostics import RunDiagnosticsCallback

    callback = RunDiagnosticsCallback(workspace.runs, workspace.run)
    for identifier, handled in [("handled", True), ("exception", False)]:
        callback.on_tool_start(
            {"name": "execute_analysis_python"},
            "{}",
            run_id=identifier,
            metadata={"lc_agent_name": "data-analysis"},
            inputs={"inputs": {"sales": "saved-id"}},
            tool_call_id=identifier,
        )
        if handled:
            callback.on_tool_end(
                ToolMessage(
                    content='{"ok":false,"error":"Repair this code"}',
                    tool_call_id=identifier,
                ),
                run_id=identifier,
            )
        else:
            callback.on_tool_error(ValueError("Invalid execution"), run_id=identifier)
    events = workspace.runs.get(workspace.run).events
    failed = [event for event in events if event.phase == "failed"]
    assert len(failed) == 2
    assert all(event.agent == "data-analysis" for event in failed)
    assert all(event.tool.name == "execute_analysis_python" for event in failed)
    assert all(event.duration_ms is not None for event in failed)


def test_owner_prompts_keep_only_analysis_and_report_skills(test_settings, monkeypatch):
    from data_analytics_agent import coordinator

    services = Services(settings=test_settings)
    monkeypatch.setattr(coordinator, "create_deep_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(coordinator, "_build_chat_model", lambda *args: AnalystModel())
    specification = coordinator.build_agent(
        test_settings,
        services.results,
        services.runs,
        source=services.source("test"),
        semantic_catalog=services.semantic_catalog_for_source("test"),
        backend=services.backend_for_source("test"),
    )
    assert specification["skills"] == ["/project/skills/reporting/"]
    specialists = {s["name"]: s for s in specification["subagents"]}
    assert "skills" not in specialists["text-to-sql"]
    assert specialists["data-analysis"]["skills"] == ["/project/skills/analysis/"]
    assert (
        "Complete exact catalog definitions"
        in specialists["text-to-sql"]["system_prompt"]
    )
    assert "execute_sql" not in {t.name for t in specification["tools"]}
    assert "execute_sql" not in {t.name for t in specialists["data-analysis"]["tools"]}
    disabled = coordinator.build_agent(
        replace(test_settings, enable_data_visualization=False),
        services.results,
        services.runs,
        source=services.source("test"),
        semantic_catalog=services.semantic_catalog_for_source("test"),
        backend=services.backend_for_source("test"),
    )
    assert "Use create_chart for purposeful charts" not in disabled["system_prompt"]
    assert "create_chart" not in {t.name for t in disabled["tools"]}
