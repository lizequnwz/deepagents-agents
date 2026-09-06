"""Exact edited SQL/Python approval translation."""

from typing import Any
from langgraph.types import Command
from data_analytics_agent.schemas import ApprovalRequest, Decision
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore, StoreNotFound
from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits


def _single_decision(
    approval: ApprovalRequest,
    decisions: list[Decision],
) -> Decision:
    if len(decisions) != 1:
        raise ValueError("Exactly one decision is required for this review.")
    decision = decisions[0]
    if decision.action not in approval.allowed_decisions:
        raise ValueError(f"Decision {decision.action!r} is not allowed.")
    return decision


def decisions_to_command(
    approval: ApprovalRequest,
    decisions: list[Decision],
) -> Command:
    """Validate and translate API decisions to LangGraph's resume shape."""

    decision = _single_decision(approval, decisions)

    if decision.action == "reject":
        default_feedback = (
            "Revise the Python and submit it for review again."
            if approval.review_type == "python"
            else "Revise the query and submit it for review again."
        )
        translated = {
            "type": "reject",
            "message": decision.feedback or default_feedback,
        }
        return Command(
            resume={
                approval.interrupt_id: {"decisions": [translated]},
            }
        )

    if decision.action == "approve":
        translated = {"type": "approve"}
    elif approval.review_type == "sql":
        if not decision.edited_sql:
            raise ValueError("edited_sql is required for an edit decision.")
        translated = {
            "type": "edit",
            "edited_action": {
                "name": approval.action_name,
                "args": {**approval.arguments, "query": decision.edited_sql},
            },
        }
    else:
        if decision.edited_python is None:
            raise ValueError("edited_python is required for a Python edit decision.")
        if not decision.edited_python.strip():
            raise ValueError("Reviewed Python cannot be empty.")
        translated = {
            "type": "edit",
            "edited_action": {
                "name": approval.action_name,
                "args": {
                    **approval.arguments,
                    "code": decision.edited_python,
                },
            },
        }
    return Command(
        resume={
            approval.interrupt_id: {"decisions": [translated]},
        }
    )


def _extract_approval(
    interrupts: list[Any],
    *,
    source: DataSource | None = None,
    result_store: ResultStore | None = None,
    thread_id: str = "",
    analysis_limits: PythonExecutionLimits | None = None,
) -> ApprovalRequest:
    for interrupt in interrupts:
        interrupt_id = getattr(interrupt, "id", None)
        if not isinstance(interrupt_id, str) or not interrupt_id:
            raise RuntimeError("The run interrupted without a resumable interrupt ID.")
        value = getattr(interrupt, "value", interrupt)
        if not isinstance(value, dict):
            continue
        requests = value.get("action_requests") or []
        configs = value.get("review_configs") or []
        for index, action in enumerate(requests):
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            arguments = action.get("args") or action.get("arguments") or {}
            allowed = ["approve", "edit", "reject"]
            if index < len(configs) and isinstance(configs[index], dict):
                configured = configs[index].get("allowed_decisions")
                if isinstance(configured, list):
                    allowed = [
                        item
                        for item in configured
                        if item in {"approve", "edit", "reject"}
                    ]
            if not isinstance(arguments, dict):
                continue
            query = arguments.get("query")
            if name in {"execute_sql", "query_saved_results"} and isinstance(
                query, str
            ):
                return ApprovalRequest(
                    interrupt_id=interrupt_id,
                    action_name=name,
                    query=query,
                    arguments=arguments,
                    allowed_decisions=allowed,
                    source_id=source.source_id if source else "",
                    dialect=source.dialect if source else "sqlite",
                    timeout_seconds=(source.limits.timeout_seconds if source else 10),
                    max_result_rows=(
                        source.limits.max_result_rows if source else 10_000
                    ),
                    description=(
                        "Review the generated SQL before it is executed. "
                        "The database has not been queried yet."
                    ),
                )
            code = arguments.get("code")
            inputs = arguments.get("inputs") or {}
            result_id = next(iter(inputs.values()), None)
            if (
                name == "execute_analysis_python"
                and isinstance(code, str)
                and isinstance(result_id, str)
                and result_store is not None
            ):
                try:
                    result = result_store.get(
                        result_id,
                        thread_id,
                        source_id=source.source_id if source else None,
                    )
                except StoreNotFound as exc:
                    raise RuntimeError(
                        "The Python review references an out-of-scope result."
                    ) from exc
                limits = analysis_limits or PythonExecutionLimits()
                return ApprovalRequest(
                    interrupt_id=interrupt_id,
                    action_name=name,
                    query=code,
                    arguments=arguments,
                    allowed_decisions=allowed,
                    review_type="python",
                    source_id=result.source_id,
                    timeout_seconds=limits.timeout_seconds,
                    parent_result_id=result.result_id,
                    originating_question=result.originating_question,
                    executed_sql=result.executed_sql,
                    columns=result.columns,
                    sample_rows=result.preview,
                    profile=result.profile,
                    row_count=result.row_count,
                    truncated=result.truncated,
                    description=(
                        "Review the complete generated Python before it is "
                        "executed against the scoped saved result."
                    ),
                )
    raise RuntimeError("The run interrupted without a reviewable action.")
