"""Immutable check evidence and revision-sensitive verification outcomes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from general_agent.coding.store import identifier, now


def record_check(
    name: str,
    command: str,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    *,
    exit_code: int | None,
    output: str,
    runtime_identity: str,
    reason: str | None = None,
    phase: str = "final",
) -> dict[str, Any]:
    """Record observed execution; a check that rewrites source is stale."""

    if phase not in {"baseline", "final"}:
        raise ValueError("Check phase must be baseline or final.")
    if before_snapshot["revision"] != after_snapshot["revision"]:
        status = "stale"
        reason = "Source changed while the check ran; rerun on the final revision."
    elif exit_code is None:
        status = "not_run"
        reason = reason or "The check did not report an exit code."
    else:
        status = "passed" if exit_code == 0 else "failed"
    return {
        "id": identifier(), "created": now(), "name": name, "command": command,
        "phase": phase,
        "status": status, "exit_code": exit_code, "output": output,
        "before_revision": before_snapshot["revision"],
        "revision": after_snapshot["revision"], "runtime_identity": runtime_identity,
        "reason": reason,
    }


def verification_summary(
    checks: list[dict[str, Any]],
    approved_checks: dict[str, str],
    current_snapshot: dict[str, Any],
    *,
    runtime_identity: str,
) -> dict[str, Any]:
    """Evaluate copies, preserving the immutable evidence from earlier attempts."""

    evaluated = deepcopy(checks)
    latest: dict[str, dict[str, Any]] = {}
    for check in evaluated:
        if check.get("phase") == "baseline":
            continue  # Keep observations from the opening state; they never certify final source.
        reasons = []
        if check["revision"] != current_snapshot["revision"]:
            reasons.append("Source changed after this check.")
        if check["runtime_identity"] != runtime_identity:
            reasons.append("The execution environment changed after this check.")
        if approved_checks.get(check["name"]) != check["command"]:
            reasons.append("The approved check command changed or was removed.")
        if reasons:
            check.update(status="stale", reason=" ".join(reasons))
        if check["name"] in approved_checks:
            latest[check["name"]] = check

    for name, command in approved_checks.items():
        if name not in latest:
            missing = {"name": name, "command": command, "status": "not_run",
                       "reason": "No execution evidence was recorded for this check."}
            evaluated.append(missing)
            latest[name] = missing
    statuses = [check["status"] for check in latest.values()]
    if "failed" in statuses:
        outcome = "checks_failed"
    elif statuses and all(status == "passed" for status in statuses):
        outcome = "verified"
    else:
        outcome = "not_verified"
    return {"outcome": outcome, "checks": evaluated,
            "baseline_failures": [check["name"] for check in evaluated
                                  if check.get("phase") == "baseline" and check["status"] == "failed"]}


def browser_summary(records: list[dict], *, revision: str, runtime_identity: str,
                    outcome: str) -> dict:
    """A browser failure prevents verification; screenshots alone cannot grant it."""
    evaluated = deepcopy(records)
    latest = {}
    for record in evaluated:
        if record.get("source_revision") != revision or record.get("main_runtime_identity") != runtime_identity:
            record.update(status="stale", reason="Source or installed environment changed after this browser check.")
        latest[record["target"]] = record
    statuses = {record["status"] for record in latest.values()}
    if "failed" in statuses:
        outcome = "checks_failed"
    elif "stale" in statuses and outcome == "verified":
        outcome = "not_verified"
    return {"browser_checks": evaluated, "outcome": outcome}
