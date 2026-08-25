"""Strict domain and API schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisResult,
)
from data_analytics_agent.agents.visualization.schemas import ChartSpec
from data_analytics_agent.reporting.schemas import ReportReference

API_CONTRACT_VERSION = 7


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhysicalKind(StrEnum):
    EMPTY = "empty"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    TEXT = "text"
    MIXED = "mixed"


class AnalyticalRole(StrEnum):
    CATEGORICAL = "categorical"
    TEMPORAL = "temporal"
    NUMERIC = "numeric"
    DISCRETE_NUMERIC = "discrete_numeric"
    UNKNOWN = "unknown"


class TemporalKind(StrEnum):
    DATE = "date"
    DATETIME = "datetime"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class RoleCandidate(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AnalyticalRole
    confidence: float = Field(ge=0, le=1)


class ColumnProfile(StrictModel):
    """Immutable, deterministic profile of one stored-result column."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    physical_kind: PhysicalKind
    role_candidates: tuple[RoleCandidate, ...]
    temporal_kind: TemporalKind | None = None
    null_count: int = Field(ge=0)
    non_null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    minimum: Any | None = None
    maximum: Any | None = None
    representative_values: tuple[Any, ...] = ()


class ResultProfile(StrictModel):
    """Profile over every row retained by the configured retrieval cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["stored_rows"] = "stored_rows"
    row_count: int = Field(ge=0, le=10_000)
    columns: tuple[ColumnProfile, ...]


class QueryResult(StrictModel):
    """Small model-facing SQL result; full rows live in ResultStore."""

    result_id: str
    executed_sql: str
    columns: list[str]
    sample_rows: list[dict[str, Any]]
    profile: ResultProfile
    row_count: int = Field(ge=0, le=10_000)
    truncated: bool
    elapsed_ms: float = Field(ge=0)


class SQLAnalysisResult(StrictModel):
    """Successful SQL analysis backed by an exact, saved execution."""

    answer: str
    sql: str
    result_id: str
    columns: list[str]
    sample_rows: list[dict[str, Any]]
    profile: ResultProfile
    row_count: int = Field(ge=0, le=10_000)
    truncated: bool
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""


class SQLAnalysisResponse(StrictModel):
    """Provider-facing narrative for a validated SQL result.

    Exact rows, columns, profiles, counts, and truncation state remain in
    ``ResultStore`` and are resolved from ``result_id`` by trusted code.
    """

    answer: str
    sql: str
    result_id: str
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""


class CoordinatorResponse(StrictModel):
    """Small provider-facing response; trusted artifacts are attached later."""

    answer: str
    primary_result_id: str | None = None
    supporting_result_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""


class ResultReference(StrictModel):
    """Application-owned provenance for one saved SQL result."""

    result_id: str
    executed_sql: str
    originating_question: str
    short_label: str


class FinalAnswer(StrictModel):
    answer: str
    primary_result_id: str | None = None
    results: list[ResultReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    interpretation: str = ""
    chart: ChartSpec | None = None
    statistical_analysis: StatisticalAnalysisResult | None = None
    report: ReportReference | None = None


class SavedStatisticalAnalysis(StrictModel):
    analysis_id: str
    thread_id: str
    source_id: str
    analysis: StatisticalAnalysisResult
    created_at: datetime


class SavedResult(StrictModel):
    result_id: str
    thread_id: str
    source_id: str
    executed_sql: str
    originating_question: str
    short_label: str
    columns: list[str]
    rows: list[dict[str, Any]]
    profile: ResultProfile
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
    profile: ResultProfile
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


class TokenUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)


class AgentDiagnostics(StrictModel):
    agent: str
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    model_calls: int = Field(default=0, ge=0)
    model_call_errors: int = Field(default=0, ge=0)
    model_calls_missing_usage: int = Field(default=0, ge=0)
    model_ms: int = Field(default=0, ge=0)
    max_model_call_ms: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_call_errors: int = Field(default=0, ge=0)
    tool_ms: int = Field(default=0, ge=0)


class RunDiagnostics(StrictModel):
    model: str = ""
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    token_usage_partial: bool = False
    model_calls: int = Field(default=0, ge=0)
    model_call_errors: int = Field(default=0, ge=0)
    model_calls_missing_usage: int = Field(default=0, ge=0)
    model_ms: int = Field(default=0, ge=0)
    max_model_call_ms: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_call_errors: int = Field(default=0, ge=0)
    tool_ms: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    active_ms: int = Field(default=0, ge=0)
    approval_wait_ms: int = Field(default=0, ge=0)
    agents: list[AgentDiagnostics] = Field(default_factory=list)


class ConversationDiagnostics(StrictModel):
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    token_usage_partial: bool = False
    model_calls: int = Field(default=0, ge=0)
    model_call_errors: int = Field(default=0, ge=0)
    model_calls_missing_usage: int = Field(default=0, ge=0)
    model_ms: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_call_errors: int = Field(default=0, ge=0)
    tool_ms: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    active_ms: int = Field(default=0, ge=0)
    approval_wait_ms: int = Field(default=0, ge=0)
    run_count: int = Field(default=0, ge=0)
    has_active_run: bool = False


class ToolCallDiagnostic(StrictModel):
    tool_name: str
    input: str | None = None
    output: str | None = None
    error: str | None = None


class ExecutionBudgetDiagnostics(StrictModel):
    code: Literal["execution_budget_exceeded"] = (
        "execution_budget_exceeded"
    )
    agent: str
    budget_type: Literal["model_calls", "tool_calls"]
    limit: int = Field(ge=1)
    attempted_count: int = Field(ge=1)
    run_id: str
    tool_name: str | None = None
    recent_tool_calls: list[ToolCallDiagnostic] = Field(
        default_factory=list
    )


class ActivityTool(StrictModel):
    """User-presentable details for one streamed tool lifecycle."""

    call_id: str | None = None
    name: str
    input: Any | None = None
    output: Any | None = None


class ActivityEvent(StrictModel):
    id: int
    kind: str
    label: str
    phase: Literal["info", "started", "completed", "failed"] = "info"
    agent: str | None = None
    tool: ActivityTool | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AgentStateSnapshot(StrictModel):
    """Bounded, debug-only view of the latest state for one agent."""

    agent: str
    namespace: list[str] = Field(default_factory=list)
    state: dict[str, Any]
    truncated: bool = False
    omitted_items: int = Field(default=0, ge=0)
    omitted_messages: int = Field(default=0, ge=0)
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ApprovalRequest(StrictModel):
    interrupt_id: str = Field(min_length=1)
    action_name: str
    query: str
    allowed_decisions: list[Literal["approve", "edit", "reject"]]
    review_type: Literal["sql", "python"] = "sql"
    source_id: str = ""
    dialect: str = "sqlite"
    timeout_seconds: float = Field(default=10, gt=0)
    max_result_rows: int = Field(default=10_000, ge=1)
    parent_result_id: str | None = None
    originating_question: str = ""
    executed_sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    profile: ResultProfile | None = None
    row_count: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    description: str = "Review the generated SQL before it is executed."


class ChatTurn(StrictModel):
    user_message: str
    answer: FinalAnswer
    activities: list[ActivityEvent] = Field(default_factory=list)
    debug_states: list[AgentStateSnapshot] = Field(default_factory=list)
    diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ConversationResponse(StrictModel):
    thread_id: str
    source_id: str
    turns: list[ChatTurn]
    run_ids: list[str] = Field(default_factory=list)
    active_run_id: str | None = None
    diagnostics: ConversationDiagnostics = Field(
        default_factory=ConversationDiagnostics
    )


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
    debug_states: list[AgentStateSnapshot] = Field(default_factory=list)
    approval: ApprovalRequest | None = None
    answer: FinalAnswer | None = None
    error: str | None = None
    diagnostics: ExecutionBudgetDiagnostics | None = None
    run_diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)


class Decision(StrictModel):
    action: Literal["approve", "edit", "reject"]
    edited_sql: str | None = None
    edited_python: str | None = None
    feedback: str | None = None


class DecisionRequest(StrictModel):
    decisions: list[Decision] = Field(min_length=1)


class HealthResponse(StrictModel):
    status: Literal["ok", "not_ready"]
    model: str
    api_contract_version: int = API_CONTRACT_VERSION
    default_source_id: str | None = None
    ready_source_count: int = 0
    sql_approval_required: bool = False
    python_approval_required: bool = True
    visualization_enabled: bool = False
    statistical_analysis_enabled: bool = False
    reporting_enabled: bool = False
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
