"""Real native subagent fan-out, durable tools and separate human reviews."""

import asyncio
import json
import re
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from data_analytics_agent.api import Services
from data_analytics_agent.approvals import decisions_to_command
from data_analytics_agent.schemas import Decision
from tests.test_agent_workflow import AnalystModel


class ParallelAnalyst(AnalystModel):
    dataset: str
    branches: int = 3

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        call_names = {
            c["id"]: c["name"]
            for m in messages
            if isinstance(m, AIMessage)
            for c in m.tool_calls
        }
        tools = [
            m.model_copy(update={"name": m.name or call_names.get(m.tool_call_id)})
            for m in messages
            if isinstance(m, ToolMessage)
        ]
        system = " ".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )

        def call(name, args, identity):
            return AIMessage(
                content="", tool_calls=[{"name": name, "args": args, "id": identity}]
            )

        if "You are the data-analysis specialist" in system:
            brief = next(
                str(m.content) for m in messages if isinstance(m, HumanMessage)
            )
            branch = int(re.search(r"branch=(\d+)", brief)[1])
            executions = [m for m in tools if m.name == "execute_analysis_python"]
            finished = [m for m in tools if m.name == "finish_analysis"]
            if finished:
                raise AssertionError(
                    "Saved analyses must return directly without another model call"
                )
            elif executions:
                payload = json.loads(executions[-1].content)
                assert payload["ok"], payload
                message = call(
                    "finish_analysis",
                    {
                        "outcome": "analysis_completed",
                        "answer": f"Branch {branch}",
                        "method": "Synthetic isolated calculation",
                    },
                    "same-finish-id",
                )
            else:
                # Deliberately identical tool IDs in different workers.
                message = call(
                    "execute_analysis_python",
                    {
                        "inputs": {"sales": self.dataset},
                        "code": f"analysis_outputs = {{'value': float(datasets['sales']['amount'].sum()) * {branch}}}",
                    },
                    "same-python-id",
                )
        else:
            tasks = [m for m in tools if m.name == "task"]
            if not any(m.name == "write_todos" for m in tools):
                message = call(
                    "write_todos",
                    {
                        "todos": [
                            {
                                "content": "Run independent saved-data analyses",
                                "status": "in_progress",
                            },
                            {
                                "content": "Synthesize findings and create report",
                                "status": "pending",
                            },
                        ]
                    },
                    "plan",
                )
            elif len(tasks) < self.branches:
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "id": f"branch-{n}",
                            "args": {
                                "subagent_type": "data-analysis",
                                "description": f"Analyze independently branch={n}, saved input {self.dataset}.",
                            },
                        }
                        for n in range(1, self.branches + 1)
                    ],
                )
            else:
                ids = [json.loads(m.content)["analysis_id"] for m in tasks]
                findings = {
                    "answer": "Independent analyses finished.",
                    "primary_result_id": self.dataset,
                    "analysis_ids": ids,
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
                                    "title": "Parallel analyses",
                                    "blocks": [
                                        {
                                            "type": "narrative",
                                            "body": findings["answer"],
                                        }
                                    ],
                                }
                            )
                        },
                        "report",
                    )
                else:
                    assert json.loads(
                        next(m.content for m in tools if m.name == "create_report")
                    )["ok"]
                    message = call("CoordinatorResponse", findings, "final")
        return ChatResult(generations=[ChatGeneration(message=message)])


def setup_parallel(test_settings, monkeypatch, *, review=False, branches=3, workers=2):
    from data_analytics_agent import coordinator

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    root = Path(__file__).parents[1]
    shutil.copy(root / "AGENTS.md", test_settings.project_root / "AGENTS.md")
    shutil.copytree(root / "skills", test_settings.project_root / "skills")
    s = Services(
        settings=replace(
            test_settings,
            require_python_approval=review,
            analysis_parallel_workers=workers,
        )
    )
    thread = s.conversations.create("test")
    result = s.results.save(
        thread_id=thread,
        source_id="test",
        columns=["amount"],
        rows=[{"amount": 10}, {"amount": 20}],
    )
    monkeypatch.setattr(
        coordinator,
        "_build_chat_model",
        lambda *a, **k: ParallelAnalyst(dataset=result.result_id, branches=branches),
    )
    run = s.runs.create(thread, "test", "Independent saved-data analyses")
    s.conversations.begin_run(thread, run)
    return s, thread, run


