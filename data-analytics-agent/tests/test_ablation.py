"""Mechanical study gates over fabricated receipts, not model-quality evidence."""

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import httpx
import pytest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.evaluation import file_hash, receipt_hash
from scripts.compare_ablation import compare_trials, metric_value
from scripts.evaluate_documented_examples import (
    main as evaluate,
    save_receipts,
    validate_cases,
)
from scripts.grade_documented_examples import RUBRIC, grade_receipts
from scripts.prepare_ablation_fixtures import prepare_project

ROOT = Path(__file__).resolve().parents[1]
STUDY = json.loads((ROOT / "doc/roadmap/prompt-ownership-study.json").read_text())


def write(path, payload):
    path.write_text(json.dumps(payload))


def check(status="pass"):
    return {
        "status": status,
        "evidence": "fabricated receipt for reducer regression only",
    }


def reviewed(run_id):
    return {"run_id": run_id, "criteria": {name: check() for name in RUBRIC}}


@pytest.fixture
def trials(tmp_path):
    folders = []
    for variant in ("baseline", "candidate"):
        for repeat in range(1, 4):
            folder = tmp_path / f"{variant}-{repeat}"
            folder.mkdir()
            corpus = [
                {
                    "id": f"case-{i}",
                    "conversation": f"case-{i}",
                    "expected_outcome": "metadata",
                }
                for i in range(20)
            ]
            execution = {
                "code_files": {"data_analytics_agent/coordinator.py": variant},
                "instruction_files": {},
                "runtime": {"model_provider": "openai", "model": "fixture"},
                "sources": {},
                "versions": {"python": "fixture"},
                "dependencies_sha256": "same",
                "registry_sha256": "same",
            }
            write(
                folder / "manifest.json",
                {
                    "corpus": corpus,
                    "case_ids": [case["id"] for case in corpus],
                    "execution": execution,
                    "uploads": {},
                    "evaluation_sha256": "same",
                    "study": STUDY,
                    "variant": variant,
                    "repetition": repeat,
                },
            )
            write(folder / "execution-after.json", execution)
            outcomes = {}
            for case in corpus:
                case_id = case["id"]
                destination = folder / case_id
                destination.mkdir()
                run_id = f"{variant}-{repeat}-{case_id}"
                write(
                    destination / "run.json",
                    {
                        "run_id": run_id,
                        "thread_id": run_id,
                        "status": "completed",
                        "answer": {"answer": "metadata only"},
                        "events": [],
                        "run_diagnostics": {
                            "tokens": {
                                "input_tokens": 100 if variant == "baseline" else 80
                            },
                            "token_usage_partial": False,
                            "model_calls_missing_usage": 0,
                        },
                    },
                )
                outcomes[case_id] = {
                    "outcome": "pass",
                    "failures": [],
                    "unreviewed": [],
                    "run_id": run_id,
                    "run_sha256": file_hash(destination / "run.json"),
                    "receipt_sha256": receipt_hash(destination),
                    "hard_boundaries": check(),
                    "first_attempt": check(),
                    "scenario_checks": {
                        name: check() for name in STUDY["required_scenarios"]
                    },
                }
            write(
                folder / "grades.json",
                {
                    "manifest_sha256": file_hash(folder / "manifest.json"),
                    "execution_stable": True,
                    "evidence_level": "live_provider",
                    "cases": outcomes,
                },
            )
            folders.append(folder)
    return folders


def update_grade(folder, case_id, change):
    path = folder / "grades.json"
    grades = json.loads(path.read_text())
    grades["cases"][case_id].update(change)
    write(path, grades)


def test_paired_gate_reports_case_uncertainty_and_does_not_hide_unknown_repairs(trials):
    outcome = compare_trials(STUDY, trials)
    assert outcome["decision"] == "eligible_for_adoption"
    assert outcome["median_relative_improvement"] == pytest.approx(0.2)
    assert outcome["confidence_interval"] == pytest.approx([0.2, 0.2])
    assert outcome["cases"][0]["pairs"][0]["candidate_repair_count"] is None


