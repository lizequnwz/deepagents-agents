"""Run frozen questions through a live API and retain inspectable outcomes.

Invokes the configured provider. Use authorized fixtures and a separate API
storage directory for each independent trial. Never auto-approve SQL or Python.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx

from data_analytics_agent.evaluation import file_hash, files_hash

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OUTCOMES = {"complete", "partial", "clarification", "metadata"}
ACTIVE_STATUSES = {"running", "queued", "stopping"}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def expected_status(case):
    return (
        "clarification_required"
        if case.get("expected_outcome") == "clarification"
        else "completed"
    )


def validate_cases(cases):
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Case IDs must be unique")
    sources, uploads = {}, {}
    for case in cases:
        if Path(case["id"]).name != case["id"] or case["id"] in {"", ".", ".."}:
            raise ValueError("Case IDs must be directory names")
        expected = case.get("expected_outcome", "complete")
        if expected not in EXPECTED_OUTCOMES:
            raise ValueError(f"{case['id']}: unknown expected outcome {expected}")
        if expected == "clarification" and case.get("clarification"):
            raise ValueError(
                f"{case['id']}: expected clarification must remain unanswered"
            )
        group = case["conversation"]
        if group in sources and sources[group] != case["source"]:
            raise ValueError(f"{case['id']}: a conversation cannot change source")
        sources[group] = case["source"]
        if case["source"] == "upload":
            supplied = case.get("upload")
            if group not in uploads and not supplied:
                raise ValueError(
                    f"{case['id']}: upload path and explicit schema review are required"
                )
            if supplied:
                if not {"path", "review"} <= supplied.keys():
                    raise ValueError(f"{case['id']}: upload needs path and review")
                if group in uploads and supplied != uploads[group]:
                    raise ValueError(
                        f"{case['id']}: a new upload needs a separate conversation"
                    )
                uploads[group] = supplied


def save_receipts(client, call, folder, state):
    # Commit the run before downloading artifacts: a broken download must never
    # erase a failed, partial, or successful model outcome.
    write_json(folder / "run.json", state)
    answer = state.get("answer") or state.get("findings") or {}
    result_ids = list(dict.fromkeys([
        *(ref["result_id"] for ref in answer.get("results", [])),
        *(r["result_id"] for r in state.get("evaluation_receipts", []) if r.get("result_id")),
    ]))
    for rid in result_ids:
        for format in ("csv", "parquet"):
            response = client.get(
                f"/api/results/{rid}/download", params={"format": format}
            )
            response.raise_for_status()
            (folder / f"{rid}.{format}").write_bytes(response.content)
        write_json(folder / f"{rid}.json", call("GET", f"/api/results/{rid}"))
    if answer.get("report"):
        rid = answer["report"]["report_id"]
        report = call("GET", f"/api/reports/{rid}")
        write_json(folder / "report.json", report)
        (folder / "report.html").write_text(report["html"])
        write_json(folder / "report-spec.json", call("GET", f"/api/reports/{rid}/spec"))
        response = client.get(
            f"/api/runs/{state['run_id']}/download", params={"report_id": rid}
        )
        response.raise_for_status()
        (folder / "analysis.zip").write_bytes(response.content)
    write_json(
        folder / "artifact-hashes.json",
        {
            path.name: file_hash(path)
            for path in sorted(folder.iterdir())
            if path.suffix in {".csv", ".parquet", ".html", ".zip"}
        },
    )


def run_case(case, cases, output, threads, client, call):
    folder = output / case["id"]
    folder.mkdir(exist_ok=True)
    recorded = None
    if (folder / "run.json").exists():
        recorded = json.loads((folder / "run.json").read_text())
        # A failed trial stays failed. Repetitions need new receipt directories.
        if recorded["status"] in {"completed", "failed"} or (
            recorded["status"] == expected_status(case) == "clarification_required"
        ):
            collected = folder / "artifact-hashes.json"
            if collected.exists():
                hashes = json.loads(collected.read_text())
                if any(
                    not (folder / name).is_file()
                    or file_hash(folder / name) != expected
                    for name, expected in hashes.items()
                ):
                    raise RuntimeError(
                        "Collected evidence changed; use a new receipt directory"
                    )
                return recorded
            save_receipts(client, call, folder, recorded)
            return recorded
        if not (folder / "interrupted-run.json").exists():
            write_json(folder / "interrupted-run.json", recorded)
    group = case["conversation"]
    for prior in cases[: cases.index(case)]:
        if prior["conversation"] != group:
            continue
        receipt = output / prior["id"] / "run.json"
        if (
            not receipt.exists()
            or json.loads(receipt.read_text())["status"] != "completed"
        ):
            raise RuntimeError(f"{case['id']} requires completed {prior['id']}")
    if group not in threads:
        if recorded is not None:
            raise RuntimeError(
                "Recorded run has no conversation registry; do not resubmit"
            )
        if case["source"] == "upload":
            fixture = case["upload"]
            path = ROOT / fixture["path"]
            upload = call(
                "POST",
                "/api/uploads",
                params={"filename": path.name, **fixture.get("selection", {})},
                content=path.read_bytes(),
            )
            thread = upload["thread_id"]
            write_json(folder / "upload.json", upload)
            # Record the conversation before review so an interruption can use
            # this same upload instead of creating another conversation.
            threads[group] = thread
            write_json(output / "conversations.json", threads)
        else:
            thread = call(
                "POST", "/api/conversations", json={"source_id": case["source"]}
            )["thread_id"]
            threads[group] = thread
            write_json(output / "conversations.json", threads)
    thread = threads[group]
    if case["source"] == "upload" and not (folder / "request.json").exists():
        # The confirmation is idempotent for the exact same reviewed schema.
        fixture = next(
            c["upload"] for c in cases if c["conversation"] == group and c.get("upload")
        )
        review = call(
            "POST",
            f"/api/conversations/{thread}/upload/confirm",
            json=fixture["review"],
        )
        write_json(folder / "review.json", review)
    start = time.monotonic()
    request_file = folder / "request.json"
    if recorded is not None:
        if recorded["thread_id"] != thread:
            raise RuntimeError("Receipt conversation does not match registry")
        run_id = recorded["run_id"]
    elif request_file.exists():
        request = json.loads(request_file.read_text())
        if any(request.get(key) != value for key, value in case.items()):
            raise RuntimeError("Prompt changed; use a new receipt directory")
        if request["thread_id"] != thread:
            raise RuntimeError("Receipt conversation does not match registry")
        run_id = request["run_id"]
    else:
        message = {"message": case["question"]}
        if selected_case := case.get("selected_dataset_from"):
            parent = json.loads((output / selected_case / "run.json").read_text())
            candidates = (parent.get("answer") or {}).get("results", [])
            label = case.get("selected_dataset_label")
            matches = [r for r in candidates if not label or r.get("short_label") == label]
            if len(matches) != 1:
                raise ValueError("Selected dataset fixture requires one exact saved label from the preceding receipt.")
            message["selected_result_id"] = matches[0]["result_id"]
        created = call(
            "POST",
            f"/api/conversations/{thread}/messages",
            json=message,
        )
        run_id = created["run_id"]
        write_json(request_file, {**case, "thread_id": thread, "run_id": run_id})
    answered = (folder / "clarification-submitted.json").exists()
    previous = None
    while True:
        state = call("GET", f"/api/runs/{run_id}")
        status = (state["status"], state["phase"])
        if status != previous:
            print(
                case["id"], run_id, status, round(time.monotonic() - start), flush=True
            )
            previous = status
        if (
            state["status"] == "clarification_required"
            and case.get("clarification")
            and not answered
        ):
            write_json(folder / "clarification.json", state)
            call(
                "POST",
                f"/api/runs/{run_id}/clarification",
                json={"message": case["clarification"]},
            )
            answered = True
            write_json(
                folder / "clarification-submitted.json",
                {"message": case["clarification"]},
            )
        elif state["status"] not in ACTIVE_STATUSES:
            break
        if time.monotonic() - start > 1200:
            stopped = call("POST", f"/api/runs/{run_id}/stop")
            write_json(folder / "run.json", stopped)
            raise TimeoutError(
                f"{case['id']}: exceeded live-test wall time; stop requested"
            )
        time.sleep(3)
    state["test_elapsed_seconds"] = round(time.monotonic() - start, 2)
    save_receipts(client, call, folder, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "tests/fixtures/documented_examples.json"
    )
    parser.add_argument(
        "--case",
        action="append",
        help="Case ID; prerequisites must already have receipts.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Retain failures and continue independent cases.",
    )
    parser.add_argument(
        "--study", type=Path, help="Predeclared paired-study protocol JSON."
    )
    parser.add_argument("--variant", choices=["baseline", "candidate"])
    parser.add_argument("--repetition", type=int, default=1)
    args = parser.parse_args()
    cases = json.loads(args.corpus.read_text())
    try:
        validate_cases(cases)
    except ValueError as exc:
        parser.error(str(exc))
    if args.repetition < 1 or bool(args.study) != bool(args.variant):
        parser.error(
            "Study and variant must be supplied together; repetition must be positive"
        )
    unknown = set(args.case or []) - {case["id"] for case in cases}
    if unknown:
        parser.error(f"Unknown case IDs: {', '.join(sorted(unknown))}")
    selected = [
        case["id"] for case in cases if not args.case or case["id"] in args.case
    ]
    uploads = {c["upload"]["path"] for c in cases if c.get("upload")}
    study = json.loads(args.study.read_text()) if args.study else None
    args.output.mkdir(parents=True, exist_ok=True)
    threads_file = args.output / "conversations.json"
    threads = json.loads(threads_file.read_text()) if threads_file.exists() else {}
    source_ids = sorted(
        {case["source"] for case in cases if case["source"] != "upload"}
    )
    parameters = [("source_id", source_id) for source_id in source_ids]
    with httpx.Client(base_url=args.base_url, timeout=60) as client:

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        health = call("GET", "/health")
        execution = call("GET", "/api/evaluation-context", params=parameters)
        manifest = {
            "corpus": cases,
            "case_ids": [case["id"] for case in cases],
            "execution": execution,
            "uploads": {path: file_hash(ROOT / path) for path in sorted(uploads)},
            "evaluation_sha256": files_hash(
                {p.name: file_hash(p) for p in sorted((ROOT / "scripts").glob("*.py"))}
            ),
            "study": study,
            "variant": args.variant,
            "repetition": args.repetition,
        }
        manifest_file = args.output / "manifest.json"
        if manifest_file.exists() and json.loads(manifest_file.read_text()) != manifest:
            raise RuntimeError(
                "Inputs, code, study or runtime changed; use a new receipt directory"
            )
        write_json(manifest_file, manifest)
        write_json(args.output / "health.json", health)
        failed = []
        for case in cases:
            if case["id"] not in selected:
                continue
            folder = args.output / case["id"]
            folder.mkdir(exist_ok=True)
            state = None
            try:
                state = run_case(case, cases, args.output, threads, client, call)
                if state["status"] != expected_status(case):
                    raise RuntimeError(
                        f"{case['id']}: {state['status']}; review the saved run"
                    )
                print(case["id"], "FINISHED", state["status"], flush=True)
            except Exception as exc:
                write_json(
                    folder / "runner-error.json",
                    {
                        "error": str(exc),
                        "type": type(exc).__name__,
                        "reason": "unexpected_status"
                        if state is not None
                        else "collection",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                failed.append(case["id"])
                if not args.keep_going:
                    raise
                print(case["id"], "RETAINED FAILURE", str(exc), flush=True)
            else:
                (folder / "runner-error.json").unlink(missing_ok=True)
        after = call("GET", "/api/evaluation-context", params=parameters)
        write_json(args.output / "execution-after.json", after)
        if after != execution:
            raise RuntimeError(
                "Serving code, settings or source changed during evaluation"
            )
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
