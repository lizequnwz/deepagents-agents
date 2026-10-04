"""Run trusted reference/control fixtures, never arbitrary candidate code on host."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
from pydantic import Field

from general_agent.budgets import RunBudget, RunBudgetCallback, RunBudgetExceeded, run_budget_scope
from general_agent.coding.agent import build_coding_agent
from general_agent.coding.backend import RepositoryBackend
from general_agent.coding.changes import ChangeManager
from general_agent.coding.context import repository_context
from general_agent.coding.source import source_file
from general_agent.coding.store import CodingConflict, identifier
from general_agent.coding.verification import record_check, verification_summary
from general_agent.config import Settings
from general_agent.processes import ProcessSupervisor

SUITE_ROOT = Path(__file__).parent / "v1"
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C",
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
VARIANTS = {"reference", "alternative", "baseline", "collateral", "missing_checks", "shortcut"}
ALTERNATIVES = {
    "python_bug_repair": "    if high < low:\n        raise ValueError('bounds')\n    return low if value < low else high if value > high else value",
    "python_feature_work": "    import re\n    return '-'.join(re.findall('[a-z0-9]+', text.lower()))",
}


class ScriptedModel(FakeMessagesListChatModel):
    model_name: str = Field(default_factory=lambda: f"contract-{uuid4().hex}")
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        return {"ls_provider": "test", "ls_model_name": self.model_name}

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def catalog() -> dict[str, Any]:
    return json.loads((SUITE_ROOT / "catalog.json").read_text())


def fixture_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(SUITE_ROOT.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(SUITE_ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def prepare(task: dict[str, Any], destination: Path) -> None:
    """Copy only the explicitly agent-visible fixture into a fresh repository."""

    shutil.copytree(SUITE_ROOT / "tasks" / task["id"] / "visible", destination)


def _call(name: str, arguments: dict[str, Any], number: int) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": f"call-{number}"}])


def _responses(task: dict, variant: str) -> list[AIMessage]:
    scenario = task["scenario"]
    if scenario == "budget" and variant != "baseline":
        return [_call("task", {"description": "Inspect then fix increment", "subagent_type": "general-purpose"}, 0),
                _call("read_file", {"file_path": "/repo/increment.py"}, 1),
                _call("edit_file", {"file_path": "/repo/increment.py", "old_string": "value + 1", "new_string": "value + 2"}, 2),
                AIMessage(content="Done"), AIMessage(content="Done")]
    if scenario == "review" and variant != "baseline":
        return [_call("task", {"description": "Review calc.js without changing source", "subagent_type": "general-purpose"}, 0),
                _call("write_file", {"file_path": "/repo/calc.js", "content": "forbidden delegated edit"}, 1),
                AIMessage(content="calc.js:2 increments by two, contrary to its name."),
                AIMessage(content="calc.js:2 increments by two; no tests were executed.")]
    messages: list[AIMessage] = []
    if scenario == "instructions":
        for path in ("AGENTS.md", "service/AGENTS.md"):
            messages.append(_call("read_file", {"file_path": "/repo/" + path}, len(messages)))
    edits = json.loads((SUITE_ROOT / "tasks" / task["id"] / "reference.json").read_text())
    if variant not in {"baseline", "shortcut"}:
        for edit in edits:
            path = "/repo/" + edit["path"]
            if edit["old"] is None:
                arguments = {"file_path": path, "content": edit["new"]}
                name = "write_file"
            else:
                messages.append(_call("read_file", {"file_path": path}, len(messages)))
                replacement = ALTERNATIVES[task["id"]] if variant == "alternative" else edit["new"]
                arguments = {"file_path": path, "old_string": edit["old"], "new_string": replacement}
                name = "edit_file"
            messages.append(_call(name, arguments, len(messages)))
    if variant == "shortcut":
        visible = SUITE_ROOT / "tasks" / task["id"] / "visible"
        for path in sorted((visible / "tests").rglob("*")):
            if not path.is_file() or not path.read_text():
                continue
            relative = path.relative_to(visible).as_posix()
            messages.append(_call("edit_file", {"file_path": "/repo/" + relative,
                "old_string": path.read_text(), "new_string": "// skip assertions\n" if task["language"] == "javascript" else
                "import unittest\nclass Shortcut(unittest.TestCase):\n    def test_skip(self):\n        self.assertTrue(True)\n"}, len(messages)))
    if scenario == "cancellation" and variant != "baseline":
        messages.append(_call("long_validation", {}, len(messages)))
    elif task["check"] and variant != "missing_checks":
        messages.append(_call("run_check", {"name": "tests"}, len(messages)))
    messages.append(AIMessage(content="All tests pass." if scenario == "existing_failure" else "Fixture work completed."))
    return messages


def _argv(task: dict, node: str | None) -> list[str]:
    replacements = {"$PYTHON": sys.executable, "$NODE": node}
    return [replacements.get(argument, argument) for argument in task["check"]["argv"]]


async def run_fixture(task_id: str, trial_root: Path, *, variant: str = "reference") -> dict[str, Any]:
    """Produce an unscored infrastructure result even when fixture setup fails."""

    if variant not in VARIANTS or (variant == "alternative" and task_id not in ALTERNATIVES):
        raise ValueError("Unknown controlled fixture variant.")
    task = next((task for task in catalog()["tasks"] if task["id"] == task_id), None)
    if task is None:
        raise ValueError("Unknown coding fixture identifier.")
    try:
        return await _run_fixture_control(task, trial_root, variant=variant)
    except Exception as exc:
        return {"task": task_id, "language": task["language"], "variant": variant,
                "fixture_hash": fixture_hash(), "status": "infrastructure_error", "passed": None,
                "reason": f"{type(exc).__name__}: {exc}", "runtime_seconds": 0}


async def _run_fixture_control(task: dict[str, Any], trial_root: Path, *, variant: str) -> dict[str, Any]:
    """Exercise one fixed, repository-authored control through the actual graph."""

    task_id = task["id"]
    started = time.monotonic()
    result = {"task": task_id, "language": task["language"], "variant": variant,
              "fixture_hash": fixture_hash(), "status": "infrastructure_error", "passed": None}
    node = shutil.which("node")
    if task["language"] == "javascript" and node is None:
        return {**result, "status": "setup_failed", "reason": "Node.js is unavailable.", "runtime_seconds": 0}
    trial_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(project_root=trial_root / "application", model_name="test:fixture")
    settings.prepare_directories()
    manager, corp, session = ChangeManager(settings), "eval-alpha", identifier()
    original = trial_root / "original"
    prepare(task, original)
    repo = manager._session(corp, session) / "repo"
    shutil.copytree(original, repo)
    before = manager.capture(corp, session, repo)
    registered_identity = manager._root_identity(original)
    backend = RepositoryBackend(repo, read_only=task["scenario"] == "review")
    approved = {"tests": task["check"]["command"]} if task["check"] else {}
    identity = "trusted-contract-controls-v1"
    checks, state = [], {"budget_exhausted": False, "cancelled": False}
    supervisor, owner = ProcessSupervisor(), identifier()

    @tool
    async def run_check(name: str) -> str:
        """Run the fixture's approved named check and record exact source evidence."""
        if name != "tests" or not task["check"]:
            raise ValueError("No such approved check.")
        checked_before = manager.capture(corp, session, repo, tracked_paths=tuple(before["files"]))
        execution = await supervisor.run(_argv(task, node), owner_id=owner, cwd=repo,
            env=ENVIRONMENT, timeout=5, max_output_bytes=16000)
        checked_after = manager.capture(corp, session, repo, tracked_paths=tuple(before["files"]))
        evidence = record_check(name, approved[name], checked_before, checked_after,
            exit_code=execution.exit_code, output=execution.output, runtime_identity=identity)
        checks.append(evidence)
        return json.dumps(evidence)

    @tool
    async def long_validation() -> str:
        """Start the controlled long Node.js check, which the fixture controller stops."""
        execution = await supervisor.run([node, "-e", "require('fs').writeFileSync('.fixture-pid',String(process.pid)); setInterval(()=>{},1000)"],
            owner_id=owner, cwd=repo, env=ENVIRONMENT, timeout=10, max_output_bytes=1000)
        return execution.output

    try:
        grader = (SUITE_ROOT / "tasks" / task_id / "grader.txt").read_text()
        if task["language"] == "python":
            compile(grader, f"hidden:{task_id}", "exec")
        else:
            syntax = await supervisor.run_bytes([node, "--check", "--input-type=module"],
                owner_id=owner, cwd=repo, env=ENVIRONMENT, timeout=5,
                max_output_bytes=1000, input_data=grader.encode())
            if syntax.exit_code != 0 or syntax.truncated:
                raise RuntimeError("The hidden JavaScript grader failed its syntax audit.")
        node_version = None
        if node is not None:
            detected = await supervisor.run([node, "--version"], owner_id=owner, cwd=repo,
                env=ENVIRONMENT, timeout=5, max_output_bytes=100)
            if detected.exit_code != 0 or detected.truncated:
                raise RuntimeError("The detected Node.js executable did not report its version.")
            node_version = detected.output.strip()
        if task["check"]:
            baseline = await supervisor.run(_argv(task, node), owner_id=owner, cwd=repo,
                env=ENVIRONMENT, timeout=5, max_output_bytes=2000)
            result["baseline_check"] = {"exit_code": baseline.exit_code, "passed": baseline.exit_code == 0}
        context = repository_context(repo, tracked_paths=tuple(before["files"]))
        model = ScriptedModel(responses=_responses(task, variant))
        graph = build_coding_agent(settings, repository=backend,
            mode="review" if task["scenario"] == "review" else "implement",
            checkpointer=None, tools=[run_check, long_validation] if task["check"] else [], model=model)
        budget = RunBudget(max_model_calls=2 if task["scenario"] == "budget" else 40,
                           max_tool_calls=40, max_task_calls=5)
        agent_input = {"messages": [{"role": "user", "content": task["instruction"] +
            "\nRepository data:\n" + json.dumps(context["instructions"])}]}
        final_text, run_status = "", "completed"
        with run_budget_scope(budget):
            try:
                if task["scenario"] == "cancellation" and variant != "baseline":
                    running = asyncio.create_task(graph.ainvoke(agent_input, config={"callbacks": [RunBudgetCallback()]}))
                    deadline = time.monotonic() + 5
                    marker = repo / ".fixture-pid"
                    while not marker.exists() and not running.done() and time.monotonic() < deadline:
                        await asyncio.sleep(0.01)
                    if not marker.exists():
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
                        raise RuntimeError("Controlled cancellation process did not become ready.")
                    pid = int(marker.read_text())
                    running.cancel()
                    await asyncio.gather(running, return_exceptions=True)
                    await supervisor.cancel_owner(owner)
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        state["cancelled"] = True
                    run_status = "stopped"
                else:
                    output = await graph.ainvoke(agent_input, config={"callbacks": [RunBudgetCallback()]})
                    final_text = output["messages"][-1].content
                    budget.raise_if_exceeded()
            except RunBudgetExceeded:
                state["budget_exhausted"] = True
                run_status = "failed"
        if variant == "collateral":
            (repo / "unexpected.txt").write_text("prohibited unrelated change")
        change = manager.finalize(corp, session, before, repo, identifier(), tracked_paths=tuple(before["files"]))
        summary = verification_summary(checks, approved, change["after"], runtime_identity=identity)
        if task["scenario"] == "stale_apply":
            (original / "increment.py").write_text("def increment(value):\n    return value + 999\n")
            state["apply_conflict"] = False
            if change["files"]:
                try:
                    manager.apply(corp, session, change["id"], original, repo, change["revision"],
                                  expected_root_identity=registered_identity)
                except CodingConflict:
                    state["apply_conflict"] = True
            state["external_edit_preserved"] = "value + 999" in (original / "increment.py").read_text()
        argv = [sys.executable, "-c", grader] if task["language"] == "python" else [node, "--input-type=module", "-e", grader]
        graded = await supervisor.run(argv, owner_id=owner, cwd=repo, env=ENVIRONMENT,
                                      timeout=5, max_output_bytes=3000)
        changed = {entry["path"] for entry in change["files"]}
        preserved = True
        for relative, metadata in before["files"].items():
            if task["scenario"] == "stale_apply" and relative == "increment.py":
                continue
            with source_file(original, relative) as descriptor:
                with os.fdopen(os.dup(descriptor), "rb") as reader:
                    preserved &= hashlib.file_digest(reader, "sha256").hexdigest() == metadata["sha256"]
        scenario_ok = True
        if task["scenario"] == "budget":
            scenario_ok = state["budget_exhausted"] and len(model.calls) == 2 and not changed
        elif task["scenario"] == "review":
            scenario_ok = budget.snapshot()["task_calls"] == 1 and not changed and "calc.js:2" in final_text
        elif task["scenario"] == "stale_apply":
            scenario_ok = state.get("apply_conflict", False) and state["external_edit_preserved"]
        elif task["scenario"] == "cancellation":
            scenario_ok = state["cancelled"] and run_status == "stopped"
        elif task["scenario"] == "instructions":
            scopes = {entry["path"]: entry["scope"] for entry in context["instructions"]}
            scenario_ok = scopes == {"AGENTS.md": "/", "service/AGENTS.md": "service/"}
        assertions = {"hidden_behavior": graded.exit_code == 0,
                      "patch_scope": changed <= set(task["allowed_changes"]),
                      "original_user_bytes_preserved": preserved, "scenario_contract": bool(scenario_ok),
                      "verification_outcome": summary["outcome"] == task["expected_outcome"]}
        return {**result, "status": "completed", "passed": all(assertions.values()),
                "assertions": assertions, "outcome": summary["outcome"], "run_status": run_status,
                "checks": summary["checks"], "state": state, "changed_paths": sorted(changed),
                "hidden_grader": {"exit_code": graded.exit_code, "output": graded.output},
                "false_verified": summary["outcome"] == "verified" and not assertions["hidden_behavior"],
                "unsupported_success_claim": final_text == "All tests pass." and summary["outcome"] != "verified",
                "usage": {"reported_tokens": None, "missing_usage_calls": len(model.calls), **budget.snapshot()},
                "runtime_seconds": round(time.monotonic() - started, 4),
                "harness": "actual coding graph; scripted fake model; trusted reference/control processes",
                "runtime": {"python": sys.version.split()[0], "node": node_version,
                            "deepagents": version("deepagents"), "langchain": version("langchain"),
                            "langchain_core": version("langchain-core"), "langgraph": version("langgraph")}}
    except Exception as exc:
        return {**result, "reason": f"{type(exc).__name__}: {exc}",
                "runtime_seconds": round(time.monotonic() - started, 4)}
    finally:
        await supervisor.cancel_owner(owner)