def test_new_failure_and_first_attempt_regression_retain_baseline(trials):
    update_grade(trials[-1], "case-0", {"outcome": "fail", "failures": ["arithmetic"]})
    outcome = compare_trials(STUDY, trials)
    assert outcome["decision"] == "retain_baseline"
    assert outcome["regressions"] == [{"case_id": "case-0", "repetition": 3}]
    assert outcome["median_relative_improvement"] is None
    assert outcome["confidence_interval"] is None
    update_grade(
        trials[-1],
        "case-0",
        {"outcome": "pass", "failures": [], "first_attempt": check("fail")},
    )
    assert compare_trials(STUDY, trials)["decision"] == "retain_baseline"


def test_missing_usage_is_unknown_even_with_zero_token_counters():
    assert (
        metric_value(
            {"status": "completed", "run_diagnostics": {"tokens": {"input_tokens": 0}}},
            "input_tokens",
        )
        is None
    )
    assert (
        metric_value(
            {"status": "completed", "run_diagnostics": {"elapsed_ms": 0}}, "elapsed_ms"
        )
        == 0
    )
    assert (
        metric_value(
            {"status": "completed", "run_diagnostics": {"elapsed_ms": float("nan")}},
            "elapsed_ms",
        )
        is None
    )


@pytest.mark.parametrize("status", ["running", "paused", "approval_required", "failed"])
def test_incomplete_execution_has_no_comparable_performance_metric(status):
    run = {
        "status": status,
        "run_diagnostics": {
            "elapsed_ms": 1,
            "tokens": {"input_tokens": 10},
            "token_usage_partial": False,
            "model_calls_missing_usage": 0,
        },
    }
    assert metric_value(run, "elapsed_ms") is None
    assert metric_value(run, "input_tokens") is None


def test_missing_review_or_unexercised_boundary_prevents_adoption(trials):
    update_grade(trials[-1], "case-0", {"outcome": "unreviewed"})
    result = compare_trials(STUDY, trials)
    assert result["decision"] == "inconclusive"
    assert result["median_relative_improvement"] is None
    assert result["confidence_interval"] is None
    update_grade(trials[-1], "case-0", {"outcome": "pass"})
    grades = json.loads((trials[-1] / "grades.json").read_text())
    for outcome in grades["cases"].values():
        outcome["scenario_checks"].pop("stop_resume")
    write(trials[-1] / "grades.json", grades)
    assert any(
        item["reason"] == "scenario:stop_resume"
        for item in compare_trials(STUDY, trials)["unknown"]
    )


@pytest.mark.parametrize("field", ["sources", "versions", "runtime"])
def test_uncontrolled_source_provider_or_settings_change_is_rejected(trials, field):
    folder = trials[-1]
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["execution"][field]["extra"] = "changed"
    write(folder / "manifest.json", manifest)
    write(folder / "execution-after.json", manifest["execution"])
    grades = json.loads((folder / "grades.json").read_text())
    grades["manifest_sha256"] = file_hash(folder / "manifest.json")
    write(folder / "grades.json", grades)
    with pytest.raises(ValueError):
        compare_trials(STUDY, trials)


def test_stale_evidence_and_duplicate_trials_are_rejected(trials):
    update_grade(trials[-1], "case-0", {"outcome": "completed"})
    with pytest.raises(ValueError, match="Unknown graded outcome"):
        compare_trials(STUDY, trials)
    update_grade(trials[-1], "case-0", {"outcome": "pass"})
    (trials[-1] / "case-0" / "extra.csv").write_text("revised after grading")
    with pytest.raises(ValueError, match="stale"):
        compare_trials(STUDY, trials)
    with pytest.raises(ValueError, match="reused"):
        compare_trials(STUDY, [*trials, trials[0]])


