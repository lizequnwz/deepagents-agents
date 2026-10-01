from __future__ import annotations

import pytest

from data_analytics_agent.approvals import decisions_to_command
from data_analytics_agent.schemas import ApprovalAction, ApprovalRequest, Decision


@pytest.fixture
def approval() -> ApprovalRequest:
    return ApprovalRequest(
        interrupt_id="sql-review-1",
        actions=[
            ApprovalAction(
                action_name="execute_sql",
                query="SELECT Name FROM Artist LIMIT 5",
                allowed_decisions=["approve", "edit", "reject"],
            )
        ],
    )


def test_approve_resume_shape(approval: ApprovalRequest) -> None:
    command = decisions_to_command(approval, [Decision(action="approve")])
    assert command.resume == {
        approval.interrupt_id: {"decisions": [{"type": "approve"}]}
    }


def test_edit_preserves_action_order(
    approval: ApprovalRequest,
) -> None:
    edited = "SELECT Name FROM Artist ORDER BY Name LIMIT 10"
    command = decisions_to_command(
        approval, [Decision(action="edit", edited_sql=edited)]
    )
    resume_value = command.resume[approval.interrupt_id]
    assert resume_value["decisions"][0]["edited_action"] == {
        "name": "execute_sql",
        "args": {"query": edited},
    }


def test_empty_edit_does_not_create_resume_command(
    approval: ApprovalRequest,
) -> None:
    with pytest.raises(ValueError):
        decisions_to_command(
            approval,
            [Decision(action="edit", edited_sql="")],
        )


def test_reject_includes_feedback(approval: ApprovalRequest) -> None:
    command = decisions_to_command(
        approval,
        [Decision(action="reject", feedback="Group by country instead.")],
    )
    assert command.resume == {
        approval.interrupt_id: {
            "decisions": [{"type": "reject", "message": "Group by country instead."}]
        }
    }


def test_review_without_supported_decisions_cannot_be_presented():
    from types import SimpleNamespace
    from pydantic import ValidationError
    from data_analytics_agent.approvals import _extract_approval

    interrupt = SimpleNamespace(
        id="unsupported-review",
        value={
            "action_requests": [{"name": "execute_sql", "args": {"query": "SELECT 1"}}],
            "review_configs": [{"allowed_decisions": ["respond"]}],
        },
    )
    with pytest.raises(ValidationError, match="allowed_decisions"):
        _extract_approval([interrupt])


def test_python_edit_preserves_parent_result_and_exact_code() -> None:
    approval = ApprovalRequest(
        interrupt_id="python-review-1",
        actions=[
            ApprovalAction(
                action_name="execute_analysis_python",
                query='analysis_outputs = {"Mean": df.value.mean()}',
                allowed_decisions=["approve", "edit", "reject"],
                review_type="python",
                arguments={"inputs": {"data": "result-1"}},
            )
        ],
    )
    edited = 'analysis_outputs = {"Median": df.value.median()}\n'

    command = decisions_to_command(
        approval,
        [Decision(action="edit", edited_python=edited)],
    )

    resume_value = command.resume[approval.interrupt_id]
    assert resume_value["decisions"][0]["edited_action"] == {
        "name": "execute_analysis_python",
        "args": {"inputs": {"data": "result-1"}, "code": edited},
    }


def test_python_review_resolves_every_named_input_and_rejects_foreign_input(workspace):
    from types import SimpleNamespace
    from data_analytics_agent.approvals import _extract_approval

    w = workspace

    def save(thread, value):
        return w.results.save(
            columns=["value"],
            rows=[{"value": value}],
            thread_id=thread,
            source_id="test",
        )

    first, second, foreign = (
        save(w.thread, 1),
        save(w.thread, 2),
        save("other-thread", 3),
    )

    def interrupt(inputs):
        return [
            SimpleNamespace(
                id="review",
                value={
                    "action_requests": [
                        {
                            "name": "execute_analysis_python",
                            "args": {
                                "inputs": inputs,
                                "code": "analysis_outputs={'total':3}",
                            },
                        }
                    ]
                },
            )
        ]

    review = _extract_approval(
        interrupt({"first": first.result_id, "second": second.result_id}),
        result_store=w.results,
        thread_id=w.thread,
    )
    assert set(review.actions[0].input_datasets) == {"first", "second"}
    assert review.actions[0].input_datasets["second"].sample_rows == [{"value": 2}]
    import pytest

    with pytest.raises(RuntimeError, match="out-of-scope"):
        _extract_approval(
            interrupt({"first": first.result_id, "foreign": foreign.result_id}),
            result_store=w.results,
            thread_id=w.thread,
        )
