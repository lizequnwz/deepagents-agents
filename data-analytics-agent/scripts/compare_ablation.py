"""Compare independently graded, paired receipts against a frozen study protocol.

Makes no model/source calls and changes no application settings. Bootstrap
conversations, keeping follow-ups and repetitions together.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from scipy.stats import bootstrap

from data_analytics_agent.evaluation import file_hash, receipt_hash

METRICS = {
    "elapsed_ms",
    "active_ms",
    "input_tokens",
    "total_tokens",
    "model_calls",
    "tool_calls",
}


def metric_value(run, name):
    if run.get("status") not in {"completed", "clarification_required"}:
        return None
    diagnostics = run.get("run_diagnostics") or {}
    if name.endswith("tokens"):
        if (
            "token_usage_partial" not in diagnostics
            or diagnostics["token_usage_partial"]
            or diagnostics.get("model_calls_missing_usage", 1) != 0
        ):
            return None
        value = (diagnostics.get("tokens") or {}).get(name)
    else:
        value = diagnostics.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not np.isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


def reviewed(item):
    return (
        isinstance(item, dict)
        and item.get("status") in {"pass", "fail"}
        and bool(item.get("evidence"))
    )


def compare_trials(study, folders):
    if study["target_metric"] not in METRICS:
        raise ValueError(
            "Unsupported target metric; missing cost telemetry is not zero cost"
        )
    if not study.get("hypothesis") or not study.get("changed_component"):
        raise ValueError("Declare the hypothesis and one changed component")
    if study["minimum_cases"] < 20 or study["minimum_repetitions"] < 3:
        raise ValueError(
            "A diagnostic study requires at least 20 cases and three repetitions"
        )
    if (
        not 0 < study["minimum_improvement"] < 1
        or not 0 < study["confidence_level"] < 1
    ):
        raise ValueError(
            "Improvement and confidence level must lie between zero and one"
        )
    if not study.get("changed_files") and not study.get("changed_settings"):
        raise ValueError("Declare the files or setting changed by this experiment")
    if len({path.resolve() for path in folders}) != len(folders):
        raise ValueError("A trial directory cannot be reused")
    trials = {}
    run_ids, thread_ids = set(), set()
    for folder in folders:
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest["study"] != study:
            raise ValueError("Trial does not match the predeclared study")
        key = (manifest["variant"], manifest["repetition"])
        if key[0] not in {"baseline", "candidate"} or key[1] < 1 or key in trials:
            raise ValueError("Each variant/repetition needs a separate trial")
        grades = json.loads((folder / "grades.json").read_text())
        if grades["manifest_sha256"] != file_hash(folder / "manifest.json"):
            raise ValueError("Grades do not match the frozen manifest")
        if manifest["case_ids"] != [case["id"] for case in manifest["corpus"]]:
            raise ValueError("A paired trial must account for the entire frozen corpus")
        if set(grades["cases"]) != set(manifest["case_ids"]):
            raise ValueError("Grades omit selected cases")
        if not grades["execution_stable"]:
            raise ValueError(
                "Serving inputs/settings changed or the trial did not finish collecting evidence"
            )
        if (
            json.loads((folder / "execution-after.json").read_text())
            != manifest["execution"]
        ):
            raise ValueError("Post-run fingerprints do not match the frozen execution")
        if any(
            not isinstance(source, dict) or not source.get("frozen")
            for source in manifest["execution"]["sources"].values()
        ):
            raise ValueError("Remote source inputs are not frozen snapshots")
        runs = {}
        trial_threads = set()
        for case_id, outcome in grades["cases"].items():
            if outcome.get("outcome") not in {"pass", "fail", "unreviewed"}:
                raise ValueError("Unknown graded outcome")
            path = folder / case_id / "run.json"
            if not path.exists():
                runs[case_id] = {}
                continue
            run = json.loads(path.read_text())
            if (
                outcome.get("run_id") != run["run_id"]
                or outcome.get("run_sha256") != file_hash(path)
                or outcome.get("receipt_sha256") != receipt_hash(path.parent)
            ):
                raise ValueError("Grades are stale or belong to different receipts")
            if run["run_id"] in run_ids:
                raise ValueError("An independent trial cannot reuse a run")
            run_ids.add(run["run_id"])
            trial_threads.add(run["thread_id"])
            runs[case_id] = run
        if thread_ids & trial_threads:
            raise ValueError("Independent repetitions must use fresh conversations")
        thread_ids.update(trial_threads)
        trials[key] = {"manifest": manifest, "grades": grades, "runs": runs}
    if not trials:
        raise ValueError("Supply paired trial directories")
    baseline = {repeat for variant, repeat in trials if variant == "baseline"}
    candidate = {repeat for variant, repeat in trials if variant == "candidate"}
    if not baseline or baseline != candidate:
        raise ValueError("Pair every baseline repetition with its candidate repetition")
    reference = trials[("baseline", min(baseline))]["manifest"]
    changed_files, changed_settings = set(), set()
    for (variant, _), trial in trials.items():
        manifest = trial["manifest"]
        for field in ("corpus", "uploads", "evaluation_sha256"):
            if manifest[field] != reference[field]:
                raise ValueError(f"Uncontrolled change to {field}")
        execution, original = manifest["execution"], reference["execution"]
        for field in ("sources", "dependencies_sha256", "registry_sha256", "versions"):
            if execution[field] != original[field]:
                raise ValueError(f"Uncontrolled change to {field}")
        files = {**original["code_files"], **original["instruction_files"]}
        current = {**execution["code_files"], **execution["instruction_files"]}
        changes = {
            name
            for name in files.keys() | current.keys()
            if files.get(name) != current.get(name)
        }
        setting_changes = {
            name
            for name in original["runtime"].keys() | execution["runtime"].keys()
            if original["runtime"].get(name) != execution["runtime"].get(name)
        }
        if variant == "baseline" and (changes or setting_changes):
            raise ValueError("Baseline changed between independent repetitions")
        if not changes <= set(study["changed_files"]) or not setting_changes <= set(
            study["changed_settings"]
        ):
            raise ValueError("Experiment changed undeclared components")
        candidate_reference = trials[("candidate", min(candidate))]["manifest"][
            "execution"
        ]
        if variant == "candidate" and execution != candidate_reference:
            raise ValueError("Candidate changed between independent repetitions")
        changed_files.update(changes)
        changed_settings.update(setting_changes)
    if not changed_files and not changed_settings:
        raise ValueError("The candidate is identical to the baseline")
    regressions, failures, unknown, rows = [], [], [], []
    for (variant, repetition), trial in trials.items():
        observed = {
            name
            for outcome in trial["grades"]["cases"].values()
            for name, check in outcome.get("scenario_checks", {}).items()
            if reviewed(check) and check["status"] == "pass"
        }
        for scenario in set(study["required_scenarios"]) - observed:
            unknown.append(
                {
                    "variant": variant,
                    "repetition": repetition,
                    "reason": f"scenario:{scenario}",
                }
            )
    for case in reference["corpus"]:
        case_id = case["id"]
        before_values, after_values = [], []
        paired_reductions = []
        pairs = []
        for repetition in sorted(baseline):
            before, after = (
                trials[(variant, repetition)] for variant in ("baseline", "candidate")
            )
            bg, cg = (trial["grades"]["cases"][case_id] for trial in (before, after))
            pair = {"case_id": case_id, "repetition": repetition}
            if bg["outcome"] == "pass" and cg["outcome"] == "fail":
                regressions.append(pair)
            if cg["outcome"] == "fail":
                failures.append({**pair, "failures": cg["failures"]})
            for variant, trial, outcome in (
                ("baseline", before, bg),
                ("candidate", after, cg),
            ):
                if trial["grades"].get("evidence_level") != "live_provider":
                    unknown.append(
                        {**pair, "variant": variant, "reason": "live_provider_review"}
                    )
                if outcome["outcome"] == "unreviewed":
                    unknown.append(
                        {**pair, "variant": variant, "reason": "independent_review"}
                    )
                for check in ("hard_boundaries", "first_attempt"):
                    if not reviewed(outcome.get(check)):
                        unknown.append({**pair, "variant": variant, "reason": check})
                if (
                    variant == "candidate"
                    and reviewed(outcome.get("hard_boundaries"))
                    and outcome["hard_boundaries"]["status"] == "fail"
                ):
                    failures.append({**pair, "failures": ["hard_boundaries"]})
            if reviewed(bg.get("first_attempt")) and reviewed(cg.get("first_attempt")):
                if (
                    bg["first_attempt"]["status"] == "pass"
                    and cg["first_attempt"]["status"] == "fail"
                ):
                    regressions.append({**pair, "reason": "first_attempt"})
            before_value = metric_value(before["runs"][case_id], study["target_metric"])
            after_value = metric_value(after["runs"][case_id], study["target_metric"])
            if before_value is None or after_value is None or before_value == 0:
                unknown.append({**pair, "reason": "target_telemetry"})
            else:
                before_values.append(before_value)
                after_values.append(after_value)
                paired_reductions.append((before_value - after_value) / before_value)
            pairs.append(
                {
                    **pair,
                    "baseline": before_value,
                    "candidate": after_value,
                    "baseline_outcome": bg["outcome"],
                    "candidate_outcome": cg["outcome"],
                    "baseline_repair_count": bg.get("repair_count"),
                    "candidate_repair_count": cg.get("repair_count"),
                    "baseline_diagnostics": before["runs"][case_id].get(
                        "run_diagnostics", {}
                    ),
                    "candidate_diagnostics": after["runs"][case_id].get(
                        "run_diagnostics", {}
                    ),
                    "baseline_failed_tools": failed_tools(before["runs"][case_id]),
                    "candidate_failed_tools": failed_tools(after["runs"][case_id]),
                }
            )
        before_median = float(np.median(before_values)) if before_values else None
        after_median = float(np.median(after_values)) if after_values else None
        rows.append(
            {
                "case_id": case_id,
                "conversation": case["conversation"],
                "pairs": pairs,
                "baseline_median": before_median,
                "candidate_median": after_median,
                "relative_improvement": (
                    float(np.median(paired_reductions))
                    if len(paired_reductions) == len(baseline)
                    and all(
                        pair["baseline_outcome"] == pair["candidate_outcome"] == "pass"
                        for pair in pairs
                    )
                    else None
                ),
            }
        )
    reductions = [
        row["relative_improvement"]
        for row in rows
        if row["relative_improvement"] is not None
    ]
    enough = (
        len(rows) >= study["minimum_cases"]
        and len(baseline) >= study["minimum_repetitions"]
    )
    median, interval = None, None
    if enough and len(reductions) == len(rows):
        median = float(np.median(reductions))
        groups = {}
        for row in rows:
            if row["relative_improvement"] is not None:
                groups.setdefault(row["conversation"], []).append(
                    row["relative_improvement"]
                )
        blocks = [np.array(values) for values in groups.values()]
        if len(blocks) > 1:

            def grouped_median(indices):
                return np.median(
                    np.concatenate([blocks[int(index)] for index in indices])
                )

            result = bootstrap(
                (np.arange(len(blocks)),),
                grouped_median,
                vectorized=False,
                method="percentile",
                confidence_level=study["confidence_level"],
                n_resamples=10_000,
                rng=np.random.default_rng(study["bootstrap_seed"]),
            )
            interval = [
                float(result.confidence_interval.low),
                float(result.confidence_interval.high),
            ]
    improvement = (
        median is not None
        and median >= study["minimum_improvement"]
        and interval is not None
        and interval[0] > 0
    )
    decision = (
        "retain_baseline"
        if failures or regressions
        else "inconclusive"
        if unknown or not enough or interval is None or interval[0] <= 0
        else "eligible_for_adoption"
        if improvement
        else "retain_baseline"
    )
    return {
        "study": study,
        "decision": decision,
        "case_count": len(rows),
        "repetitions": len(baseline),
        "changed_files": sorted(changed_files),
        "changed_settings": sorted(changed_settings),
        "median_relative_improvement": median,
        "confidence_interval": interval,
        "paid_cost": None,
        "warehouse_query_count": None,
        "regressions": regressions,
        "candidate_failures": failures,
        "unknown": unknown,
        "cases": rows,
        "limitations": [
            "Conversation bootstrap describes this frozen diagnostic corpus; it does not prove general non-inferiority.",
            "Study performance is not estimated over incomplete, unreviewed or failing outcome pairs. Interrupted-run counters describe only the work performed so far.",
            "Elapsed/active time, model/tool errors and reviewed repairs are distinct measures. Missing telemetry remains unknown.",
            "Adoption requires review of boundary coverage; this script does not change production code.",
        ],
    }


def failed_tools(run):
    counts = {}
    for event in run.get("events", []):
        if event.get("phase") == "failed" and event.get("tool"):
            name = event["tool"]["name"]
            counts[name] = counts.get(name, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--trial", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_trials(json.loads(args.study.read_text()), args.trial)
    result["compared_at"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    raise SystemExit(0 if result["decision"] == "eligible_for_adoption" else 1)


if __name__ == "__main__":
    main()
