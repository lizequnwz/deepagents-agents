"""Process-local conversation, run, and event state.

Restart loss is intentional. Durable advisor records live in AdvisorRepository.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from typing import Any

from general_agent.schemas import (
    Artifact,
    AgentUsage,
    Attachment,
    Conversation,
    ConversationSummary,
    Run,
    RunDiagnostics,
    RunEvent,
    RunStatus,
    Turn,
    TokenUsage,
    utc_now,
)
from general_agent.workspace import validate_corp_id


class ActiveRunError(RuntimeError):
    """Raised when one conversation already has an active run."""


class RuntimeStore:
    """Thread-safe in-memory runtime state scoped by corporation."""

    def __init__(self, default_corp_id: str = "A123456") -> None:
        self.default_corp_id = validate_corp_id(default_corp_id)
        self._conversations: dict[tuple[str, str], Conversation] = {}
        self._runs: dict[tuple[str, str], Run] = {}
        self._turns: dict[tuple[str, str], Turn] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def _corp(self, corp_id: str | None) -> str:
        return validate_corp_id(corp_id or self.default_corp_id)

    def create_conversation(
        self, title: str | None = None, *, corp_id: str | None = None
    ) -> ConversationSummary:
        corp = self._corp(corp_id)
        now = utc_now()
        conversation = Conversation(
            conversation_id=uuid.uuid4().hex,
            title=(title or "New chat").strip()[:120] or "New chat",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conversations[(corp, conversation.conversation_id)] = conversation
        return ConversationSummary.model_validate(conversation.model_dump())

    def list_conversations(self, corp_id: str | None = None) -> list[ConversationSummary]:
        corp = self._corp(corp_id)
        with self._lock:
            values = [
                value for (owner, _), value in self._conversations.items() if owner == corp
            ]
            values.sort(key=lambda item: item.updated_at, reverse=True)
            return [ConversationSummary.model_validate(item.model_dump()) for item in values]

    def get_conversation(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> Conversation:
        corp = self._corp(corp_id)
        with self._lock:
            value = self._conversations.get((corp, conversation_id))
            if value is None:
                raise KeyError(conversation_id)
            return value.model_copy(deep=True)

    def rename_conversation(
        self, conversation_id: str, title: str, *, corp_id: str | None = None
    ) -> None:
        corp = self._corp(corp_id)
        safe = title.strip()[:120]
        if not safe:
            raise ValueError("Conversation title cannot be empty.")
        with self._lock:
            conversation = self._require_conversation(corp, conversation_id)
            conversation.title = safe
            conversation.updated_at = utc_now()

    def delete_conversation(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> list[str]:
        corp = self._corp(corp_id)
        with self._lock:
            conversation = self._require_conversation(corp, conversation_id)
            if conversation.active_run_id:
                raise ActiveRunError("Stop the active run before deleting its conversation.")
            run_ids = [turn.run_id for turn in conversation.turns]
            for run_id in run_ids:
                self._runs.pop((corp, run_id), None)
                self._turns.pop((corp, run_id), None)
            del self._conversations[(corp, conversation_id)]
            return run_ids

    def create_run(
        self, conversation_id: str, question: str, *, corp_id: str | None = None
    ) -> tuple[str, str]:
        corp = self._corp(corp_id)
        now = utc_now()
        run_id, turn_id = uuid.uuid4().hex, uuid.uuid4().hex
        with self._lock:
            conversation = self._require_conversation(corp, conversation_id)
            if conversation.active_run_id:
                raise ActiveRunError(
                    "This conversation already has an active run. Stop or finish it first."
                )
            run = Run(
                run_id=run_id,
                conversation_id=conversation_id,
                status=RunStatus.RUNNING,
                question=question,
                started_at=now,
            )
            turn = Turn(
                turn_id=turn_id,
                run_id=run_id,
                user_message=question,
                status=RunStatus.RUNNING,
                created_at=now,
            )
            self._runs[(corp, run_id)] = run
            self._turns[(corp, run_id)] = turn
            conversation.turns.append(turn)
            conversation.active_run_id = run_id
            conversation.updated_at = now
            if conversation.title == "New chat":
                compact = " ".join(question.split())
                conversation.title = compact[:57] + ("…" if len(compact) > 57 else "")
        return run_id, turn_id

    def add_attachment(
        self, run_id: str, attachment: Attachment, *, corp_id: str | None = None
    ) -> None:
        corp = self._corp(corp_id)
        with self._lock:
            self._require_run(corp, run_id)
            self._turns[(corp, run_id)].attachments.append(attachment)

    def add_artifact(
        self, artifact: Artifact, *, corp_id: str | None = None
    ) -> None:
        corp = self._corp(corp_id)
        with self._lock:
            self._require_run(corp, artifact.run_id)
            turn = self._turns[(corp, artifact.run_id)]
            if all(item.artifact_id != artifact.artifact_id for item in turn.artifacts):
                turn.artifacts.append(artifact)

    def add_event(
        self,
        run_id: str,
        kind: str,
        phase: str,
        label: str,
        *,
        data: Mapping[str, Any] | None = None,
        corp_id: str | None = None,
    ) -> RunEvent:
        corp = self._corp(corp_id)
        with self._lock:
            run = self._require_run(corp, run_id)
            event = RunEvent(
                id=run.next_event_id + 1,
                kind=kind,
                phase=phase,
                label=label,
                created_at=utc_now(),
                data=dict(data or {}),
            )
            run.next_event_id = event.id
            run.events.append(event)
            self._turns[(corp, run_id)].events.append(event)
            return event.model_copy(deep=True)

    def request_stop(self, run_id: str, *, corp_id: str | None = None) -> bool:
        corp = self._corp(corp_id)
        with self._lock:
            run = self._require_run(corp, run_id)
            if run.status != RunStatus.RUNNING:
                return False
            run.status = RunStatus.STOPPING
            self._turns[(corp, run_id)].status = RunStatus.STOPPING
            return True

    def record_model_call(
        self,
        run_id: str,
        usage: Mapping[str, Any] | None,
        *,
        corp_id: str | None = None,
    ) -> None:
        """Accumulate provider-reported usage in process-local diagnostics."""

        corp = self._corp(corp_id)
        with self._lock:
            run = self._require_run(corp, run_id)
            diagnostics = run.diagnostics
            diagnostics.model_calls += 1
            parsed = _token_usage(usage)
            if parsed is None:
                diagnostics.model_calls_missing_usage += 1
            else:
                diagnostics.tokens = _add_tokens(diagnostics.tokens, parsed)
            diagnostics.token_usage_partial = True
            diagnostics.agents = [
                AgentUsage(
                    agent="advisor-match-graph",
                    tokens=diagnostics.tokens.model_copy(deep=True),
                    model_calls=diagnostics.model_calls,
                    model_calls_missing_usage=diagnostics.model_calls_missing_usage,
                )
            ]
            self._turns[(corp, run_id)].diagnostics = diagnostics.model_copy(deep=True)

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        assistant_text: str = "",
        error: str | None = None,
        corp_id: str | None = None,
    ) -> None:
        corp = self._corp(corp_id)
        now = utc_now()
        with self._lock:
            run = self._require_run(corp, run_id)
            run.status = status
            run.assistant_text = assistant_text
            run.error = error
            run.completed_at = now
            run.diagnostics.elapsed_ms = int((now - run.started_at).total_seconds() * 1000)
            run.diagnostics.token_usage_partial = (
                bool(run.diagnostics.model_calls_missing_usage)
                or status in {RunStatus.STOPPED, RunStatus.FAILED}
            )
            turn = self._turns[(corp, run_id)]
            turn.status = status
            turn.assistant_message = assistant_text
            turn.error = error
            turn.completed_at = now
            turn.diagnostics = run.diagnostics.model_copy(deep=True)
            conversation = self._require_conversation(corp, run.conversation_id)
            if conversation.active_run_id == run_id:
                conversation.active_run_id = None
            conversation.updated_at = now

    def get_run(
        self,
        run_id: str,
        *,
        after_event_id: int = 0,
        corp_id: str | None = None,
    ) -> Run:
        corp = self._corp(corp_id)
        with self._lock:
            run = self._require_run(corp, run_id).model_copy(deep=True)
            run.events = [event for event in run.events if event.id > after_event_id]
            return run

    def completed_history(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> list[dict[str, str]]:
        conversation = self.get_conversation(conversation_id, corp_id=corp_id)
        result: list[dict[str, str]] = []
        for turn in conversation.turns:
            if turn.status == RunStatus.COMPLETED:
                result.extend(
                    [
                        {"role": "user", "content": turn.user_message},
                        {"role": "assistant", "content": turn.assistant_message},
                    ]
                )
        return result

    def _require_conversation(self, corp: str, conversation_id: str) -> Conversation:
        value = self._conversations.get((corp, conversation_id))
        if value is None:
            raise KeyError(conversation_id)
        return value

    def _require_run(self, corp: str, run_id: str) -> Run:
        value = self._runs.get((corp, run_id))
        if value is None:
            raise KeyError(run_id)
        return value


def _token_usage(usage: Mapping[str, Any] | None) -> TokenUsage | None:
    if not usage:
        return None
    values = {
        key: usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    if any(not isinstance(value, int) or value < 0 for value in values.values()):
        return None
    input_details = usage.get("input_token_details")
    output_details = usage.get("output_token_details")
    return TokenUsage(
        input_tokens=int(values["input_tokens"]),
        output_tokens=int(values["output_tokens"]),
        total_tokens=int(values["total_tokens"]),
        cached_input_tokens=_detail(input_details, "cache_read", "cached"),
        reasoning_output_tokens=_detail(output_details, "reasoning"),
    )


def _detail(value: Any, *keys: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
    return None


def _add_tokens(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
        cached_input_tokens=_optional_sum(
            left.cached_input_tokens, right.cached_input_tokens
        ),
        reasoning_output_tokens=_optional_sum(
            left.reasoning_output_tokens, right.reasoning_output_tokens
        ),
    )


def _optional_sum(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)
