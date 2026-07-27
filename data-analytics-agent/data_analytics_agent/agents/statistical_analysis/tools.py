"""Source- and conversation-scoped statistical-analysis tools."""

from __future__ import annotations

from typing import Any

import pandas as pd
from langchain.tools import ToolRuntime, tool

from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
    StatisticalExecutionError,
    execute_reviewed_python,
)
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.stores import ResultStore, RunStore, StoreNotFound


def _get_result(
    result_store: ResultStore,
    result_id: str,
    runtime: ToolRuntime,
    *,
    source_id: str,
):
    context = _runtime_context(runtime)
    try:
        return result_store.get(
            result_id,
            context.thread_id,
            source_id=source_id,
        )
    except StoreNotFound as exc:
        raise ValueError(
            "That result does not exist in this data-source conversation."
        ) from exc


def create_inspect_result_for_statistics_tool(
    result_store: ResultStore,
    *,
    source_id: str,
    sample_rows: int,
):
    @tool
    def inspect_result_for_statistics(
        result_id: str,
        runtime: ToolRuntime,
    ) -> dict[str, Any]:
        """Inspect provenance, profile, and a bounded sample before analysis."""

        try:
            result = _get_result(
                result_store,
                result_id,
                runtime,
                source_id=source_id,
            )
        except ValueError as exc:
            return {
                "ok": False,
                "code": "result_not_found",
                "repairable": False,
                "result_id": result_id,
                "error": str(exc),
            }
        return {
            "ok": True,
            "result_id": result.result_id,
            "originating_question": result.originating_question,
            "executed_sql": result.executed_sql,
            "columns": result.columns,
            "profile": result.profile.model_dump(mode="json"),
            "row_count": result.row_count,
            "sample_rows": result.rows[:sample_rows],
            "truncated": result.truncated,
        }

    return inspect_result_for_statistics


def create_execute_statistical_python_tool(
    result_store: ResultStore,
    run_store: RunStore,
    *,
    source_id: str,
    limits: PythonExecutionLimits,
):
    @tool
    def execute_statistical_python(
        result_id: str,
        code: str,
        runtime: ToolRuntime,
    ) -> dict[str, Any]:
        """Execute exact human-reviewed Python against ``df`` from result_id.

        The runtime preloads the complete scoped saved result as pandas
        ``df`` and also provides ``pd`` and ``np``. The reviewed code must set
        ``analysis_outputs`` to a named dictionary of compact values, tables,
        or matplotlib figures. The DataFrame itself is never returned to the
        model.
        """

        context = _runtime_context(runtime)
        result = _get_result(
            result_store,
            result_id,
            runtime,
            source_id=source_id,
        )
        if result.truncated:
            return {
                "ok": False,
                "code": "truncated_dataset",
                "repairable": False,
                "error": (
                    "This saved result is truncated. Return needs_sql_reshape; "
                    "do not run inferential analysis over a stored prefix."
                ),
            }
        try:
            attempt = run_store.reserve_statistical_execution_attempt(
                context.run_id,
                maximum=limits.max_execution_attempts,
            )
        except RuntimeError as exc:
            return {
                "ok": False,
                "code": "execution_attempts_exhausted",
                "repairable": False,
                "error": str(exc),
            }
        dataframe = pd.DataFrame(result.rows, columns=result.columns)
        try:
            execution = execute_reviewed_python(
                dataframe=dataframe,
                code=code,
                parent_result_id=result.result_id,
                attempt=attempt,
                limits=limits,
            )
        except StatisticalExecutionError as exc:
            remaining = limits.max_execution_attempts - attempt
            return {
                "ok": False,
                "code": exc.code,
                "attempt": attempt,
                "maximum_attempts": limits.max_execution_attempts,
                "remaining_attempts": remaining,
                "repairable": exc.repairable and remaining > 0,
                "error": str(exc),
                "traceback": exc.traceback,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
            }
        run_store.record_statistical_execution(context.run_id, execution)
        return execution.model_facing()

    return execute_statistical_python
