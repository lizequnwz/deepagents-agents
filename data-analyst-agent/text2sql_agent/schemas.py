"""Strict domain and API schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryResult(StrictModel):
    """Small model-facing SQL result; full rows live in ResultStore."""

    result_id: str
    executed_sql: str
    columns: list[str]
    sample_rows: list[dict[str, Any]]
    row_count: int = Field(ge=0, le=10_000)
    truncated: bool
    elapsed_ms: float = Field(ge=0)


class SQLAnalysisResult(StrictModel):
    """Successful SQL analysis backed by a reviewed, saved execution."""

    answer: str
    sql: str
    result_id: str
    row_count: int = Field(ge=0, le=10_000)
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""


class FinalAnswer(StrictModel):
    answer: str
    sql: str | None = None
    result_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""


class SavedResult(StrictModel):
    result_id: str
    thread_id: str
    source_id: str
    executed_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    created_at: datetime


class ResultPage(StrictModel):
    result_id: str
    source_id: str
    executed_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    offset: int
    limit: int


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    APPROVAL_REQUIRED = "approval_required"
    COMPLETED = "completed"
    FAILED = "failed"


class ActivityEvent(StrictModel):
    id: int
    kind: str
    label: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ApprovalRequest(StrictModel):
    action_name: str
    query: str
    allowed_decisions: list[Literal["approve", "edit", "reject"]]
    source_id: str = ""
    dialect: str = "sqlite"
    timeout_seconds: float = Field(default=10, gt=0)
    max_result_rows: int = Field(default=500, ge=1)
    description: str = "Review the generated SQL before it is executed."


class ChatTurn(StrictModel):
    user_message: str
    answer: FinalAnswer
    activities: list[ActivityEvent] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ConversationResponse(StrictModel):
    thread_id: str
    source_id: str
    turns: list[ChatTurn]
    active_run_id: str | None = None


class CreateConversationRequest(StrictModel):
    source_id: str | None = None


class CreateConversationResponse(StrictModel):
    thread_id: str
    source_id: str


class MessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)


class CreateRunResponse(StrictModel):
    run_id: str
    status: RunStatus


class RunResponse(StrictModel):
    run_id: str
    thread_id: str
    source_id: str
    question: str
    status: RunStatus
    events: list[ActivityEvent]
    next_event_id: int
    approval: ApprovalRequest | None = None
    answer: FinalAnswer | None = None
    error: str | None = None


class Decision(StrictModel):
    action: Literal["approve", "edit", "reject"]
    edited_sql: str | None = None
    feedback: str | None = None


class DecisionRequest(StrictModel):
    decisions: list[Decision] = Field(min_length=1)


class HealthResponse(StrictModel):
    status: Literal["ok", "not_ready"]
    model: str
    default_source_id: str | None = None
    ready_source_count: int = 0
    errors: list[str]


class ExampleQuestionResponse(StrictModel):
    label: str
    question: str


class ExecutionLimitsResponse(StrictModel):
    timeout_seconds: float
    max_result_rows: int
    model_sample_rows: int


class DataSourceSummary(StrictModel):
    source_id: str
    name: str
    description: str
    backend_type: str
    dialect: str
    ready: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    examples: list[ExampleQuestionResponse] = Field(default_factory=list)
    limits: ExecutionLimitsResponse


class DataSourcesResponse(StrictModel):
    default_source_id: str
    sources: list[DataSourceSummary]