async def run_suite(*, trials: int = 1) -> dict[str, Any]:
    if not 1 <= trials <= 3:
        raise ValueError("Run one to three independent deterministic trials.")
    results = []
    with tempfile.TemporaryDirectory(prefix="coding-contract-") as temporary:
        physical_root = Path(temporary).resolve()
        for trial in range(1, trials + 1):
            for task in catalog()["tasks"]:
                result = await run_fixture(task["id"], physical_root / f"trial-{trial}" / task["id"])
                results.append({"trial": trial, **result})
    completed = [result for result in results if result["status"] == "completed"]
    return {"suite": catalog()["version"], "fixture_hash": fixture_hash(), "trials": trials,
            "reference_only": True, "provider_calls": 0,
            "contract_tasks": len(results), "scored_tasks": len(completed),
            "passed_tasks": sum(result["passed"] for result in completed),
            "contract_pass_rate": sum(result["passed"] for result in completed) / len(completed) if completed else None,
            "false_verified": sum(bool(result.get("false_verified")) for result in results),
            "unsupported_success_claims": sum(bool(result.get("unsupported_success_claim")) for result in results),
            "setup_failures": sum(result["status"] == "setup_failed" for result in results),
            "infrastructure_errors": sum(result["status"] == "infrastructure_error" for result in results),
            "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(run_suite(trials=arguments.trials))
    rendered = json.dumps(report, indent=2)
    if arguments.output:
        arguments.output.write_text(rendered + "\n")
    else:
        print(rendered)
    return 0 if report["contract_pass_rate"] == 1 and not report["setup_failures"] and not report["infrastructure_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
