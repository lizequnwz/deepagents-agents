"""Iterative Python tools over explicit, saved datasets."""

from __future__ import annotations
import json
from typing import Literal
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
from data_analytics_agent.forecasting import (
    ForecastEvaluationRequest,
    evaluate_forecast,
)


def create_analysis_tools(results, runs, analyses, *, source_id, limits):
    @tool
    def execute_analysis_python(
        inputs: dict[str, str],
        code: str,
        analysis_kind: Literal["general", "forecast"],
        runtime: ToolRuntime,
    ) -> dict:
        """Execute a Python step with named pandas DataFrames in datasets.

        Declare analysis_kind='forecast' before forecasting, including its preparation.
        A declared forecast cannot complete without validated saved evaluation.
        General exploration/statistics/prediction use 'general'.
        Set analysis_outputs to compact text/scalars/tables/figures and
        output_datasets to named DataFrames to save for later steps. Each call
        is a fresh process; explicitly load all needed saved inputs. Return at most
        10 named outputs; combine related scalar diagnostics in a small table.
        Save full rows in output_datasets, not strings, stdout or analysis_outputs.
        For labeled Series (including statsmodels parameters), use .iloc for
        positional access. Recompute and save flags whenever a screening rule changes.
        Example: inputs={"sales": "saved-result-id"}, code="df = datasets['sales'];
        analysis_outputs = {'rows': len(df)}". There are no automatic variables
        named sales, source, data, or df: use datasets['sales'] explicitly.
        Reusable DataFrame procedures can be imported from
        data_analytics_agent.analysis.exploration, preparation, diagnostics,
        customer, statistical, prediction, time_series and scenarios. Their exact
        sources are captured with execution and portable replay. Load the analysis
        skill's practical-workflows reference for signatures and saved outputs.
        """
        context = _runtime_context(runtime)
        assignment_id = runtime.state["assignment_id"]
        call_id = f"{assignment_id}:{runtime.tool_call_id}"
        if committed := runs.storage.committed(context.run_id, call_id):
            return json.loads(committed)
        if reason := runs.analysis_stop_reason(context.run_id):
            return {"ok": False, "error": reason, "needs_synthesis": True}
        if analysis_kind not in {"general", "forecast"}:
            return {
                "ok": False,
                "error": "Declare analysis_kind as general or forecast.",
            }
        runs.declare_analysis_kind(context.run_id, assignment_id, analysis_kind)
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
                        assignment_id=assignment_id,
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
        execution = execution.model_copy(update={"assignment_id": assignment_id})
        runs.record_python_execution(context.run_id, execution)
        response = execution.model_facing()
        runs.storage.commit(context.run_id, call_id, json.dumps(response))
        return response

    @tool
    def finish_analysis(
        outcome: DataAnalysisOutcome,
        answer: str,
        final_outputs: dict[str, list[str]],
        final_result_ids: list[str],
        runtime: ToolRuntime,
        method: str = "",
        assumptions: list[str] | None = None,
        warnings: list[str] | None = None,
        requested_data: str = "",
        forecast_evaluation: ForecastEvaluationRequest | None = None,
    ) -> dict:
        """Finish this analytical assignment, or request more SQL data with a complete brief.

        Select authoritative final_outputs by execution_id and output name, and
        final_result_ids from this assignment's saved output_datasets. Supply empty
        selections for unsupported partial outcomes. Earlier executions remain
        inspectable provenance, but their superseded diagnostics are not findings.
        You may be assigned again after the coordinator retrieves more data.
        Supply interpretation, not artifact IDs or copied code. Derive counts and
        flagged observations from the final saved output, never from mental counting.
        Before finishing, verify the saved flag column matches your final method;
        a degenerate-scale fallback requires recomputing and saving that column.
        Keep declared units and unknown completeness consistent in ALL outputs.
        For a forecast, save actuals, holdout predictions, baseline and future
        predictions as a named dataset and provide forecast_evaluation. Its scores
        are recomputed by application code; both training and holdout must precede
        the future horizon. Declare preparation and interval meaning explicitly.
        """
        context = _runtime_context(runtime)
        assignment_id = runtime.state["assignment_id"]
        call_id = f"{assignment_id}:{runtime.tool_call_id}"
        if committed := runs.storage.committed(context.run_id, call_id):
            return json.loads(committed)
        executions = [
            item
            for item in runs.get_python_execution(context.run_id)
            if item.assignment_id == assignment_id
        ]
        input_result_ids = list(
            dict.fromkeys(
                key for execution in executions for key in execution.inputs.values()
            )
        )
        if outcome == DataAnalysisOutcome.ANALYSIS_COMPLETED and not any(
            item.error is None for item in executions
        ):
            return {
                "ok": False,
                "error": "Completed analysis requires a successful execution. Continue analysis or report a partial outcome.",
            }
        successful = {
            execution.execution_id: execution
            for execution in executions
            if execution.error is None
        }
        available_outputs = {
            key
            for execution in successful.values()
            for key in execution.output_datasets.values()
        }
        for execution_id, names in final_outputs.items():
            execution = successful.get(execution_id)
            if (
                execution is None
                or not names
                or len(names) != len(set(names))
                or set(names) - {output.name for output in execution.outputs}
            ):
                return {
                    "ok": False,
                    "error": "Select exact output names from successful executions in this assignment.",
                }
        if (
            len(final_result_ids) != len(set(final_result_ids))
            or set(final_result_ids) - available_outputs
        ):
            return {
                "ok": False,
                "error": "Select final_result_ids from this assignment's successful output_datasets.",
            }
        if outcome == DataAnalysisOutcome.ANALYSIS_COMPLETED and not (
            final_outputs or final_result_ids
        ):
            return {
                "ok": False,
                "error": "Completed analysis requires selected final outputs or saved final datasets.",
            }
        kind = runs.assignment(context.run_id, assignment_id).analysis_kind or "general"
        if (
            kind == "forecast"
            and outcome == DataAnalysisOutcome.ANALYSIS_COMPLETED
            and forecast_evaluation is None
        ):
            return {
                "ok": False,
                "error": "A declared forecast requires saved predictions and forecast_evaluation; otherwise finish partial with the limitation.",
            }
        evaluation = None
        if forecast_evaluation:
            if forecast_evaluation.predictions_result_id not in final_result_ids:
                return {
                    "ok": False,
                    "error": "Select this assignment's complete prediction table in final_result_ids before evaluating it.",
                }
            try:
                evaluation = evaluate_forecast(
                    forecast_evaluation,
                    results=results,
                    thread_id=context.thread_id,
                    source_id=source_id,
                )
            except (ValueError, TypeError, KeyError) as exc:
                return {"ok": False, "error": str(exc)}
            kind = "forecast"
            final_result_ids = [*final_result_ids, evaluation.scores_result_id]
        result = DataAnalysisResult(
            outcome=outcome,
            analysis_kind=kind,
            final_outputs=final_outputs,
            final_result_ids=final_result_ids,
            input_result_ids=input_result_ids,
            executions=executions,
            answer=answer,
            method=method,
            assumptions=assumptions or [],
            warnings=warnings or [],
            requested_data=requested_data,
            forecast_evaluation=evaluation,
        )
        produced = {
            key
            for execution in executions
            for key in execution.output_datasets.values()
        }
        result.input_result_ids = list(
            dict.fromkeys(
                key
                for execution in result.selected_executions()
                for key in execution.inputs.values()
                if key not in produced
            )
        )
        saved = analyses.save(
            thread_id=context.thread_id, source_id=source_id, analysis=result
        )
        response = saved.analysis.model_facing()
        runs.finish_assignment(
            context.run_id,
            assignment_id,
            response,
            runtime.state.get("correction_ids", []),
        )
        runs.storage.commit(context.run_id, call_id, json.dumps(response))
        return response

    execute_analysis_python.description += (
        f" Configured limits: {limits.max_output_items} outputs, "
        f"{min(10, limits.max_output_rows)} model-visible table rows, "
        f"{limits.max_output_columns} columns. Complete tables belong in output_datasets."
    )
    return [execute_analysis_python, finish_analysis]