def test_all_case_ids_are_graded_even_if_review_omits_them(trials):
    folder = trials[0]
    payload = grade_receipts(
        folder,
        {
            "evidence_level": "scripted",
            "cases": {"case-0": reviewed("baseline-1-case-0")},
        },
    )
    assert len(payload["cases"]) == 20
    assert payload["cases"]["case-0"]["outcome"] == "pass"
    assert payload["cases"]["case-1"]["outcome"] == "unreviewed"
    (folder / "case-2" / "run.json").unlink()
    payload = grade_receipts(folder, {"cases": {}})
    assert payload["cases"]["case-2"]["unreviewed"] == ["missing_receipt"]


def test_upload_corpus_is_explicit_and_cannot_change_source():
    corpus = json.loads((ROOT / "tests/fixtures/ablation_cases.json").read_text())
    validate_cases(corpus)
    assert len(corpus) == 25
    assert len({case["id"] for case in corpus if case["held_out"]}) >= 3
    for case in corpus:
        if case.get("upload"):
            assert (ROOT / case["upload"]["path"]).is_file()
    with pytest.raises(ValueError, match="schema review"):
        validate_cases([{"id": "missing", "source": "upload", "conversation": "file"}])
    with pytest.raises(ValueError, match="change source"):
        validate_cases(
            [
                {"id": "a", "source": "fixture", "conversation": "same"},
                {"id": "b", "source": "other", "conversation": "same"},
            ]
        )


def test_frozen_synthetic_sources_and_serving_fingerprints(
    test_settings, tmp_path, monkeypatch
):
    first, second = tmp_path / "first", tmp_path / "second"
    prepare_project(first)
    prepare_project(second)
    assert file_hash(first / "db/fixture.sqlite") == file_hash(
        second / "db/fixture.sqlite"
    )
    settings = replace(
        test_settings,
        project_root=first,
        data_sources_config_path=first / "data_sources.yaml",
    )
    services = Services(settings=settings)
    assert services.source_summary("fixture").ready
    with TestClient(create_app(services)) as client:
        response = client.get(
            "/api/evaluation-context", params={"source_id": "fixture"}
        )
        assert response.status_code == 200, response.text
        before = response.json()
        assert before["runtime"]["model"] == settings.model
        assert (
            before["runtime"]["analysis_parallel_workers"]
            == settings.analysis_parallel_workers
        )
        assert before["sources"]["fixture"]["frozen"]
        assert "test-key" not in response.text
        with sqlite3.connect(first / "db/fixture.sqlite") as db:
            assert db.execute(
                "SELECT COUNT(*), SUM(revenue) FROM facts"
            ).fetchone() == pytest.approx((120, 26280))
            db.execute("UPDATE facts SET revenue=0 WHERE observation_id=1")
        after = client.get(
            "/api/evaluation-context", params={"source_id": "fixture"}
        ).json()
        assert before["sources"] != after["sources"]
        monkeypatch.setenv("OPENAI_BASE_URL", "http://fixture-provider.invalid/private")
        routed = client.get(
            "/api/evaluation-context", params={"source_id": "fixture"}
        ).json()
        assert after["runtime"] != routed["runtime"]
        assert "fixture-provider.invalid" not in json.dumps(routed)
        assert (
            client.get(
                "/api/evaluation-context", params={"source_id": "unknown"}
            ).status_code
            == 422
        )


def test_file_only_fingerprints_and_frozen_workbook_review(test_settings, tmp_path):
    project = tmp_path / "file-project"
    prepare_project(project)
    settings = replace(
        test_settings,
        project_root=project,
        data_sources_config_path=project / "missing.yaml",
    )
    services = Services(settings=settings)
    with TestClient(create_app(services)) as client:
        context = client.get("/api/evaluation-context").json()
        assert context["sources"] == {} and context["registry_sha256"] is None
        case = next(
            c
            for c in json.loads(
                (ROOT / "tests/fixtures/ablation_cases.json").read_text()
            )
            if c["id"] == "19-excel"
        )
        fixture = case["upload"]
        path = ROOT / fixture["path"]
        uploaded = client.post(
            "/api/uploads",
            params={"filename": path.name, **fixture["selection"]},
            content=path.read_bytes(),
        )
        assert uploaded.status_code == 201, uploaded.text
        thread = uploaded.json()["thread_id"]
        confirmed = client.post(
            f"/api/conversations/{thread}/upload/confirm", json=fixture["review"]
        )
        assert confirmed.status_code == 200, confirmed.text
        saved = services.results.get_unscoped(confirmed.json()["result_id"])
        assert saved.row_count == 8
        assert [row["customer_id"] for row in saved.rows] == [
            f"{i:05d}" for i in range(1, 9)
        ]
        assert sum(row["revenue_units"] for row in saved.rows) == 1080


