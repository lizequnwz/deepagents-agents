"""Thread-safe, process-local stores for the POC."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import uuid4

from data_analytics_agent.agents.statistical_analysis.schemas import (
    PythonExecutionResult,
    StatisticalAnalysisResult,
)
from data_analytics_agent.profiling import profile_result
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
    ResultPage,
    RunDiagnostics,
    RunResponse,
    RunStatus,
    SavedResult,
    SavedStatisticalAnalysis,
    TokenUsage,
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


class StatisticalAnalysisStore:
    """Retains reusable, source-scoped statistical analysis artifacts."""

    def __init__(self) -> None:
        self._items: dict[str, SavedStatisticalAnalysis] = {}
        self._lock = RLock()

    def save(
        self,
        *,
        thread_id: str,
        source_id: str,
        analysis: StatisticalAnalysisResult,
    ) -> SavedStatisticalAnalysis:
        analysis_id = str(uuid4())
        authoritative = analysis.model_copy(update={"analysis_id": analysis_id})
        saved = SavedStatisticalAnalysis(
            analysis_id=analysis_id,
            thread_id=thread_id,
            source_id=source_id,
            analysis=authoritative,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._items[analysis_id] = saved
        return saved

    def get(
        self,
        analysis_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
    ) -> SavedStatisticalAnalysis:
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
    ) -> list[SavedStatisticalAnalysis]:
        with self._lock:
            items = [
                item
                for item in self._items.values()
                if item.thread_id == thread_id and item.source_id == source_id
            ]
        return sorted(items, key=lambda item: item.created_at)


class ReportStore:
    """Stores exact rendered HTML outside model and checkpoint context."""

    def __init__(self) -> None:
        self._items: dict[str, ReportArtifact] = {}
        self._lock = RLock()

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
        artifact = ReportArtifact(
            report_id=str(uuid4()),
            thread_id=thread_id,
            source_id=source_id,
            title=spec.title,
            version=(previous.version + 1 if previous else 1),
            previous_report_id=previous.report_id if previous else None,
            spec=spec,
            html=html,
            html_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
            renderer_version=REPORT_RENDERER_VERSION,
            input_result_ids=list(dict.fromkeys(input_result_ids)),
            input_analysis_ids=list(dict.fromkeys(input_analysis_ids)),
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._items[artifact.report_id] = artifact
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
            item.run_ids.append(run_id)
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
            if (
                isinstance(cached, int)
                and not isinstance(cached, bool)
                and cached >= 0
            ):
                self.cached_input_tokens = (
                    (self.cached_input_tokens or 0) + cached
                )
        output_details = usage.get("output_token_details")
        if isinstance(output_details, Mapping):
            reasoning = output_details.get("reasoning")
            if (
                isinstance(reasoning, int)
                and not isinstance(reasoning, bool)
                and reasoning >= 0
            ):
                self.reasoning_output_tokens = (
                    (self.reasoning_output_tokens or 0) + reasoning
                )

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
    model: str = ""
    status: RunStatus = RunStatus.QUEUED
    events: list[ActivityEvent] = field(default_factory=list)
    debug_states: dict[str, AgentStateSnapshot] = field(default_factory=dict)
    approval: ApprovalRequest | None = None
    answer: FinalAnswer | None = None
    error: str | None = None
    diagnostics: ExecutionBudgetDiagnostics | None = None
    statistical_execution_attempts: int = 0
    statistical_execution: PythonExecutionResult | None = None
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
        reasoning_output_tokens=(
            sum(reasoning_values) if reasoning_values else None
        ),
    )


class RunStore:
    def __init__(self, *, clock: Callable[[], float] = perf_counter) -> None:
        self._items: dict[str, _Run] = {}
        self._lock = RLock()
        self._clock = clock

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
            "statistical-analysis": 2,
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
                max_model_call_ms=_rounded_ms(
                    metrics.max_model_call_seconds
                ),
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
                or any(
                    agent.model_calls_missing_usage for agent in agents
                )
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
            return self._run_diagnostics(
                self._get_mutable(run_id), self._clock()
            )

    def conversation_diagnostics(
        self, run_ids: list[str]
    ) -> ConversationDiagnostics:
        with self._lock:
            now = self._clock()
            items = [
                self._items[run_id]
                for run_id in run_ids
                if run_id in self._items
            ]
            runs = [self._run_diagnostics(item, now) for item in items]
            return ConversationDiagnostics(
                tokens=_sum_tokens([run.tokens for run in runs]),
                token_usage_partial=any(
                    run.token_usage_partial for run in runs
                ),
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
                approval_wait_ms=sum(
                    run.approval_wait_ms for run in runs
                ),
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

    def start_active(self, run_id: str) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            if item.active_started_at is None:
                item.active_started_at = self._clock()
            item.status = RunStatus.RUNNING

    def set_status(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            self._get_mutable(run_id).status = status

    def start_model_call(
        self, run_id: str, call_id: str, *, agent: str
    ) -> None:
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

    def start_tool_call(
        self, run_id: str, call_id: str, *, agent: str
    ) -> None:
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

    def reserve_statistical_execution_attempt(
        self,
        run_id: str,
        *,
        maximum: int,
    ) -> int:
        """Count actual reviewed executions, excluding review rejections."""

        with self._lock:
            item = self._get_mutable(run_id)
            if item.statistical_execution_attempts >= maximum:
                raise RuntimeError(
                    f"The run already used all {maximum} statistical Python "
                    "execution attempts."
                )
            item.statistical_execution_attempts += 1
            return item.statistical_execution_attempts

    def record_statistical_execution(
        self,
        run_id: str,
        execution: PythonExecutionResult,
    ) -> None:
        """Retain the authoritative successful execution for final validation."""

        with self._lock:
            self._get_mutable(run_id).statistical_execution = execution

    def get_statistical_execution(
        self,
        run_id: str,
    ) -> PythonExecutionResult | None:
        with self._lock:
            return self._get_mutable(run_id).statistical_execution

    def get_last_review_type(self, run_id: str) -> str:
        with self._lock:
            return self._get_mutable(run_id).last_review_type

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
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.APPROVAL_REQUIRED
            item.approval = approval
            item.approval_started_at = now

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
    ) -> int:
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

    def complete(self, run_id: str, answer: FinalAnswer) -> None:
        with self._lock:
            item = self._get_mutable(run_id)
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.COMPLETED
            item.terminal_at = now
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
            now = self._clock()
            self._stop_active(item, now)
            item.status = RunStatus.FAILED
            item.terminal_at = now
            item.error = error
            item.diagnostics = diagnostics
            item.approval = None
