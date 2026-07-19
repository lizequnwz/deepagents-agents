from __future__ import annotations

import pytest

from data_analytics_agent.run_manager import decisions_to_command
from data_analytics_agent.schemas import (
    ApprovalRequest,
    Decision,
)


@pytest.fixture
def approval() -> ApprovalRequest:
    return ApprovalRequest(
        action_name="execute_sql",
        query="SELECT Name FROM Artist LIMIT 5",
        allowed_decisions=["approve", "edit", "reject"],
    )


def test_approve_resume_shape(approval: ApprovalRequest) -> None:
    command = decisions_to_command(approval, [Decision(action="approve")])
    assert command.resume == {"decisions": [{"type": "approve"}]}


def test_edit_is_validated_and_preserves_action_order(
    approval: ApprovalRequest,
) -> None:
    edited = "SELECT Name FROM Artist ORDER BY Name LIMIT 10"
    command = decisions_to_command(
        approval, [Decision(action="edit", edited_sql=edited)]
    )
    assert command.resume["decisions"][0]["edited_action"] == {
        "name": "execute_sql",
        "args": {"query": edited},
    }


def test_invalid_edit_does_not_create_resume_command(
    approval: ApprovalRequest,
) -> None:
    with pytest.raises(ValueError):
        decisions_to_command(
            approval,
            [Decision(action="edit", edited_sql="DROP TABLE Artist")],
        )


def test_reject_includes_feedback(approval: ApprovalRequest) -> None:
    command = decisions_to_command(
        approval,
        [Decision(action="reject", feedback="Group by country instead.")],
    )
    assert command.resume == {
        "decisions": [
            {"type": "reject", "message": "Group by country instead."}
        ]
    }
