"""Thread-safe durable stores for conversations, runs, and presentation artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from threading import RLock
from typing import Any
from uuid import uuid4

from data_analytics_agent.agents.data_analysis.schemas import (
    PythonExecutionResult,
    DataAnalysisResult,
)
from data_analytics_agent.reporting.schemas import (
    ReportArtifact,
    ReportResponse,
    ReportSpec,
)
from data_analytics_agent.reporting.renderer import REPORT_RENDERER_VERSION
from data_analytics_agent.schemas import (
    ActivityEvent,
    ActivityTool,
    AgentDiagnostics,
    AgentStateSnapshot,
    ApprovalRequest,
    ChatTurn,
    ConversationDiagnostics,
    ConversationResponse,
    ExecutionBudgetDiagnostics,
    FinalAnswer,
    RunDiagnostics,
    RunResponse,
    RunStatus,
    SavedDataAnalysis,
    TokenUsage,
)


from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.datasets import ResultStore as ResultStore
from data_analytics_agent.persistence import LocalStorage, persist_run


class DataAnalysisStore:
    """Retains reusable, source-scoped statistical analysis artifacts."""

    def __init__(self, storage: LocalStorage | None = None) -> None:
        self.storage = storage or LocalStorage()
        self._items = self.storage.load("analyses", SavedDataAnalysis)
        self._lock = RLock()

    def forget_conversations(self, thread_ids: set[str]) -> None:
        """Evict records after durable history deletion."""
        with self._lock:
            keys = [
                key for key, item in self._items.items() if item.thread_id in thread_ids
            ]
            for key in keys:
                del self._items[key]

    def save(
        self,
        *,
        thread_id: str,
        source_id: str,
        analysis: DataAnalysisResult,
    ) -> SavedDataAnalysis:
        analysis_id = str(uuid4())
        authoritative = analysis.model_copy(update={"analysis_id": analysis_id})
        saved = SavedDataAnalysis(
            analysis_id=analysis_id,
            thread_id=thread_id,
            source_id=source_id,
            analysis=authoritative,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._items[analysis_id] = saved
            self.storage.put("analyses", analysis_id, saved)
        return saved

    def get(
        self,
        analysis_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
    ) -> SavedDataAnalysis:
        with self._lock:
            item = self._items.get(analysis_id)
        if (
            item is None
            or item.thread_id != thread_id
            or (source_id is not None and item.source_id != source_id)
        ):
            raise StoreNotFound(analysis_id)
        return item

    def list_for_conversation(
        self,
        thread_id: str,
        *,
        source_id: str,
    ) -> list[SavedDataAnalysis]:
        with self._lock:
            items = [
                item
                for item in self._items.values()
                if item.thread_id == thread_id and item.source_id == source_id
            ]
        return sorted(items, key=lambda item: item.created_at)


class ReportStore:
    """Stores exact rendered HTML outside model and checkpoint context."""

    def __init__(self, storage: LocalStorage | None = None) -> None:
        self.storage = storage or LocalStorage()
        self._items = self.storage.load("reports", ReportArtifact)
        self._lock = RLock()

    def forget_conversations(self, thread_ids: set[str]) -> None:
        """Evict records after durable history deletion."""
        with self._lock:
            keys = [
                key for key, item in self._items.items() if item.thread_id in thread_ids
            ]
            for key in keys:
                del self._items[key]

    def save(
        self,
        *,
        thread_id: str,
        source_id: str,
        spec: ReportSpec,
        html: str,
        input_result_ids: list[str],
        input_analysis_ids: list[str],
    ) -> ReportArtifact:
        previous: ReportArtifact | None = None
        if spec.previous_report_id:
            previous = self.get(
                spec.previous_report_id,
                thread_id,
                source_id=source_id,
            )
        report_id = str(uuid4())
        html_path = self.storage.artifacts / f"{report_id}.html"
        html_path.write_text(html, encoding="utf-8")
        artifact = ReportArtifact(
            report_id=report_id,
            thread_id=thread_id,
            source_id=source_id,
            title=spec.title,
            version=(previous.version + 1 if previous else 1),
            previous_report_id=previous.report_id if previous else None,
            spec=spec,
            html_path=str(html_path),
            html_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
            renderer_version=REPORT_RENDERER_VERSION,
            input_result_ids=list(dict.fromkeys(input_result_ids)),
            input_analysis_ids=list(dict.fromkeys(input_analysis_ids)),
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._items[artifact.report_id] = artifact
            self.storage.put("reports", artifact.report_id, artifact)
        return artifact

    def get(
        self,
        report_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
    ) -> ReportArtifact:
        with self._lock:
            item = self._items.get(report_id)
        if (
            item is None
            or item.thread_id != thread_id
            or (source_id is not None and item.source_id != source_id)
        ):
            raise StoreNotFound(report_id)
        return item

    def get_unscoped(self, report_id: str) -> ReportArtifact:
        with self._lock:
            item = self._items.get(report_id)
        if item is None:
            raise StoreNotFound(report_id)
        return item

    def response_unscoped(self, report_id: str) -> ReportResponse:
        item = self.get_unscoped(report_id)
        return ReportResponse(
            report_id=item.report_id,
            source_id=item.source_id,
            title=item.title,
            version=item.version,
            previous_report_id=item.previous_report_id,
            html=item.html,
            html_sha256=item.html_sha256,
            renderer_version=item.renderer_version,
            input_result_ids=item.input_result_ids,
            input_analysis_ids=item.input_analysis_ids,
            created_at=item.created_at,
        )


@dataclass
class _Conversation:
    thread_id: str
    source_id: str
    turns: list[ChatTurn] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    active_run_id: str | None = None


class ConversationStore:
    def __init__(self, storage: LocalStorage | None = None) -> None:
        self.storage = storage or LocalStorage()
        self._items = self.storage.load("conversations", _Conversation)
        self._lock = RLock()

    def forget_conversations(self, thread_ids: set[str]) -> None:
        """Evict records after durable history deletion."""
        with self._lock:
            keys = [
                key for key, item in self._items.items() if item.thread_id in thread_ids
            ]
            for key in keys:
                del self._items[key]

    def create(self, source_id: str) -> str:
        thread_id = str(uuid4())
        with self._lock:
            self._items[thread_id] = _Conversation(
                thread_id=thread_id,
                source_id=source_id,
            )
        self.storage.put("conversations", thread_id, self._items[thread_id])
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
                run_ids=list(item.run_ids),
                active_run_id=item.active_run_id,
            )

    def begin_run(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is None:
                raise StoreNotFound(thread_id)
            if item.active_run_id is not None:
                raise RuntimeError("A run is already active for this conversation.")
            if run_id not in item.run_ids:
                item.run_ids.append(run_id)
            item.active_run_id = run_id
            self.storage.put("conversations", thread_id, item)

    def complete_run(self, thread_id: str, run_id: str, turn: ChatTurn) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is None:
                raise StoreNotFound(thread_id)
            if item.active_run_id != run_id:
                raise RuntimeError("Run does not own the conversation.")
            item.turns.append(turn)
            item.active_run_id = None
            self.storage.put("conversations", thread_id, item)

    def fail_run(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            item = self._items.get(thread_id)
            if item is not None and item.active_run_id == run_id:
                item.active_run_id = None
                self.storage.put("conversations", thread_id, item)

    def list(self):
        return [self.get(key) for key in reversed(list(self._items))]

    def save_investigation(self, thread_id: str, record: dict):
        self.storage.put("investigations", thread_id, record, dict)

    def investigation(self, thread_id: str):
        return self.storage.load("investigations", dict).get(thread_id, {})


@dataclass
class _TokenTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None

    def add(self, usage: Mapping[str, Any]) -> None:
        self.input_tokens += int(usage["input_tokens"])
        self.output_tokens += int(usage["output_tokens"])
        self.total_tokens += int(usage["total_tokens"])
        input_details = usage.get("input_token_details")
        if isinstance(input_details, Mapping):
            cached = input_details.get("cache_read")
            if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
                self.cached_input_tokens = (self.cached_input_tokens or 0) + cached
        output_details = usage.get("output_token_details")
        if isinstance(output_details, Mapping):
            reasoning = output_details.get("reasoning")
            if (
                isinstance(reasoning, int)
                and not isinstance(reasoning, bool)
                and reasoning >= 0
            ):
                self.reasoning_output_tokens = (
                    self.reasoning_output_tokens or 0
                ) + reasoning

    def schema(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            cached_input_tokens=self.cached_input_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens,
        )


@dataclass
class _AgentMetrics:
    tokens: _TokenTotals = field(default_factory=_TokenTotals)
    model_calls: int = 0
    model_call_errors: int = 0
    model_calls_missing_usage: int = 0
    model_seconds: float = 0.0
    max_model_call_seconds: float = 0.0
    tool_calls: int = 0
    tool_call_errors: int = 0
    tool_seconds: float = 0.0


@dataclass
class _PendingCall:
    agent: str
    started_at: float


@dataclass
class _Run:
    run_id: str
    thread_id: str
    source_id: str
    question: str
    created_at: float
    last_saved_at: float = 0
    model: str = ""
    status: RunStatus = RunStatus.QUEUED
    events: list[ActivityEvent] = field(default_factory=list)
    debug_states: dict[str, AgentStateSnapshot] = field(default_factory=dict)
    approval: ApprovalRequest | None = None
    answer: FinalAnswer | None = None
    error: str | None = None
    diagnostics: ExecutionBudgetDiagnostics | None = None
    python_execution_attempts: int = 0
    python_executions: list[PythonExecutionResult] = field(default_factory=list)
    phase: str = "understanding"
    findings: FinalAnswer | None = None
    report_spec: dict | None = None
    chart_specs: list[dict] = field(default_factory=list)
    report_reference: dict | None = None
    last_review_type: str = "sql"
    terminal_at: float | None = None
    active_started_at: float | None = None
    active_seconds: float = 0.0
    approval_started_at: float | None = None
    approval_seconds: float = 0.0
    agent_metrics: dict[str, _AgentMetrics] = field(default_factory=dict)
    pending_model_calls: dict[str, _PendingCall] = field(default_factory=dict)
    pending_tool_calls: dict[str, _PendingCall] = field(default_factory=dict)


def _rounded_ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def _valid_usage(usage: Mapping[str, Any] | None) -> bool:
    if usage is None:
        return False
    for field_name in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    return True


def _sum_tokens(values: list[TokenUsage]) -> TokenUsage:
    cached_values = [
        value.cached_input_tokens
        for value in values
        if value.cached_input_tokens is not None
    ]
    reasoning_values = [
        value.reasoning_output_tokens
        for value in values
        if value.reasoning_output_tokens is not None
    ]
    return TokenUsage(
        input_tokens=sum(value.input_tokens for value in values),
        output_tokens=sum(value.output_tokens for value in values),
        total_tokens=sum(value.total_tokens for value in values),
        cached_input_tokens=(sum(cached_values) if cached_values else None),
        reasoning_output_tokens=(sum(reasoning_values) if reasoning_values else None),
    )


class RunStore:
    def __init__(
        self,
        storage: LocalStorage | None = None,
        *,
        clock: Callable[[], float] = __import__("time").time,
    ) -> None:
        self.storage = storage or LocalStorage()
        self._items = self.storage.load("runs", _Run)
        self._lock = RLock()
        self._clock = clock

    def forget_conversations(self, thread_ids: set[str]) -> None:
        """Evict records after durable history deletion."""
        with self._lock:
            keys = [
                key for key, item in self._items.items() if item.thread_id in thread_ids
            ]
            for key in keys:
                del self._items[key]
                for name in ("_cancel_events", "_workers"):
                    getattr(self, name, {}).pop(key, None)
            for key in thread_ids:
                getattr(self, "_source_locks", {}).pop(key, None)

    @persist_run
    def create(
        self,
        thread_id: str,
        source_id: str,
        question: str,
        *,
        model: str = "",
    ) -> str:
        run_id = str(uuid4())
        with self._lock:
            self._items[run_id] = _Run(
                run_id=run_id,
                thread_id=thread_id,
                source_id=source_id,
                question=question,
                created_at=self._clock(),
                model=model,
            )
        return run_id

    def _get_mutable(self, run_id: str) -> _Run:
        item = self._items.get(run_id)
        if item is None:
            raise StoreNotFound(run_id)
        return item

    def _agent(self, item: _Run, agent: str) -> _AgentMetrics:
        return item.agent_metrics.setdefault(agent or "unknown", _AgentMetrics())

    def _stop_active(self, item: _Run, now: float) -> None:
        if item.active_started_at is not None:
            item.active_seconds += max(0.0, now - item.active_started_at)
            item.active_started_at = None

    def _run_diagnostics(self, item: _Run, now: float) -> RunDiagnostics:
        active_seconds = item.active_seconds
        if item.active_started_at is not None:
            active_seconds += max(0.0, now - item.active_started_at)
        approval_seconds = item.approval_seconds
        if item.approval_started_at is not None:
            approval_seconds += max(0.0, now - item.approval_started_at)
        ended_at = item.terminal_at if item.terminal_at is not None else now

        preferred_order = {
            "coordinator": 0,
            "text-to-sql": 1,
            "data-analysis": 2,
            "data-visualization": 3,
            "unknown": 99,
        }
        agents = [
            AgentDiagnostics(
                agent=agent,
                tokens=metrics.tokens.schema(),
                model_calls=metrics.model_calls,
                model_call_errors=metrics.model_call_errors,
                model_calls_missing_usage=metrics.model_calls_missing_usage,
                model_ms=_rounded_ms(metrics.model_seconds),
                max_model_call_ms=_rounded_ms(metrics.max_model_call_seconds),
                tool_calls=metrics.tool_calls,
                tool_call_errors=metrics.tool_call_errors,
                tool_ms=_rounded_ms(metrics.tool_seconds),
            )
            for agent, metrics in sorted(
                item.agent_metrics.items(),
                key=lambda pair: (
                    preferred_order.get(pair[0], 50),
                    pair[0],
                ),
            )
        ]
        return RunDiagnostics(
            model=item.model,
            tokens=_sum_tokens([agent.tokens for agent in agents]),
            token_usage_partial=(
                bool(item.pending_model_calls)
                or any(agent.model_calls_missing_usage for agent in agents)
            ),
            model_calls=sum(agent.model_calls for agent in agents),
            model_call_errors=sum(agent.model_call_errors for agent in agents),
            model_calls_missing_usage=sum(
                agent.model_calls_missing_usage for agent in agents
            ),
            model_ms=sum(agent.model_ms for agent in agents),
            max_model_call_ms=max(
                (agent.max_model_call_ms for agent in agents), default=0
            ),
            tool_calls=sum(agent.tool_calls for agent in agents),
            tool_call_errors=sum(agent.tool_call_errors for agent in agents),
            tool_ms=sum(agent.tool_ms for agent in agents),
            elapsed_ms=_rounded_ms(max(0.0, ended_at - item.created_at)),
            active_ms=_rounded_ms(active_seconds),
            approval_wait_ms=_rounded_ms(approval_seconds),
            agents=agents,
        )

    def get(self, run_id: str, *, after_event_id: int = 0) -> RunResponse:
        with self._lock:
            item = self._get_mutable(run_id)
            events = [event for event in item.events if event.id > after_event_id]
            return RunResponse(
                run_id=item.run_id,
                thread_id=item.thread_id,
                source_id=item.source_id,
                question=item.question,
                phase=item.phase,
                findings=item.findings,
                status=item.status,
                events=events,
                next_event_id=len(item.events),
                debug_states=list(item.debug_states.values()),
                approval=item.approval,
                answer=item.answer,
                error=item.error,
                diagnostics=item.diagnostics,
                run_diagnostics=self._run_diagnostics(item, self._clock()),
            )

    def diagnostics(self, run_id: str) -> RunDiagnostics:
        with self._lock:
            return self._run_diagnostics(self._get_mutable(run_id), self._clock())

    def conversation_diagnostics(self, run_ids: list[str]) -> ConversationDiagnostics:
        with self._lock:
            now = self._clock()
            items = [self._items[run_id] for run_id in run_ids if run_id in self._items]
            runs = [self._run_diagnostics(item, now) for item in items]
            return ConversationDiagnostics(
                tokens=_sum_tokens([run.tokens for run in runs]),
                token_usage_partial=any(run.token_usage_partial for run in runs),
                model_calls=sum(run.model_calls for run in runs),
                model_call_errors=sum(run.model_call_errors for run in runs),
                model_calls_missing_usage=sum(
                    run.model_calls_missing_usage for run in runs
                ),
                model_ms=sum(run.model_ms for run in runs),
                tool_calls=sum(run.tool_calls for run in runs),
                tool_call_errors=sum(run.tool_call_errors for run in runs),
                tool_ms=sum(run.tool_ms for run in runs),
                elapsed_ms=sum(run.elapsed_ms for run in runs),
                active_ms=sum(run.active_ms for run in runs),
                approval_wait_ms=sum(run.approval_wait_ms for run in runs),
                run_count=len(runs),
                has_active_run=any(
                    item.status
                    in {
                        RunStatus.QUEUED,
                        RunStatus.RUNNING,
                        RunStatus.APPROVAL_REQUIRED,
                    }
                    for item in items
                ),
            )

    @persist_run
    def start_active(self, run_id: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            if item.active_started_at is None:
                item.active_started_at = self._clock()
            item.status = RunStatus.RUNNING

    @persist_run
    def set_status(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            self._get_mutable(run_id).status = status

    @persist_run
    def start_model_call(self, run_id: str, call_id: str, *, agent: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            if call_id in item.pending_model_calls:
                return
            normalized_agent = agent or "unknown"
            self._agent(item, normalized_agent).model_calls += 1
            item.pending_model_calls[call_id] = _PendingCall(
                agent=normalized_agent,
                started_at=self._clock(),
            )

    @persist_run
    def finish_model_call(
        self,
        run_id: str,
        call_id: str,
        *,
        usage: Mapping[str, Any] | None,
        failed: bool = False,
    ) -> int:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            pending = item.pending_model_calls.pop(call_id, None)
            if pending is None:
                pending = _PendingCall(agent="unknown", started_at=now)
                self._agent(item, "unknown").model_calls += 1
            metrics = self._agent(item, pending.agent)
            duration = max(0.0, now - pending.started_at)
            metrics.model_seconds += duration
            metrics.max_model_call_seconds = max(
                metrics.max_model_call_seconds, duration
            )
            if failed:
                metrics.model_call_errors += 1
            if not _valid_usage(usage):
                metrics.model_calls_missing_usage += 1
            else:
                metrics.tokens.add(usage)
            return _rounded_ms(duration)

    @persist_run
    def start_tool_call(self, run_id: str, call_id: str, *, agent: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            if call_id in item.pending_tool_calls:
                return
            normalized_agent = agent or "unknown"
            self._agent(item, normalized_agent).tool_calls += 1
            item.pending_tool_calls[call_id] = _PendingCall(
                agent=normalized_agent,
                started_at=self._clock(),
            )

    @persist_run
    def finish_tool_call(
        self, run_id: str, call_id: str, *, agent: str, failed: bool
    ) -> int:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            pending = item.pending_tool_calls.pop(call_id, None)
            if pending is None:
                normalized_agent = agent or "unknown"
                self._agent(item, normalized_agent).tool_calls += 1
                pending = _PendingCall(
                    agent=normalized_agent,
                    started_at=now,
                )
            metrics = self._agent(item, pending.agent)
            duration = max(0.0, now - pending.started_at)
            metrics.tool_seconds += duration
            if failed:
                metrics.tool_call_errors += 1
            return _rounded_ms(duration)

    @persist_run
    def reserve_python_execution_attempt(
        self,
        run_id: str,
        *,
        maximum: int = 0,
    ) -> int:
        """Count actual executions, excluding review rejections."""

        with self._lock:
            item = self._get_mutable(run_id)
            item.python_execution_attempts += 1
            return item.python_execution_attempts

    def python_execution_attempt_count(self, run_id: str) -> int:
        """Return actual statistical Python executions used by this run."""

        with self._lock:
            return self._get_mutable(run_id).python_execution_attempts

    @persist_run
    def record_python_execution(
        self,
        run_id: str,
        execution: PythonExecutionResult,
    ) -> None:
        """Retain the authoritative successful execution for final validation."""

        with self._lock:
            self._get_mutable(run_id).python_executions.append(execution)

    def get_python_execution(
        self,
        run_id: str,
    ) -> list[PythonExecutionResult]:
        with self._lock:
            return list(self._get_mutable(run_id).python_executions)

    def get_last_review_type(self, run_id: str) -> str:
        with self._lock:
            return self._get_mutable(run_id).last_review_type

    @persist_run
    def add_event(
        self,
        run_id: str,
        kind: str,
        label: str,
        *,
        phase: str = "info",
        agent: str | None = None,
        tool: ActivityTool | None = None,
        duration_ms: int | None = None,
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
                duration_ms=duration_ms,
            )
            item.events.append(event)
            return event

    @persist_run
    def set_debug_state(
        self,
        run_id: str,
        snapshot: AgentStateSnapshot,
    ) -> None:
        """Replace the latest debug snapshot for one recognized agent."""

        with self._lock:
            self._get_mutable(run_id).debug_states[snapshot.agent] = snapshot

    @persist_run
    def require_approval(
        self,
        run_id: str,
        approval: ApprovalRequest,
    ) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.APPROVAL_REQUIRED
            item.approval = approval
            item.approval_started_at = now

    @persist_run
    def resume(self, run_id: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            item.status = RunStatus.RUNNING
            item.approval = None
            item.error = None

    @persist_run
    def claim_approval(
        self,
        run_id: str,
        expected: ApprovalRequest,
    ) -> int:
        """Atomically claim one pending review before applying its decision."""

        with self._lock:
            item = self._get_mutable(run_id)
            if item.status != RunStatus.APPROVAL_REQUIRED or item.approval != expected:
                raise RuntimeError("This run is no longer awaiting that decision.")
            now = self._clock()
            wait_seconds = 0.0
            if item.approval_started_at is not None:
                wait_seconds = max(0.0, now - item.approval_started_at)
                item.approval_seconds += wait_seconds
                item.approval_started_at = None
            item.status = RunStatus.RUNNING
            item.last_review_type = expected.review_type
            item.approval = None
            item.error = None
            return _rounded_ms(wait_seconds)

    @persist_run
    def complete(self, run_id: str, answer: FinalAnswer) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.COMPLETED
            item.terminal_at = now
            item.answer = answer
            item.approval = None

    @persist_run
    def fail(
        self,
        run_id: str,
        error: str,
        *,
        diagnostics: ExecutionBudgetDiagnostics | None = None,
    ) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.FAILED
            item.terminal_at = now
            item.error = error
            item.diagnostics = diagnostics
            item.approval = None

    @persist_run
    def set_phase(self, run_id: str, phase: str):
        self._get_mutable(run_id).phase = phase

    @persist_run
    def publish(self, run_id: str, answer: FinalAnswer):
        item = self._get_mutable(run_id)
        item.findings = answer
        item.phase = "findings_ready"

    @persist_run
    def save_report_spec(self, run_id: str, spec: dict):
        self._get_mutable(run_id).report_spec = spec

    def report_spec(self, run_id: str):
        return self._get_mutable(run_id).report_spec

    @persist_run
    def add_chart(self, run_id: str, spec: dict):
        item = self._get_mutable(run_id)
        if spec not in item.chart_specs:
            item.chart_specs.append(spec)

    def charts(self, run_id: str):
        return self._get_mutable(run_id).chart_specs

    @persist_run
    def pause(self, run_id: str):
        item = self._get_mutable(run_id)
        self._stop_active(item, self._clock())
        item.status = RunStatus.PAUSED
        item.pending_model_calls.clear()
        item.pending_tool_calls.clear()

    def recover(self):
        for key, item in self._items.items():
            if item.status in {RunStatus.RUNNING, RunStatus.QUEUED, RunStatus.STOPPING}:
                self._stop_active(
                    item, item.last_saved_at or item.active_started_at or self._clock()
                )
                self.pause(key)

    def cancel_event(self, run_id: str):
        from threading import Event

        with self._lock:
            if not hasattr(self, "_cancel_events"):
                self._cancel_events = {}
            return self._cancel_events.setdefault(run_id, Event())

    def analysis_stop_reason(self, run_id: str):
        if self.cancel_event(run_id).is_set():
            raise InterruptedError("Run stopped.")
        if self.get(run_id).findings is not None:
            return "Findings are published. Only presentation work remains; do not rerun analysis."
        if (
            self.diagnostics(run_id).active_ms
            >= getattr(self, "analysis_budget_seconds", 900) * 1000
        ):
            return "Analysis time budget exhausted. Synthesize supported partial findings and create their report now."
        return None

    @persist_run
    def attach_report(self, run_id: str, reference):
        self._get_mutable(run_id).report_reference = reference.model_dump(mode="json")

    def report_reference(self, run_id: str):
        return self._get_mutable(run_id).report_reference

    def workers_active(self, run_id):
        return getattr(self, "_workers", {}).get(run_id, 0)

    @__import__("contextlib").contextmanager
    def source_worker(self, run_id):
        from threading import Lock

        thread_id = self.get(run_id).thread_id
        with self._lock:
            if not hasattr(self, "_source_locks"):
                self._source_locks = {}
            lock = self._source_locks.setdefault(thread_id, Lock())
        with self.worker(run_id), lock:
            if self.cancel_event(run_id).is_set():
                raise InterruptedError("Run stopped before source execution.")
            yield

    @__import__("contextlib").contextmanager
    def worker(self, run_id):
        with self._lock:
            if not hasattr(self, "_workers"):
                self._workers = {}
            self._workers[run_id] = self._workers.get(run_id, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                self._workers[run_id] -= 1
