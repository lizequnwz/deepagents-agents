from copy import deepcopy

from general_agent.coding.verification import record_check, verification_summary


def evidence(*, before="a", after="a", exit_code=0, command="pytest", image="sha256:image"):
    return record_check("tests", command, {"revision": before}, {"revision": after},
                        exit_code=exit_code, output="test output", runtime_identity=image)


def summary(checks, *, revision="a", command="pytest", image="sha256:image"):
    return verification_summary(checks, {"tests": command}, {"revision": revision},
                                runtime_identity=image)


def test_only_current_successful_check_evidence_verifies() -> None:
    result = summary([evidence()])
    assert result["outcome"] == "verified"
    assert result["checks"][0]["output"] == "test output"
    assert summary([evidence(exit_code=1)])["outcome"] == "checks_failed"
    assert summary([])["outcome"] == "not_verified"
    assert summary([])["checks"][0]["status"] == "not_run"
    assert summary([evidence(exit_code=None)])["outcome"] == "not_verified"
    assert verification_summary([], {}, {"revision": "a"}, runtime_identity="image")["outcome"] == "not_verified"


def test_passing_self_modifying_check_requires_rerun_on_final_bytes() -> None:
    changed = evidence(before="a", after="b")
    assert changed["exit_code"] == 0
    assert changed["status"] == "stale"
    assert summary([changed], revision="b")["outcome"] == "not_verified"
    assert summary([changed, evidence(before="b", after="b")], revision="b")["outcome"] == "verified"


def test_source_environment_and_command_drift_invalidate_without_editing_evidence() -> None:
    check = evidence()
    original = deepcopy(check)
    for arguments in ({"revision": "b"}, {"image": "new-image"}, {"command": "other-tests"}):
        result = summary([check], **arguments)
        assert result["outcome"] == "not_verified"
        assert result["checks"][0]["status"] == "stale"
    assert check == original


def test_latest_run_of_every_approved_check_decides_outcome() -> None:
    checks = [evidence(exit_code=1), evidence()]
    assert summary(checks)["outcome"] == "verified"
    assert summary(checks + [evidence(exit_code=2)])["outcome"] == "checks_failed"
    approved = {"tests": "pytest", "lint": "ruff check"}
    result = verification_summary(checks, approved, {"revision": "a"}, runtime_identity="sha256:image")
    assert result["outcome"] == "not_verified"
    assert result["checks"][-1]["name"] == "lint"
    assert result["checks"][-1]["status"] == "not_run"


def test_removed_check_is_stale_and_cannot_verify() -> None:
    result = verification_summary([evidence()], {}, {"revision": "a"}, runtime_identity="sha256:image")
    assert result["outcome"] == "not_verified"
    assert result["checks"][0]["status"] == "stale"


def test_baseline_observations_are_retained_without_certifying_final_source():
    baseline = dict(evidence(exit_code=1), phase="baseline")
    result = summary([baseline], revision="different")
    assert result["outcome"] == "not_verified"
    assert result["baseline_failures"] == ["tests"]
    assert result["checks"][0]["status"] == "failed"
    assert result["checks"][-1]["status"] == "not_run"
    assert summary([baseline, evidence()])["outcome"] == "verified"
