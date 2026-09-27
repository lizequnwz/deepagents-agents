"""Run documented questions through a live API and save inspectable receipts.

Requires a running application with model credentials. Invokes the configured
provider and bundled sources; use a separate ANALYTICS_STORAGE_DIR for the API.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


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
        help="Case ID; dependencies must already have receipts.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.corpus.read_text())
    unknown = set(args.case or []) - {case["id"] for case in cases}
    if unknown:
        parser.error(f"Unknown case IDs: {', '.join(sorted(unknown))}")
    paths = [
        *sorted((ROOT / "semantic").glob("*.yaml")),
        ROOT / "db/chinook/chinook.db",
        ROOT / "db/financial/financial.sqlite",
        ROOT / "doc/user/examples/monthly-index.csv",
    ]
    manifest = {
        "corpus": cases,
        "instructions_sha256": hashlib.sha256(
            b"".join(
                p.read_bytes()
                for p in [ROOT / "AGENTS.md", *sorted((ROOT / "skills").rglob("*.md"))]
            )
        ).hexdigest(),
        "sources": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
        "code_sha256": hashlib.sha256(
            b"".join(
                str(p.relative_to(ROOT)).encode() + p.read_bytes()
                for p in sorted((ROOT / "data_analytics_agent").rglob("*.py"))
            )
        ).hexdigest(),
    }
    manifest_file = args.output / "manifest.json"
    if manifest_file.exists() and json.loads(manifest_file.read_text()) != manifest:
        raise RuntimeError(
            "Code, source or corpus changed; use a new receipt directory"
        )
    manifest_file.write_text(json.dumps(manifest, indent=2))
    threads_file = args.output / "conversations.json"
    threads = json.loads(threads_file.read_text()) if threads_file.exists() else {}
    with httpx.Client(base_url=args.base_url, timeout=60) as client:

        def call(method, path, **kwargs):
            r = client.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()

        health = call("GET", "/health")
        (args.output / "health.json").write_text(json.dumps(health, indent=2))
        for case in cases:
            if args.case and case["id"] not in args.case:
                continue
            folder = args.output / case["id"]
            if (folder / "run.json").exists():
                recorded = json.loads((folder / "run.json").read_text())
                if recorded["status"] != "completed":
                    raise RuntimeError(f"{case['id']}: recorded run requires attention")
                print(case["id"], "already recorded; skipping", flush=True)
                continue
            folder.mkdir(exist_ok=True)
            group = case["conversation"]
            for prior in cases[: cases.index(case)]:
                if prior["conversation"] != group:
                    continue
                receipt = args.output / prior["id"] / "run.json"
                if (
                    not receipt.exists()
                    or json.loads(receipt.read_text())["status"] != "completed"
                ):
                    raise RuntimeError(f"{case['id']} requires completed {prior['id']}")
            if group not in threads:
                if case["source"] == "upload":
                    upload = call(
                        "POST",
                        "/api/uploads",
                        params={"filename": "monthly-index.csv"},
                        content=(
                            ROOT / "doc/user/examples/monthly-index.csv"
                        ).read_bytes(),
                    )
                    thread = upload["thread_id"]
                    (folder / "upload.json").write_text(json.dumps(upload, indent=2))
                    review = call(
                        "POST",
                        f"/api/conversations/{thread}/upload/confirm",
                        json={
                            "types": {
                                "month_index": "integer",
                                "revenue_units": "integer",
                            },
                            "grain": "One complete month per row; revenue_units is an index, not currency.",
                            "key_columns": ["month_index"],
                        },
                    )
                    (folder / "review.json").write_text(json.dumps(review, indent=2))
                else:
                    thread = call(
                        "POST", "/api/conversations", json={"source_id": case["source"]}
                    )["thread_id"]
                threads[group] = thread
                threads_file.write_text(json.dumps(threads, indent=2))
            thread = threads[group]
            start = time.monotonic()
            request_file = folder / "request.json"
            if request_file.exists():
                request = json.loads(request_file.read_text())
                if any(request.get(key) != value for key, value in case.items()):
                    raise RuntimeError("Prompt changed; use a new receipt directory")
                if request["thread_id"] != thread:
                    raise RuntimeError("Receipt conversation does not match registry")
                run_id = request["run_id"]
            else:
                created = call(
                    "POST",
                    f"/api/conversations/{thread}/messages",
                    json={"message": case["question"]},
                )
                run_id = created["run_id"]
                request_file.write_text(
                    json.dumps(
                        {**case, "thread_id": thread, "run_id": run_id}, indent=2
                    )
                )
            answered = (folder / "clarification-submitted.json").exists()
            previous = None
            while True:
                state = call("GET", f"/api/runs/{run_id}")
                status = (state["status"], state["phase"])
                if status != previous:
                    print(
                        case["id"],
                        run_id,
                        status,
                        round(time.monotonic() - start),
                        flush=True,
                    )
                    previous = status
                if (
                    state["status"] == "clarification_required"
                    and case.get("clarification")
                    and not answered
                ):
                    (folder / "clarification.json").write_text(
                        json.dumps(state, indent=2)
                    )
                    call(
                        "POST",
                        f"/api/runs/{run_id}/clarification",
                        json={"message": case["clarification"]},
                    )
                    answered = True
                    (folder / "clarification-submitted.json").write_text(
                        json.dumps({"message": case["clarification"]}, indent=2)
                    )
                elif state["status"] not in ("running", "queued", "stopping"):
                    break
                if time.monotonic() - start > 1200:
                    call("POST", f"/api/runs/{run_id}/stop")
                    raise TimeoutError(
                        f"{case['id']}: exceeded live-test wall time; stop requested"
                    )
                time.sleep(3)
            state["test_elapsed_seconds"] = round(time.monotonic() - start, 2)
            if state["status"] != "completed":
                (folder / "run.json").write_text(json.dumps(state, indent=2))
                raise RuntimeError(
                    f"{case['id']}: {state['status']}; review the saved run"
                )
            answer = state.get("answer") or state.get("findings") or {}
            for ref in answer.get("results", []):
                rid = ref["result_id"]
                r = client.get(f"/api/results/{rid}/download", params={"format": "csv"})
                r.raise_for_status()
                (folder / f"{rid}.csv").write_bytes(r.content)
                (folder / f"{rid}.json").write_text(
                    json.dumps(call("GET", f"/api/results/{rid}"), indent=2)
                )
            if answer.get("report"):
                rid = answer["report"]["report_id"]
                report = call("GET", f"/api/reports/{rid}")
                (folder / "report.json").write_text(json.dumps(report, indent=2))
                (folder / "report.html").write_text(report["html"])
                (folder / "report-spec.json").write_text(
                    json.dumps(call("GET", f"/api/reports/{rid}/spec"), indent=2)
                )
            (folder / "run.json").write_text(json.dumps(state, indent=2))
            print(
                case["id"], "FINISHED", state["status"], state.get("error"), flush=True
            )


if __name__ == "__main__":
    main()
