"""Grade saved receipts, never equating completion with analytical correctness.

The review file contains human-reviewed criteria with evidence references; numeric
checks should come from independent source calculations. No model calls are made.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

RUBRIC = (
    "scope",
    "joins_and_grain",
    "arithmetic",
    "units",
    "assumptions",
    "methodology",
    "report_agreement",
)


def grade(run, review):
    checks = review.get("criteria", {})
    failures, missing = [], []
    if run.get("status") != "completed" or not run.get("answer"):
        failures.append("execution")
    if (run.get("answer") or {}).get("partial"):
        failures.append("incomplete")
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
        "failures": failures,
        "unreviewed": missing,
        "criteria": checks,
        "diagnostics": run.get("run_diagnostics") or {},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = json.loads(args.review.read_text())
    outcomes = {}
    for case, item in review["cases"].items():
        run = json.loads((args.receipts / case / "run.json").read_text())
        if run["run_id"] != item["run_id"]:
            raise ValueError(f"{case}: review belongs to a different run")
        outcomes[case] = grade(run, item)
    payload = {"graded_at": datetime.now(timezone.utc).isoformat(), "cases": outcomes}
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    raise SystemExit(
        0 if outcomes and all(o["outcome"] == "pass" for o in outcomes.values()) else 1
    )


if __name__ == "__main__":
    main()
