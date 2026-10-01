"""Typed, reusable Python execution and analytical findings."""

from __future__ import annotations
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


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
        result["stdout"] = "\n".join(self.stdout.splitlines()[:10])[:2000]
        result["ok"] = self.error is None
        result["outputs"] = [output.model_facing() for output in self.outputs]
        return result


class DataAnalysisResult(StrictModel):
    analysis_id: str | None = None
    outcome: DataAnalysisOutcome
    input_result_ids: list[str]
    executions: list[PythonExecutionResult] = Field(default_factory=list)
    answer: str
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requested_data: str = ""

    def model_facing(self):
        """Compact synthesis view; exact code and logs remain in saved executions."""
        result = self.model_dump(mode="json", exclude={"executions"}, exclude_none=True)
        result["executions"] = [
            {
                "execution_id": execution.execution_id,
                "inputs": execution.inputs,
                "output_datasets": execution.output_datasets,
                "error": execution.error,
                "warnings": execution.warnings,
                "outputs": [output.model_facing() for output in execution.outputs],
            }
            for execution in self.executions
        ]
        return result
