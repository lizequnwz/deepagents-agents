"""Exact edited SQL/Python approval translation."""

from typing import Any
from langgraph.types import Command
from data_analytics_agent.schemas import (
    ApprovalAction,
    ApprovalRequest,
    Decision,
    PythonReviewInput,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore, StoreNotFound
from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits


def _translate_decision(action: ApprovalAction, decision: Decision) -> dict:
    if decision.action not in action.allowed_decisions:
        raise ValueError(f"Decision {decision.action!r} is not allowed.")

    if decision.action == "reject":
        default_feedback = (
            "Revise the Python and submit it for review again."
            if action.review_type == "python"
            else "Revise the query and submit it for review again."
        )
        return {
            "type": "reject",
            "message": decision.feedback or default_feedback,
        }

    if decision.action == "approve":
        translated = {"type": "approve"}
    elif action.review_type == "sql":
        if not decision.edited_sql:
            raise ValueError("edited_sql is required for an edit decision.")
        translated = {
            "type": "edit",
            "edited_action": {
                "name": action.action_name,
                "args": {**action.arguments, "query": decision.edited_sql},
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
                "name": action.action_name,
                "args": {
                    **action.arguments,
                    "code": decision.edited_python,
                },
            },
        }
    return translated


def decisions_to_command(
    approval: ApprovalRequest,
    decisions: list[Decision],
) -> Command:
    """Resume one interrupt with exactly one ordered decision per action."""

    if len(decisions) != len(approval.actions):
        raise ValueError("One decision is required for each action in this review.")
    translated = [
        _translate_decision(action, decision)
        for action, decision in zip(approval.actions, decisions, strict=True)
    ]
    return Command(
        resume={
            approval.interrupt_id: {"decisions": translated},
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
        actions = []
        for index, action in enumerate(requests):
            if not isinstance(action, dict):
                raise RuntimeError("The review contains an invalid action.")
            name = action.get("name")
            arguments = action.get("args") or {}
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
                raise RuntimeError("The review contains invalid action arguments.")
            query = arguments.get("query")
            if name in {"execute_sql", "query_saved_results"} and isinstance(
                query, str
            ):
                actions.append(
                    ApprovalAction(
                        action_name=name,
                        query=query,
                        arguments=arguments,
                        allowed_decisions=allowed,
                        source_id=source.source_id if source else "",
                        dialect=(
                            "duckdb"
                            if name == "query_saved_results"
                            else source.dialect
                            if source
                            else "sqlite"
                        ),
                        timeout_seconds=(
                            source.limits.timeout_seconds if source else 10
                        ),
                        max_result_rows=(
                            source.limits.max_result_rows if source else 10_000
                        ),
                        description=(
                            "Review the generated SQL before it is executed. "
                            "The database has not been queried yet."
                        ),
                    )
                )
                continue
            code = arguments.get("code")
            inputs = arguments.get("inputs") or {}
            if (
                name == "execute_analysis_python"
                and isinstance(code, str)
                and isinstance(inputs, dict)
                and inputs
                and result_store is not None
            ):
                try:
                    selected = {
                        alias: result_store.get(
                            key,
                            thread_id,
                            source_id=source.source_id if source else None,
                        )
                        for alias, key in inputs.items()
                    }
                except StoreNotFound as exc:
                    raise RuntimeError(
                        "The Python review references an out-of-scope result."
                    ) from exc
                limits = analysis_limits or PythonExecutionLimits()
                actions.append(
                    ApprovalAction(
                        action_name=name,
                        query=code,
                        arguments=arguments,
                        allowed_decisions=allowed,
                        review_type="python",
                        source_id=next(iter(selected.values())).source_id,
                        timeout_seconds=limits.timeout_seconds,
                        input_datasets={
                            alias: PythonReviewInput(
                                result_id=r.result_id,
                                originating_question=r.originating_question,
                                executed_sql=r.executed_sql,
                                columns=r.columns,
                                sample_rows=r.preview[:10],
                                profile=r.profile,
                                row_count=r.row_count,
                                truncated=r.truncated,
                                parent_result_ids=r.parent_result_ids,
                                upload_provenance=r.upload_provenance,
                            )
                            for alias, r in selected.items()
                        },
                        description=(
                            "Review the complete generated Python before it is "
                            "executed against all named saved datasets."
                        ),
                    )
                )
                continue
            raise RuntimeError(f"The review contains an unsupported action: {name!r}.")
        if actions:
            return ApprovalRequest(interrupt_id=interrupt_id, actions=actions)
    raise RuntimeError("The run interrupted without a reviewable action.")
