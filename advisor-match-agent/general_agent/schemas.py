"""Stable API and persistence schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class TokenUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)


class AgentUsage(BaseModel):
    agent: str
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    model_calls: int = Field(default=0, ge=0)
    model_calls_missing_usage: int = Field(default=0, ge=0)


class Attachment(BaseModel):
    attachment_id: str
    original_name: str
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: datetime


class Artifact(BaseModel):
    artifact_id: str
    run_id: str
    match_session_id: str | None = None
    revision: int | None = Field(default=None, ge=1)
    relative_path: str
    change_type: Literal["created", "modified", "deleted"]
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: datetime


class RunEvent(BaseModel):
    id: int
    kind: Literal[
        "assistant_delta",
        "plan_updated",
        "tool_started",
        "tool_finished",
        "subagent_started",
        "subagent_finished",
        "usage_updated",
        "artifact_changed",
        "run_status",
    ]
    phase: Literal["started", "updated", "completed", "failed"]
    label: str
    agent: str = "advisor-match-agent"
    created_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class RunDiagnostics(BaseModel):
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    token_usage_partial: bool = False
    model_calls: int = 0
    model_calls_missing_usage: int = 0
    tool_calls: int = 0
    elapsed_ms: int = 0
    agents: list[AgentUsage] = Field(default_factory=list)


class Turn(BaseModel):
    turn_id: str
    run_id: str
    user_message: str
    assistant_message: str = ""
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)
    error: str | None = None


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    active_run_id: str | None = None


class Conversation(ConversationSummary):
    turns: list[Turn] = Field(default_factory=list)
    diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)


class Run(BaseModel):
    run_id: str
    conversation_id: str
    status: RunStatus
    question: str
    assistant_text: str = ""
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    events: list[RunEvent] = Field(default_factory=list)
    next_event_id: int = 0
    diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)
