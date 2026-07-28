"""Structured statistical-analysis and Python-execution contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatisticalAnalysisOutcome(StrEnum):
    ANALYSIS_COMPLETED = "analysis_completed"
    NEEDS_SQL_RESHAPE = "needs_sql_reshape"
    NEEDS_CLARIFICATION = "needs_clarification"
    CANNOT_ANALYZE = "cannot_analyze"


class StatisticalOutputKind(StrEnum):
    TEXT = "text"
    SCALAR = "scalar"
    TABLE = "table"
    FIGURE = "figure"


class StatisticalOutput(StrictModel):
    """One bounded, named output from reviewed statistical Python."""

    name: str = Field(min_length=1, max_length=200)
    kind: StatisticalOutputKind
    text: str | None = None
    value: str | int | float | bool | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    image_base64: str | None = None
    media_type: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> StatisticalOutput:
        if self.kind is StatisticalOutputKind.TEXT and self.text is None:
            raise ValueError("Text outputs require text.")
        if self.kind is StatisticalOutputKind.TABLE and not self.columns:
            raise ValueError("Table outputs require columns.")
        if self.kind is StatisticalOutputKind.FIGURE:
            if self.image_base64 is not None and self.media_type != "image/png":
                raise ValueError("Figure outputs must use image/png.")
        return self

    def model_facing(self) -> dict[str, Any]:
        """Return compact content suitable for the statistical model."""

        payload = self.model_dump(mode="json", exclude_none=True)
        if self.kind is StatisticalOutputKind.FIGURE:
            payload.pop("image_base64", None)
            payload["rendered"] = True
        return payload


class PythonExecutionResult(StrictModel):
    """Authoritative application-side record of one successful execution."""

    parent_result_id: str
    executed_python: str
    attempt: int = Field(ge=1)
    outputs: list[StatisticalOutput]
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

    def model_facing(self) -> dict[str, Any]:
        """Exclude binary figure payloads while retaining analytical values."""

        return {
            "ok": True,
            "parent_result_id": self.parent_result_id,
            "executed_python": self.executed_python,
            "attempt": self.attempt,
            "outputs": [output.model_facing() for output in self.outputs],
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_ms": self.elapsed_ms,
            "warnings": self.warnings,
        }


class StatisticalAnalysisResult(StrictModel):
    """Terminal result returned by the statistical-analysis specialist."""

    outcome: StatisticalAnalysisOutcome
    analysis_id: str | None = None
    parent_result_id: str
    executed_python: str | None = None
    # The coordinator may emit a sparse copy before RunManager attaches the
    # authoritative specialist result. RunManager guarantees that the final
    # user-facing contract has an answer by backfilling its top-level answer.
    answer: str = ""
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)
    outputs: list[StatisticalOutput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terminal_contract(self) -> StatisticalAnalysisResult:
        if (
            self.outcome is not StatisticalAnalysisOutcome.ANALYSIS_COMPLETED
            and self.outputs
        ):
            raise ValueError(
                "Only analysis_completed may contain statistical outputs."
            )
        return self