def test_report_grade_requires_collected_artifacts(tmp_path):
    folder = tmp_path / "reported"
    folder.mkdir()
    execution = {"fixture": "stable"}
    write(
        tmp_path / "manifest.json",
        {
            "corpus": [{"id": "reported", "expected_outcome": "complete"}],
            "case_ids": ["reported"],
            "execution": execution,
        },
    )
    write(tmp_path / "execution-after.json", execution)
    write(
        folder / "run.json",
        {
            "run_id": "r",
            "status": "completed",
            "answer": {"answer": "done", "report": {"report_id": "report"}},
        },
    )
    result = grade_receipts(tmp_path, {"cases": {"reported": reviewed("r")}})
    assert result["cases"]["reported"]["outcome"] == "unreviewed"
    assert "missing_artifacts" in result["cases"]["reported"]["unreviewed"]


def test_failed_download_preserves_run_before_retry(tmp_path):
    state = {
        "run_id": "run",
        "status": "completed",
        "answer": {"results": [{"result_id": "r"}]},
    }
    requests = []

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(500)

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            save_receipts(client, lambda *args: {}, tmp_path, state)
    assert json.loads((tmp_path / "run.json").read_text()) == state
    assert requests == ["/api/results/r/download"]
    with httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"fixture")
        ),
    ) as client:
        save_receipts(client, lambda *args: {}, tmp_path, state)
    assert set(json.loads((tmp_path / "artifact-hashes.json").read_text())) == {
        "r.csv",
        "r.parquet",
    }


def test_batch_retains_failure_and_continues_independent_cases(tmp_path, monkeypatch):
    corpus = [
        {
            "id": name,
            "source": "fixture",
            "conversation": name,
            "question": name,
            "expected_outcome": "metadata",
        }
        for name in ("failed", "good")
    ]
    path = tmp_path / "corpus.json"
    write(path, corpus)
    output = tmp_path / "receipts"
    counters = {"threads": 0, "runs": 0}

    def respond(request):
        if request.url.path in {"/health", "/api/evaluation-context"}:
            return httpx.Response(200, json={"fixture": "stable"})
        if request.url.path == "/api/conversations":
            counters["threads"] += 1
            return httpx.Response(200, json={"thread_id": f"t{counters['threads']}"})
        if request.method == "POST":
            counters["runs"] += 1
            return httpx.Response(200, json={"run_id": f"r{counters['runs']}"})
        failed = request.url.path.endswith("r1")
        return httpx.Response(
            200,
            json={
                "run_id": "r1" if failed else "r2",
                "status": "failed" if failed else "completed",
                "phase": "done",
                "events": [],
                "answer": None if failed else {"answer": "metadata"},
            },
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--base-url",
            "http://test",
            "--output",
            str(output),
            "--corpus",
            str(path),
            "--keep-going",
        ],
    )
    with pytest.raises(SystemExit) as exit:
        evaluate()
    assert exit.value.code == 1
    assert json.loads((output / "failed/run.json").read_text())["status"] == "failed"
    assert json.loads((output / "good/run.json").read_text())["status"] == "completed"
    assert (output / "execution-after.json").exists()


def test_prompt_candidate_applies_to_current_files_and_compiles(tmp_path):
    for path in STUDY["changed_files"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    subprocess.run(
        ["git", "apply", str(ROOT / "doc/roadmap/prompt-ownership.patch")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    for path in tmp_path.rglob("*.py"):
        compile(path.read_text(), str(path), "exec")
