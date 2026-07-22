"""Thread-safe, process-local stores for the POC."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from data_analytics_agent.profiling import profile_result
from data_analytics_agent.schemas import (
    AgentStateSnapshot,
    ActivityEvent,
    ActivityTool,
    ApprovalRequest,
    ChatTurn,
    ConversationResponse,
    FinalAnswer,
    ExecutionBudgetDiagnostics,
    ResultPage,
    RunResponse,
    RunStatus,
    SavedResult,
)


class StoreNotFound(KeyError):
    pass


class ResultStore:
    """Stores capped SQL artifacts outside the model/checkpoint context."""

    def __init__(self) -> None:
        self._items: dict[str, SavedResult] = {}
        self._lock = RLock()

    def save(
        self,
        *,
        thread_id: str,
        source_id: str,
        executed_sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        truncated: bool,
        elapsed_ms: float,
        originating_question: str = "",
    ) -> SavedResult:
        clean_question = " ".join(originating_question.split())
        result = SavedResult(
            result_id=str(uuid4()),
            thread_id=thread_id,
            source_id=source_id,
            executed_sql=executed_sql,
            originating_question=clean_question,
            short_label=(
                clean_question[:77] + "…"
                if len(clean_question) > 78
                else clean_question or "SQL result"
            ),
            columns=columns,
            rows=rows,
            profile=profile_result(columns, rows),
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._items[result.result_id] = result
        return result

    def list_for_conversation(
        self,
        thread_id: str,
        *,
        source_id: str,
    ) -> list[SavedResult]:
        """List scoped artifacts in creation order without exposing rows."""

        with self._lock:
            results = [
                result
                for result in self._items.values()
                if result.thread_id == thread_id
                and result.source_id == source_id
            ]
        return sorted(results, key=lambda result: result.created_at)

    def get(
        self,
        result_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
    ) -> SavedResult:
        with self._lock:
            result = self._items.get(result_id)
        if (
            result is None
            or result.thread_id != thread_id
            or (source_id is not None and result.source_id != source_id)
        ):
            raise StoreNotFound(result_id)
        return result

    def get_unscoped(self, result_id: str) -> SavedResult:
        """Fetch by opaque ID for the local single-user HTTP result endpoint."""

        with self._lock:
            result = self._items.get(result_id)
        if result is None:
            raise StoreNotFound(result_id)
        return result

    def page(
        self,
        result_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> ResultPage:
        result = self.get(result_id, thread_id, source_id=source_id)
        bounded_limit = min(max(limit, 1), 10_000)
        bounded_offset = max(offset, 0)
        return ResultPage(
            result_id=result.result_id,
            source_id=result.source_id,
            executed_sql=result.executed_sql,
            columns=result.columns,
            rows=result.rows[bounded_offset : bounded_offset + bounded_limit],
            profile=result.profile,
            row_count=result.row_count,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            offset=bounded_offset,
            limit=bounded_limit,
        )

    def page_unscoped(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> ResultPage:
        result = self.get_unscoped(result_id)
        return self.page(
            result_id,
            result.thread_id,
            offset=offset,
            limit=limit,
        )


@dataclass
class _Conversation:
    thread_id: str
    source_id: str
    turns: list[ChatTurn] = field(default_factory=list)
    active_run_id: str | None = None


class ConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, _Conversation] = {}
        self._lock = RLock()

    def create(self, source_id: str) -> str:
        thread_id = str(uuid4())
        with self._lock:
            self._items[thread_id] = _Conversation(
                thread_id=thread_id,
                source_id=source_id,
            )
        return thread_id

    def exists(self, thread_id: str) -> bool:
        with self._lock:
            return thread_id in self._items

    def get(self, thread_id: str) -> ConversationResponse:
        with self._lock:
            item = self._items.get(thread_id)
            if item is None:
                raise StoreNotFound(thread_id)
            return ConversationResponse(
                thread_id=item.thread_id,
                source_id=item.source_id,
                turns=list(item.turns),
                active_run_id=item.active_run_id,
            )

    def begin_run(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is None:
                raise StoreNotFound(thread_id)
            if item.active_run_id is not None:
                raise RuntimeError("A run is already active for this conversation.")
            item.active_run_id = run_id

    def complete_run(self, thread_id: str, run_id: str, turn: ChatTurn) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is None:
                raise StoreNotFound(thread_id)
            if item.active_run_id != run_id:
                raise RuntimeError("Run does not own the conversation.")
            item.turns.append(turn)
            item.active_run_id = None

    def fail_run(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is not None and item.active_run_id == run_id:
                item.active_run_id = None


@dataclass
class _Run:
    run_id: str
    thread_id: str
    source_id: str
    question: str
    status: RunStatus = RunStatus.QUEUED
    events: list[ActivityEvent] = field(default_factory=list)
    debug_states: dict[str, AgentStateSnapshot] = field(default_factory=dict)
    approval: ApprovalRequest | None = None
    answer: FinalAnswer | None = None
    error: str | None = None
    diagnostics: ExecutionBudgetDiagnostics | None = None


class RunStore:
    def __init__(self) -> None:
        self._items: dict[str, _Run] = {}
        self._lock = RLock()

    def create(self, thread_id: str, source_id: str, question: str) -> str:
        run_id = str(uuid4())
        with self._lock:
            self._items[run_id] = _Run(
                run_id=run_id,
                thread_id=thread_id,
                source_id=source_id,
                question=question,
            )
        return run_id

    def _get_mutable(self, run_id: str) -> _Run:
        item = self._items.get(run_id)
        if item is None:
            raise StoreNotFound(run_id)
        return item

    def get(self, run_id: str, *, after_event_id: int = 0) -> RunResponse:
        with self._lock:
            item = self._get_mutable(run_id)
            events = [event for event in item.events if event.id > after_event_id]
            return RunResponse(
                run_id=item.run_id,
                thread_id=item.thread_id,
                source_id=item.source_id,
                question=item.question,
                status=item.status,
                events=events,
                next_event_id=len(item.events),
                debug_states=list(item.debug_states.values()),
                approval=item.approval,
                answer=item.answer,
                error=item.error,
                diagnostics=item.diagnostics,
            )

    def set_status(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            self._get_mutable(run_id).status = status

    def add_event(
        self,
        run_id: str,
        kind: str,
        label: str,
        *,
        phase: str = "info",
        agent: str | None = None,
        tool: ActivityTool | None = None,
    ) -> ActivityEvent:
        with self._lock:
            item = self._get_mutable(run_id)
            event = ActivityEvent(
                id=len(item.events) + 1,
                kind=kind,
                label=label,
                phase=phase,
                agent=agent,
                tool=tool,
            )
            item.events.append(event)
            return event

    def set_debug_state(
        self,
        run_id: str,
        snapshot: AgentStateSnapshot,
    ) -> None:
        """Replace the latest debug snapshot for one recognized agent."""

        with self._lock:
            self._get_mutable(run_id).debug_states[snapshot.agent] = snapshot

    def require_approval(
        self,
        run_id: str,
        approval: ApprovalRequest,
    ) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            item.status = RunStatus.APPROVAL_REQUIRED
            item.approval = approval

    def resume(self, run_id: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            item.status = RunStatus.RUNNING
            item.approval = None
            item.error = None

    def claim_approval(
        self,
        run_id: str,
        expected: ApprovalRequest,
    ) -> None:
        """Atomically claim one pending review before applying its decision."""

        with self._lock:
            item = self._get_mutable(run_id)
            if (
                item.status != RunStatus.APPROVAL_REQUIRED
                or item.approval != expected
            ):
                raise RuntimeError(
                    "This run is no longer awaiting that decision."
                )
            item.status = RunStatus.RUNNING
            item.approval = None
            item.error = None

    def complete(self, run_id: str, answer: FinalAnswer) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            item.status = RunStatus.COMPLETED
            item.answer = answer
            item.approval = None

    def fail(
        self,
        run_id: str,
        error: str,
        *,
        diagnostics: ExecutionBudgetDiagnostics | None = None,
    ) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            item.status = RunStatus.FAILED
            item.error = error
            item.diagnostics = diagnostics
            item.approval = None
