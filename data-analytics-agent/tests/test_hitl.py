from __future__ import annotations

import pytest

from data_analytics_agent.approvals import decisions_to_command
from data_analytics_agent.schemas import (
    ApprovalRequest,
    Decision,
)


@pytest.fixture
def approval() -> ApprovalRequest:
    return ApprovalRequest(
        interrupt_id="sql-review-1",
        action_name="execute_sql",
        query="SELECT Name FROM Artist LIMIT 5",
        allowed_decisions=["approve", "edit", "reject"],
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


def test_python_edit_preserves_parent_result_and_exact_code() -> None:
    approval = ApprovalRequest(
        interrupt_id="python-review-1",
        action_name="execute_analysis_python",
        query='analysis_outputs = {"Mean": df.value.mean()}',
        allowed_decisions=["approve", "edit", "reject"],
        review_type="python",
        arguments={"inputs": {"data": "result-1"}},
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