@pytest.mark.parametrize("workers", [1, 2])
async def test_parallel_analysis_owns_outputs_and_obeys_concurrency(
    test_settings, monkeypatch, workers
):
    from data_analytics_agent.agents.data_analysis import tools

    s, thread, run = setup_parallel(test_settings, monkeypatch, workers=workers)
    execute = tools.execute_python
    lock = threading.Lock()
    counts = {"active": 0, "maximum": 0}

    def observed(**kwargs):
        with lock:
            counts["active"] += 1
            counts["maximum"] = max(counts["active"], counts["maximum"])
        try:
            time.sleep(0.15)
            return execute(**kwargs)
        finally:
            with lock:
                counts["active"] -= 1

    monkeypatch.setattr(tools, "execute_python", observed)
    await s.manager().start(run)
    state = s.runs.get(run)
    assert state.status == "completed", state.error
    assert counts["maximum"] == workers
    assert any(
        e.tool and e.tool.name == "write_todos" and e.phase == "completed"
        for e in state.events
    )
    executions = s.runs.get_python_execution(run)
    assert len(executions) == 3
    assert len({e.assignment_id for e in executions}) == 3
    assert sorted(e.outputs[0].value for e in executions) == [30, 60, 90]
    assert len(state.answer.analyses) == 3 and state.answer.report
    assert all(len(a.executions) == 1 for a in state.answer.analyses)
    receipts = s.runs.continuation(run)["assignments"]
    assert len(receipts) == 3
    assert {r["result"]["analysis_id"] for r in receipts} == {
        a.analysis_id for a in state.answer.analyses
    }
    assert all("executed_python" not in str(r) for r in receipts)
    python_events = [
        e
        for e in state.events
        if e.tool
        and e.tool.name == "execute_analysis_python"
        and e.phase == "completed"
    ]
    assert len({e.tool.invocation_id for e in python_events}) == 3
    assert all(e.duration_ms is not None for e in python_events)


async def test_parallel_reviews_approve_only_selected_worker(
    test_settings, monkeypatch
):
    s, thread, run = setup_parallel(test_settings, monkeypatch, review=True, branches=2)
    await s.manager().start(run)
    state = s.runs.get(run)
    assert state.status == "approval_required", state.error
    assert not s.runs.get_python_execution(run)
    assert not [e for e in state.events if e.phase == "failed"]
    assert [e for e in state.events if e.phase == "waiting"]
    first = state.approval
    await s.manager().resume(
        run,
        decisions_to_command(
            first,
            [Decision(action="edit", edited_python="analysis_outputs={'value':123}")],
        ),
    )
    state = s.runs.get(run)
    assert state.status == "approval_required", state.error
    assert state.approval.interrupt_id != first.interrupt_id
    executed = s.runs.get_python_execution(run)
    assert len(executed) == 1 and executed[0].outputs[0].value == 123
    await s.manager().resume(
        run, decisions_to_command(state.approval, [Decision(action="approve")])
    )
    state = s.runs.get(run)
    assert state.status == "completed", state.error
    assert len(s.runs.get_python_execution(run)) == 2
    assert len(state.answer.analyses) == 2


async def test_stop_cancels_running_and_queued_assignments(test_settings, monkeypatch):
    from data_analytics_agent.agents.data_analysis import tools

    s, thread, run = setup_parallel(test_settings, monkeypatch)
    started = threading.Event()
    count = []

    def block(**kwargs):
        count.append(kwargs["code"])
        if len(count) == 2:
            started.set()
        assert kwargs["cancel"].wait(5)
        raise InterruptedError("Stopped by test")

    monkeypatch.setattr(tools, "execute_python", block)
    task = asyncio.create_task(s.manager().start(run))
    assert await asyncio.to_thread(started.wait, 5)
    await s.manager().stop(run)
    await task
    assert s.runs.get(run).status == "paused"
    assert not s.runs.workers_active(run)
    assert len(count) == 2  # The queued third assignment never executes.


def test_parallel_dispatch_requires_plan_before_starting_workers():
    from data_analytics_agent.delegation import DelegationMiddleware

    calls = [
        {"name": "task", "args": {"subagent_type": "data-analysis"}, "id": str(n)}
        for n in range(2)
    ]
    request = SimpleNamespace(
        tool_call=calls[0],
        state={"messages": [AIMessage(content="", tool_calls=calls)]},
    )
    middleware = DelegationMiddleware(None, 2)
    invoked = []
    result = middleware.wrap_tool_call(request, lambda r: invoked.append(r))
    assert not invoked
    assert result.status == "error" and "write_todos" in result.content
    request.state["todos"] = [
        {"content": "Analyze both questions", "status": "in_progress"}
    ]
    assert middleware._missing_parallel_plan(request) is None
