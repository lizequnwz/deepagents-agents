"""Typed, reusable Python execution and analytical findings."""

from __future__ import annotations
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from data_analytics_agent.forecasting import ForecastEvaluation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataAnalysisOutcome(StrEnum):
    ANALYSIS_COMPLETED = "analysis_completed"
    NEEDS_SQL_RESHAPE = "needs_sql_reshape"
    NEEDS_CLARIFICATION = "needs_clarification"
    CANNOT_ANALYZE = "cannot_analyze"
    PARTIAL = "partial"


class AnalysisOutputKind(StrEnum):
    TEXT = "text"
    SCALAR = "scalar"
    TABLE = "table"
    FIGURE = "figure"


class AnalysisOutput(StrictModel):
    name: str
    kind: AnalysisOutputKind
    text: str | None = None
    value: Any = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    image_path: str | None = None
    media_type: str | None = None

    def model_facing(self):
        result = self.model_dump(mode="json", exclude_none=True)
        if self.text:
            result["text"] = "\n".join(self.text.splitlines()[:10])[:2000]
            if result["text"] != self.text:
                result["text_preview_truncated"] = True
        if self.kind == AnalysisOutputKind.TABLE:
            result["rows"] = self.rows[:10]
            result["stored_output_row_count"] = len(self.rows)
        if self.image_path:
            result.pop("image_path", None)
            result["rendered"] = True
        return result


class PythonExecutionResult(StrictModel):
    assignment_id: str | None = None
    execution_id: str
    inputs: dict[str, str]
    executed_python: str
    attempt: int
    runtime_versions: dict[str, str] = Field(default_factory=dict)
    workflow_sources: dict[str, str] = Field(default_factory=dict)
    outputs: list[AnalysisOutput] = Field(default_factory=list)
    output_datasets: dict[str, str] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    def model_facing(self):
        result = self.model_dump(mode="json", exclude_none=True)
        # Exact stdout/code remain in execution inspection, not repeated in model context.
        result.pop("executed_python", None)
        result.pop("runtime_versions", None)
        result.pop("workflow_sources", None)
        result["stdout"] = "\n".join(self.stdout.splitlines()[:10])[:2000]
        result["ok"] = self.error is None
        result["outputs"] = [output.model_facing() for output in self.outputs]
        return result


class DataAnalysisResult(StrictModel):
    analysis_id: str | None = None
    outcome: DataAnalysisOutcome
    analysis_kind: Literal["general", "forecast"]
    final_outputs: dict[str, list[str]]
    final_result_ids: list[str]
    input_result_ids: list[str]
    executions: list[PythonExecutionResult] = Field(default_factory=list)
    answer: str
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requested_data: str = ""
    forecast_evaluation: ForecastEvaluation | None = None

    def selected_executions(self):
        """Final producers and their dependencies, in original execution order."""
        producers = {
            key: execution.execution_id
            for execution in self.executions
            if execution.error is None
            for key in execution.output_datasets.values()
        }
        executions = {
            execution.execution_id: execution for execution in self.executions
        }
        selected = set()

        def include(key):
            if key in selected:
                return
            selected.add(key)
            for source in executions[key].inputs.values():
                if source in producers:
                    include(producers[source])

        for key in self.final_outputs:
            include(key)
        for key in self.final_result_ids:
            if key in producers:
                include(producers[key])
        return [
            execution
            for execution in self.executions
            if execution.execution_id in selected
        ]

    def selected_outputs(self):
        for execution in self.executions:
            selected = self.final_outputs.get(execution.execution_id, [])
            for output in execution.outputs:
                if output.name in selected:
                    yield output

    def model_facing(self):
        """Compact synthesis view; exact code and logs remain in saved executions."""
        result = self.model_dump(mode="json", exclude={"executions"}, exclude_none=True)
        result["execution_count"] = len(self.executions)
        result["failed_execution_count"] = sum(
            execution.error is not None for execution in self.executions
        )
        result["executions"] = [
            {
                "execution_id": execution.execution_id,
                "inputs": execution.inputs,
                "output_datasets": {
                    name: key
                    for name, key in execution.output_datasets.items()
                    if key in self.final_result_ids
                },
                "error": execution.error,
                "warnings": execution.warnings,
                "outputs": [
                    output.model_facing()
                    for output in execution.outputs
                    if output.name in self.final_outputs.get(execution.execution_id, [])
                ],
            }
            for execution in self.selected_executions()
        ]
        return result
