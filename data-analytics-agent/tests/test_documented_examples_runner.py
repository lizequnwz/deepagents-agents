"""The live runner must not silently create a new dependent conversation/run."""

import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "example_runner", ROOT / "scripts/evaluate_documented_examples.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        assert request.method == "GET", "Must not resubmit an existing question"
        return httpx.Response(200, json={"status": "completed", "phase": "done"})

    client_type = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )

    def invoke(case):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "runner",
                "--base-url",
                "http://test",
                "--output",
                str(tmp_path),
                "--case",
                case,
            ],
        )
        module.main()

    return invoke, requests


def test_rejects_unknown_case_without_provider_call(runner):
    invoke, requests = runner
    with pytest.raises(SystemExit) as error:
        invoke("not-a-case")
    assert error.value.code == 2
    assert requests == []


def test_followup_requires_completed_prior_case(runner):
    invoke, requests = runner
    with pytest.raises(RuntimeError, match="requires completed 01-revenue"):
        invoke("02-trend")
    assert requests == [("GET", "/health"), ("GET", "/api/evaluation-context")]


def test_reattaches_recorded_run_without_resubmission(runner, tmp_path):
    invoke, requests = runner
    case = json.loads((ROOT / "tests/fixtures/documented_examples.json").read_text())[0]
    (tmp_path / "conversations.json").write_text(json.dumps({"revenue": "thread-1"}))
    folder = tmp_path / case["id"]
    folder.mkdir()
    (folder / "request.json").write_text(
        json.dumps(
            {
                **case,
                "thread_id": "thread-1",
                "run_id": "run-1",
            }
        )
    )
    invoke(case["id"])
    assert requests == [
        ("GET", "/health"),
        ("GET", "/api/evaluation-context"),
        ("GET", "/api/runs/run-1"),
        ("GET", "/api/evaluation-context"),
    ]
    assert json.loads((folder / "run.json").read_text())["status"] == "completed"


def test_finished_receipts_are_preserved_when_runner_is_repeated(runner, tmp_path):
    invoke, requests = runner
    case = json.loads((ROOT / "tests/fixtures/documented_examples.json").read_text())[0]
    (tmp_path / "conversations.json").write_text(json.dumps({"revenue": "thread-1"}))
    folder = tmp_path / case["id"]
    folder.mkdir()
    (folder / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "completed", "phase": "done"})
    )
    (folder / "artifact-hashes.json").write_text("{}")
    original = (folder / "run.json").read_bytes()
    invoke(case["id"])
    assert (folder / "run.json").read_bytes() == original
    assert ("GET", "/api/runs/run-1") not in requests


def test_reviewed_run_is_reattached_without_new_question(runner, tmp_path):
    invoke, requests = runner
    case = json.loads((ROOT / "tests/fixtures/documented_examples.json").read_text())[0]
    (tmp_path / "conversations.json").write_text(json.dumps({"revenue": "thread-1"}))
    folder = tmp_path / case["id"]
    folder.mkdir()
    recorded = {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "status": "approval_required",
    }
    (folder / "run.json").write_text(json.dumps(recorded))
    invoke(case["id"])
    assert json.loads((folder / "interrupted-run.json").read_text()) == recorded
    assert json.loads((folder / "run.json").read_text())["status"] == "completed"
    assert ("GET", "/api/runs/run-1") in requests
