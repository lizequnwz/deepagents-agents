from scripts.grade_documented_examples import RUBRIC, grade


def complete_run(**answer):
    return {"status": "completed", "answer": {"answer": "done", "report": {"report_id": "r"}, **answer}}


def reviewed(status="pass"):
    return {
        "criteria": {
            name: {
                "status": status,
                "evidence": "receipt/table.csv: independently recomputed",
            }
            for name in RUBRIC
        }
    }


def test_completed_report_is_not_an_accuracy_pass():
    assert (
        grade(complete_run(), {})["outcome"]
        == "unreviewed"
    )


def test_narrative_disagreement_fails_even_with_complete_report():
    review = reviewed()
    review["criteria"]["report_agreement"]["status"] = "fail"
    result = grade(complete_run(), review)
    assert result["outcome"] == "fail"
    assert result["failures"] == ["report_agreement"]


def test_partial_and_unsubstantiated_reviews_cannot_pass():
    assert (
        grade(complete_run(partial=True), reviewed())[
            "outcome"
        ]
        == "fail"
    )
    review = reviewed()
    review["criteria"]["units"]["evidence"] = ""
    assert (
        grade(complete_run(), review)["outcome"]
        == "unreviewed"
    )


def test_complete_evidence_review_passes():
    assert (
        grade(complete_run(), reviewed())[
            "outcome"
        ]
        == "pass"
    )


def test_grade_preserves_application_execution_diagnostics():
    diagnostics = {"model_calls": 3, "tool_call_errors": 1}
    result = grade(
        {
            **complete_run(),
            "run_diagnostics": diagnostics,
        },
        reviewed(),
    )
    assert result["diagnostics"] == diagnostics


def test_data_answer_needs_its_report():
    result = grade(complete_run(report=None), reviewed())
    assert result["failures"] == ["missing_report"]


def test_only_predeclared_partial_can_pass_with_evidence():
    run = complete_run(partial=True)
    assert grade(run, reviewed(), expected_outcome="partial")["outcome"] == "pass"
    review = {**reviewed(), "expected_outcome": "partial"}
    assert grade(run, review)["outcome"] == "fail"
    assert grade(complete_run(), reviewed(), expected_outcome="partial")["failures"] == ["expected_partial"]
    assert grade(run, {}, expected_outcome="partial")["outcome"] == "unreviewed"


def test_clarification_passes_only_before_data_access_and_with_review():
    run = {"status": "clarification_required", "clarification": {"question": "Which metric?"}, "events": []}
    assert grade(run, reviewed(), expected_outcome="clarification")["outcome"] == "pass"
    assert grade(run, {}, expected_outcome="clarification")["outcome"] == "unreviewed"
    run["events"] = [{"tool": {"name": "lookup_values"}, "phase": "completed"}]
    assert grade(run, reviewed(), expected_outcome="clarification")["failures"] == ["clarification_after_analysis"]
    assert grade(complete_run(), reviewed(), expected_outcome="clarification")["outcome"] == "fail"


def test_metadata_needs_evidence_that_no_values_were_read():
    run = complete_run(report=None)
    assert grade(run, reviewed(), expected_outcome="metadata")["outcome"] == "unreviewed"
    run["events"] = []
    assert grade(run, reviewed(), expected_outcome="metadata")["outcome"] == "pass"
    run["events"] = [{"tool": {"name": "execute_sql"}, "phase": "started"}]
    assert grade(run, reviewed(), expected_outcome="metadata")["failures"] == ["metadata_data_access"]
