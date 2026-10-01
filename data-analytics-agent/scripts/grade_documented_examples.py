"""Grade saved receipts, never equating completion with analytical correctness.

The review file contains human-reviewed criteria with evidence references; numeric
checks should come from independent source calculations. No model calls are made.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from data_analytics_agent.evaluation import file_hash, receipt_hash

RUBRIC = (
    "scope",
    "joins_and_grain",
    "arithmetic",
    "units",
    "assumptions",
    "methodology",
    "report_agreement",
)
EXPECTED_OUTCOMES = {"complete", "partial", "clarification", "metadata"}
DATA_TOOLS = {
    "execute_sql",
    "lookup_values",
    "query_saved_results",
    "execute_analysis_python",
    "inspect_conversation_result",
    "inspect_conversation_analysis",
}


def grade(run, review, *, expected_outcome="complete"):
    if expected_outcome not in EXPECTED_OUTCOMES:
        raise ValueError(f"Unknown expected outcome: {expected_outcome}")
    checks = review.get("criteria", {})
    failures, missing = [], []
    answer = run.get("answer") or {}
    data_access = any(
        (event.get("tool") or {}).get("name") in DATA_TOOLS
        for event in run.get("events", [])
    )
    if expected_outcome in {"clarification", "metadata"} and "events" not in run:
        missing.append("execution_boundary")
    if expected_outcome == "clarification":
        if run.get("status") != "clarification_required" or not run.get(
            "clarification"
        ):
            failures.append("expected_clarification")
        if answer or run.get("findings") or data_access:
            failures.append("clarification_after_analysis")
    else:
        if run.get("status") != "completed" or not answer:
            failures.append("execution")
        if expected_outcome == "partial":
            if not answer.get("partial"):
                failures.append("expected_partial")
        elif answer.get("partial"):
            failures.append("incomplete")
        if expected_outcome == "metadata":
            if data_access or any(
                answer.get(k) for k in ("results", "analyses", "charts", "report")
            ):
                failures.append("metadata_data_access")
        elif answer and not answer.get("report"):
            failures.append("missing_report")
    for criterion in RUBRIC:
        item = checks.get(criterion, {})
        if item.get("status") not in {"pass", "fail", "not_applicable"} or not item.get(
            "evidence"
        ):
            missing.append(criterion)
        elif item["status"] == "fail":
            failures.append(criterion)
    return {
        "outcome": "fail" if failures else "unreviewed" if missing else "pass",
        "expected_outcome": expected_outcome,
        "failures": failures,
        "unreviewed": missing,
        "criteria": checks,
        "diagnostics": run.get("run_diagnostics") or {},
        "hard_boundaries": review.get("hard_boundaries"),
        "first_attempt": review.get("first_attempt"),
        "repair_count": review.get("repair_count"),
        "scenario_checks": review.get("scenario_checks", {}),
    }


def grade_receipts(receipts, review):
    """Account for every selected case, including absent reviews and failed runs."""
    manifest = json.loads((receipts / "manifest.json").read_text())
    cases = {case["id"]: case for case in manifest["corpus"]}
    selected = manifest["case_ids"]
    unknown = set(review["cases"]) - set(selected)
    if unknown:
        raise ValueError(f"Reviews outside the frozen selection: {sorted(unknown)}")
    outcomes = {}
    for case_id in selected:
        item = review["cases"].get(case_id, {})
        folder = receipts / case_id
        path = folder / "run.json"
        if not path.exists():
            outcomes[case_id] = {
                "outcome": "unreviewed",
                "failures": [],
                "unreviewed": ["missing_receipt"],
                "run_id": None,
                "expected_outcome": cases[case_id].get("expected_outcome", "complete"),
            }
            continue
        run = json.loads(path.read_text())
        if item and run["run_id"] != item.get("run_id"):
            raise ValueError(f"{case_id}: review belongs to a different run")
        outcome = grade(
            run,
            item,
            expected_outcome=cases[case_id].get("expected_outcome", "complete"),
        )
        outcome.update(
            run_id=run["run_id"],
            run_sha256=file_hash(path),
            receipt_sha256=receipt_hash(folder),
        )
        runner_error = folder / "runner-error.json"
        if (
            runner_error.exists()
            and json.loads(runner_error.read_text())["reason"] == "collection"
        ):
            outcome["unreviewed"].append("receipt_collection")
            if outcome["outcome"] == "pass":
                outcome["outcome"] = "unreviewed"
        answer = run.get("answer") or run.get("findings") or {}
        required = [
            folder / f"{reference['result_id']}.{format}"
            for reference in answer.get("results", [])
            for format in ("csv", "parquet")
        ]
        if answer.get("report"):
            required.extend(
                folder / name
                for name in (
                    "report.json",
                    "report.html",
                    "report-spec.json",
                    "analysis.zip",
                )
            )
        if any(not path.exists() for path in required):
            outcome["unreviewed"].append("missing_artifacts")
            if outcome["outcome"] == "pass":
                outcome["outcome"] = "unreviewed"
        outcomes[case_id] = outcome
    after_path = receipts / "execution-after.json"
    stable = (
        after_path.exists()
        and json.loads(after_path.read_text()) == manifest["execution"]
    )
    return {
        "manifest_sha256": file_hash(receipts / "manifest.json"),
        "execution_stable": stable,
        "evidence_level": review.get("evidence_level"),
        "cases": outcomes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = json.loads(args.review.read_text())
    payload = {
        **grade_receipts(args.receipts, review),
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "review_sha256": file_hash(args.review),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    outcomes = payload["cases"]
    raise SystemExit(
        0
        if payload["execution_stable"]
        and outcomes
        and all(o["outcome"] == "pass" for o in outcomes.values())
        else 1
    )


if __name__ == "__main__":
    main()
