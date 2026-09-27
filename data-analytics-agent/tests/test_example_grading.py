from scripts.grade_documented_examples import RUBRIC, grade


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
        grade({"status": "completed", "answer": {"report": {"id": "r"}}}, {})["outcome"]
        == "unreviewed"
    )


def test_narrative_disagreement_fails_even_with_complete_report():
    review = reviewed()
    review["criteria"]["report_agreement"]["status"] = "fail"
    result = grade({"status": "completed", "answer": {"answer": "done"}}, review)
    assert result["outcome"] == "fail"
    assert result["failures"] == ["report_agreement"]


def test_partial_and_unsubstantiated_reviews_cannot_pass():
    assert (
        grade({"status": "completed", "answer": {"partial": True}}, reviewed())[
            "outcome"
        ]
        == "fail"
    )
    review = reviewed()
    review["criteria"]["units"]["evidence"] = ""
    assert (
        grade({"status": "completed", "answer": {"answer": "done"}}, review)["outcome"]
        == "unreviewed"
    )


def test_complete_evidence_review_passes():
    assert (
        grade({"status": "completed", "answer": {"answer": "done"}}, reviewed())[
            "outcome"
        ]
        == "pass"
    )


def test_grade_preserves_application_execution_diagnostics():
    diagnostics = {"model_calls": 3, "tool_call_errors": 1}
    result = grade(
        {
            "status": "completed",
            "answer": {"answer": "done"},
            "run_diagnostics": diagnostics,
        },
        reviewed(),
    )
    assert result["diagnostics"] == diagnostics
