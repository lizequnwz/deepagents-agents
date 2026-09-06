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
        if self.image_path:
            result.pop("image_path", None)
            result["rendered"] = True
        return result


class PythonExecutionResult(StrictModel):
    execution_id: str
    inputs: dict[str, str]
    executed_python: str
    attempt: int
    outputs: list[AnalysisOutput] = Field(default_factory=list)
    output_datasets: dict[str, str] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    def model_facing(self):
        result = self.model_dump(mode="json", exclude_none=True)
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
    interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)
    requested_data: str = ""

    def model_facing(self):
        result = self.model_dump(mode="json", exclude_none=True)
        result["executions"] = [
            execution.model_facing() for execution in self.executions
        ]
        return result
