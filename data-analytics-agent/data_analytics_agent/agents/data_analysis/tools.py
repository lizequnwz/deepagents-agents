"""Iterative Python tools over explicit, saved datasets."""

from __future__ import annotations
import json
from uuid import uuid4
from langchain.tools import tool, ToolRuntime
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.agents.data_analysis.runner import (
    execute_python,
    AnalysisExecutionError,
)
from data_analytics_agent.agents.data_analysis.schemas import (
    DataAnalysisResult,
    DataAnalysisOutcome,
    PythonExecutionResult,
)


def create_analysis_tools(results, runs, analyses, *, source_id, limits):
    @tool
    def execute_analysis_python(
        inputs: dict[str, str], code: str, runtime: ToolRuntime
    ) -> dict:
        """Execute a Python step with named pandas DataFrames in datasets.

        Set analysis_outputs to compact text/scalars/tables/figures and
        output_datasets to named DataFrames to save for later steps. Each call
        is a fresh process; explicitly load all needed saved inputs.
        Example: inputs={"sales": "saved-result-id"}, code="df = datasets['sales'];
        analysis_outputs = {'rows': len(df)}". There are no automatic variables
        named sales, source, data, or df: use datasets['sales'] explicitly.
        """
        context = _runtime_context(runtime)
        call_id = runtime.tool_call_id
        if committed := runs.storage.committed(context.run_id, call_id):
            return json.loads(committed)
        if reason := runs.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason, "needs_synthesis": True}
        if not inputs:
            return {"ok": False, "error": "Provide at least one named dataset."}
        try:
            selected = {
                name: results.get(key, context.thread_id, source_id=source_id)
                for name, key in inputs.items()
            }
        except KeyError as exc:
            return {
                "ok": False,
                "error": f"Unknown dataset reference {exc}. Use list_conversation_results to recover its exact ID.",
            }
        if any(item.kind == "presentation" for item in selected.values()):
            return {
                "ok": False,
                "error": "Chart presentation is for display. Load its complete parent dataset for analysis.",
            }
        if any(item.truncated for item in selected.values()):
            return {
                "ok": False,
                "error": "An input is incomplete. Request a complete suitable dataset through the coordinator.",
                "needs_sql_reshape": True,
            }
        attempt = runs.reserve_python_execution_attempt(context.run_id)
        runs.set_phase(context.run_id, "analyzing")
        with runs.worker(context.run_id):
            try:
                execution = execute_python(
                    datasets={
                        name: item.parquet_path for name, item in selected.items()
                    },
                    inputs=inputs,
                    code=code,
                    artifact_dir=results.storage.artifacts,
                    result_store=results,
                    thread_id=context.thread_id,
                    source_id=source_id,
                    limits=limits,
                    attempt=attempt,
                    cancel=runs.cancel_event(context.run_id),
                )
            except InterruptedError:
                runs.record_python_execution(
                    context.run_id,
                    PythonExecutionResult(
                        execution_id=str(uuid4()),
                        inputs=inputs,
                        executed_python=code,
                        attempt=attempt,
                        error="Execution interrupted before output commit.",
                    ),
                )
                raise
            except AnalysisExecutionError as exc:
                execution = PythonExecutionResult(
                    execution_id=str(uuid4()),
                    inputs=inputs,
                    executed_python=code,
                    attempt=attempt,
                    error=str(exc),
                    stdout=exc.stdout,
                    stderr=exc.stderr,
                    warnings=[exc.traceback] if exc.traceback else [],
                )
        runs.record_python_execution(context.run_id, execution)
        response = execution.model_facing()
        runs.storage.commit(context.run_id, call_id, json.dumps(response))
        return response

    @tool
    def finish_analysis(
        outcome: DataAnalysisOutcome,
        answer: str,
        input_result_ids: list[str],
        execution_ids: list[str],
        runtime: ToolRuntime,
        method: str = "",
        assumptions: list[str] | None = None,
        interpretation: str = "",
        warnings: list[str] | None = None,
        requested_data: str = "",
    ) -> dict:
        """Finish this analytical assignment, or request more SQL data with a complete brief.

        Preserve execution IDs from every material step. You may be assigned
        again after the coordinator retrieves more data. Do not repeat code or
        output payloads: the application attaches the saved executions.
        """
        context = _runtime_context(runtime)
        if committed := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(committed)
        try:
            for key in input_result_ids:
                results.get(key, context.thread_id, source_id=source_id)
        except KeyError as exc:
            return {
                "ok": False,
                "error": f"Unknown input dataset {exc}. Correct the reference and retry finish_analysis.",
            }
        available = {
            item.execution_id: item
            for saved in analyses.list_for_conversation(
                context.thread_id, source_id=source_id
            )
            for item in saved.analysis.executions
        }
        available.update(
            {
                item.execution_id: item
                for item in runs.get_python_execution(context.run_id)
            }
        )
        missing = [key for key in execution_ids if key not in available]
        if missing:
            return {
                "ok": False,
                "error": "Unknown execution IDs; copy exact IDs and retry finish_analysis.",
                "unknown_execution_ids": missing,
                "available_executions": [
                    {
                        "execution_id": item.execution_id,
                        "error": item.error,
                        "output_datasets": item.output_datasets,
                    }
                    for item in available.values()
                ],
            }
        executions = [available[key] for key in execution_ids]
        if outcome == DataAnalysisOutcome.ANALYSIS_COMPLETED and not any(
            item.error is None for item in executions
        ):
            return {
                "ok": False,
                "error": "Completed analysis requires a successful execution. Continue analysis or report a partial outcome.",
            }
        result = DataAnalysisResult(
            outcome=outcome,
            input_result_ids=input_result_ids,
            executions=executions,
            answer=answer,
            method=method,
            assumptions=assumptions or [],
            interpretation=interpretation,
            warnings=warnings or [],
            requested_data=requested_data,
        )
        saved = analyses.save(
            thread_id=context.thread_id, source_id=source_id, analysis=result
        )
        response = saved.analysis.model_facing()
        runs.storage.commit(context.run_id, runtime.tool_call_id, json.dumps(response))
        return response

    return [execute_analysis_python, finish_analysis]
