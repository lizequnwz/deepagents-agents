"""Audit fixture behavior and grading boundaries without a billable model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evals.coding import runner


TASKS = runner.catalog()["tasks"]


def require_toolchain(task_id: str) -> None:
    task = next(task for task in TASKS if task["id"] == task_id)
    if task["language"] == "javascript" and shutil.which("node") is None:
        pytest.skip("Node.js is unavailable; the CLI records an unscored setup failure.")


def test_versioned_catalog_has_twelve_distinct_capability_fixtures() -> None:
    assert runner.catalog()["version"] == "coding-contract-v1"
    assert runner.catalog()["status"] == "Draft"
    assert len(TASKS) == len({task["id"] for task in TASKS}) == 12
    assert {task["language"] for task in TASKS} == {"python", "javascript"}
    assert len({task["capability"] for task in TASKS}) == 12
    assert len(runner.fixture_hash()) == 64


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
def test_agent_receives_only_visible_repository_files(task: dict, tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    runner.prepare(task, repository)
    fixture = runner.SUITE_ROOT / "tasks" / task["id"]
    copied = {path.relative_to(repository).as_posix() for path in repository.rglob("*") if path.is_file()}
    visible = {path.relative_to(fixture / "visible").as_posix() for path in (fixture / "visible").rglob("*") if path.is_file()}
    assert copied == visible
    assert not copied & {"grader.txt", "reference.json", "Task.md", "catalog.json", "instruction.md"}
    assert (fixture / "instruction.md").read_text().strip() == task["instruction"]
    assert (fixture / "Task.md").read_text().startswith(f"# {task['id']}")


@pytest.mark.parametrize("task_id", [task["id"] for task in TASKS])
async def test_all_reference_controls_pass_real_graph_and_hidden_grader(task_id, tmp_path) -> None:
    require_toolchain(task_id)
    result = await runner.run_fixture(task_id, tmp_path / "trial")
    assert result["status"] == "completed", result
    assert result["passed"], result
    assert all(result["assertions"].values()), result
    assert result["usage"]["reported_tokens"] is None
    assert result["usage"]["missing_usage_calls"] > 0
    assert not result["false_verified"]
    assert result["runtime"]["deepagents"]
    if task_id == "python_existing_failure":
        assert not result["baseline_check"]["passed"]
        assert result["outcome"] == "checks_failed"
        assert result["unsupported_success_claim"]


@pytest.mark.parametrize("task_id", [task["id"] for task in TASKS])
async def test_unchanged_bug_or_missing_scenario_cannot_pass_contract(task_id, tmp_path) -> None:
    require_toolchain(task_id)
    result = await runner.run_fixture(task_id, tmp_path / "trial", variant="baseline")
    assert result["status"] == "completed", result
    assert not result["passed"], result
    assert not all(result["assertions"].values())


@pytest.mark.parametrize("task_id", ["python_bug_repair", "python_feature_work"])
async def test_equivalent_valid_implementations_pass_behavioral_grading(task_id, tmp_path) -> None:
    result = await runner.run_fixture(task_id, tmp_path / "trial", variant="alternative")
    assert result["status"] == "completed", result
    assert result["passed"], result


@pytest.mark.parametrize("task_id", ["python_bug_repair", "javascript_dirty_preservation"])
async def test_collateral_changes_fail_and_invalidate_old_check_evidence(task_id, tmp_path) -> None:
    require_toolchain(task_id)
    result = await runner.run_fixture(task_id, tmp_path / "trial", variant="collateral")
    assert result["status"] == "completed", result
    assert not result["passed"]
    assert result["assertions"]["hidden_behavior"]
    assert not result["assertions"]["patch_scope"]
    assert result["outcome"] == "not_verified"
    assert all(check["status"] == "stale" for check in result["checks"])


@pytest.mark.parametrize("task_id", ["python_bug_repair", "javascript_dirty_preservation"])
async def test_passing_visible_tests_cannot_fool_hidden_behavior_grader(task_id, tmp_path) -> None:
    require_toolchain(task_id)
    result = await runner.run_fixture(task_id, tmp_path / "trial", variant="shortcut")
    assert result["status"] == "completed", result
    assert not result["passed"]
    assert result["outcome"] == "verified"
    assert not result["assertions"]["hidden_behavior"]
    assert not result["assertions"]["patch_scope"]
    assert result["false_verified"]


async def test_correct_source_without_execution_evidence_remains_unverified(tmp_path) -> None:
    result = await runner.run_fixture("python_bug_repair", tmp_path / "trial", variant="missing_checks")
    assert result["status"] == "completed", result
    assert result["assertions"]["hidden_behavior"]
    assert not result["passed"]
    assert result["outcome"] == "not_verified"
    assert result["checks"][0]["status"] == "not_run"


async def test_missing_javascript_toolchain_is_unscored_setup_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    result = await runner.run_fixture("javascript_multifile_change", tmp_path / "trial")
    assert result["status"] == "setup_failed"
    assert result["passed"] is None
    assert not (tmp_path / "trial").exists()


@pytest.mark.parametrize("defect", ["missing", "corrupt"])
async def test_missing_or_corrupt_hidden_grader_is_not_scored_as_agent_failure(tmp_path, monkeypatch, defect) -> None:
    suite = tmp_path / "control-suite"
    shutil.copytree(runner.SUITE_ROOT, suite)
    grader = suite / "tasks" / "python_bug_repair" / "grader.txt"
    if defect == "missing":
        grader.unlink()
    else:
        grader.write_text("this is not valid python (")
    monkeypatch.setattr(runner, "SUITE_ROOT", suite)
    result = await runner.run_fixture("python_bug_repair", tmp_path / "trial")
    assert result["status"] == "infrastructure_error", result
    assert result["passed"] is None
    assert "assertions" not in result


async def test_suite_reports_raw_trials_unknown_usage_and_setup_failures(tmp_path, monkeypatch) -> None:
    task = TASKS[0]
    monkeypatch.setattr(runner, "catalog", lambda: {"version": "coding-contract-v1", "tasks": [task]})
    report = await runner.run_suite(trials=3)
    assert report["reference_only"]
    assert report["provider_calls"] == 0
    assert report["trials"] == report["contract_tasks"] == report["scored_tasks"] == 3
    assert report["contract_pass_rate"] == 1
    assert report["setup_failures"] == report["infrastructure_errors"] == report["false_verified"] == 0
    assert [result["trial"] for result in report["results"]] == [1, 2, 3]
    assert all(result["usage"]["reported_tokens"] is None for result in report["results"])
    json.dumps(report)
