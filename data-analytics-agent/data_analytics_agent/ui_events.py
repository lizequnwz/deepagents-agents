"""Read-only run attachments with AG-UI payloads over application-owned SSE.

This GET endpoint is not AG-UI's POST run binding. It attaches to an existing
RunManager run; reconnecting, closing, or cancelling the attachment cannot invoke
or stop a graph. Only the public projection below can cross this boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import monotonic

from ag_ui.core import (
    CustomEvent,
    Interrupt,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.schemas import ActivityEvent, RunResponse, RunStatus

# Free-form labels, tool arguments/results, questions, exceptions, and graph
# snapshots must never be copied into the public stream, even when redacted.
_TOOL_LABELS = {
    "task": "Delegate work",
    "write_todos": "Update the plan",
    "get_semantic_context": "Read business definitions",
    "browse_semantic_model": "Browse business definitions",
    "lookup_values": "Look up filter values",
    "execute_sql": "Retrieve data",
    "query_saved_results": "Query saved data",
    "execute_dashboard_query": "Calculate dashboard data",
    "execute_analysis_python": "Analyze saved data",
    "finish_analysis": "Save analysis",
    "create_chart": "Prepare a chart",
    "create_dashboard": "Prepare the dashboard",
    "create_report": "Prepare the report",
    "publish_findings": "Publish findings",
    "save_investigation": "Save investigation progress",
    "request_clarification": "Request clarification",
    "list_documents": "List source documents",
    "read_document": "Read a source document",
    "search_documents": "Search source documents",
    "list_conversation_results": "List saved data",
    "inspect_conversation_result": "Inspect saved data",
    "list_conversation_charts": "List saved charts",
    "list_conversation_analyses": "List saved analyses",
    "inspect_conversation_analysis": "Inspect saved analysis",
}
_AGENTS = {"coordinator", "text-to-sql", "data-analysis"}
_PHASES = {"understanding", "retrieving_data", "analyzing", "findings_ready", "preparing_report"}
_CLOSED_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.PAUSED,
    RunStatus.APPROVAL_REQUIRED,
    RunStatus.CLARIFICATION_REQUIRED,
}
_POLL_SECONDS = 0.5
_HEARTBEAT_SECONDS = 15


def public_run_state(run: RunResponse) -> dict:
    """Select public status fields; do not serialize an internal run wholesale."""
    clarification = (
        {"interrupt_id": run.clarification.interrupt_id}
        if run.status == RunStatus.CLARIFICATION_REQUIRED and run.clarification
        else None
    )
    review = None
    if run.status == RunStatus.APPROVAL_REQUIRED and run.approval:
        review = {
            "interrupt_id": run.approval.interrupt_id,
            "review_types": sorted({a.review_type for a in run.approval.actions}),
            "action_count": len(run.approval.actions),
        }
    return {
        "schema_version": "1.0",
        "thread_id": run.thread_id,
        "source_id": run.source_id,
        "run_id": run.run_id,
        "status": run.status.value,
        "phase": run.phase if run.phase in _PHASES else "working",
        "next_event_id": run.next_event_id,
        "report_ready": run.report_ready,
        "findings_ready": run.findings is not None,
        "answer_ready": run.answer is not None,
        "clarification": clarification,
        "review": review,
    }


def public_activity(event: ActivityEvent) -> dict:
    """Retain event identity and safe lifecycle fields, never diagnostic content."""
    name = event.tool.name if event.tool and event.tool.name in _TOOL_LABELS else None
    return {
        "id": event.id,
        "kind": "tool" if event.kind == "tool" else "activity",
        "label": _TOOL_LABELS.get(name, "Update analysis progress"),
        "phase": event.phase,
        "agent": event.agent if event.agent in _AGENTS else None,
        "tool_name": name,
        "duration_ms": event.duration_ms,
        "created_at": event.created_at.isoformat(),
    }


def _scoped_run(services, thread_id: str, run_id: str, cursor: int) -> RunResponse:
    # Use the same application lock as history deletion and action admission.
    with services._lock:
        if thread_id in services.deleting_conversations:
            raise HTTPException(409, "Wait for history deletion to finish.")
        conversation = services.conversations.get(thread_id)
        run = services.runs.get(run_id, after_event_id=cursor)
        if run.thread_id != thread_id or run.source_id != conversation.source_id:
            raise StoreNotFound("Resource not found.")
        return run


def _cursor(run_id: str, after_event_id: int, last_event_id: str | None) -> int:
    if last_event_id is None:
        return after_event_id
    attached_run, separator, number = last_event_id.rpartition(":")
    if (
        not separator
        or attached_run != run_id
        or not number.isascii()
        or not number.isdecimal()
    ):
        raise HTTPException(
            422, "Last-Event-ID must identify this run and its activity cursor."
        )
    # Bound parsing before converting an untrusted HTTP header into an integer.
    if len(number) > 16:
        raise HTTPException(422, "The activity cursor is invalid.")
    return int(number)


def _terminal(run: RunResponse):
    if run.status == RunStatus.FAILED:
        return RunErrorEvent(
            message="The run failed. Open the run details to inspect the error.",
            code="RUN_FAILED",
        )
    if run.status in {RunStatus.APPROVAL_REQUIRED, RunStatus.CLARIFICATION_REQUIRED}:
        pending = (
            run.approval
            if run.status == RunStatus.APPROVAL_REQUIRED
            else run.clarification
        )
        outcome = RunFinishedInterruptOutcome(
            interrupts=[
                Interrupt(
                    id=pending.interrupt_id if pending else run.run_id,
                    reason=run.status.value,
                )
            ]
        )
    elif run.status == RunStatus.PAUSED:
        outcome = RunFinishedCancelledOutcome()
    else:
        outcome = RunFinishedSuccessOutcome()
    return RunFinishedEvent(
        thread_id=run.thread_id,
        run_id=run.run_id,
        result={"status": run.status.value},
        outcome=outcome,
    )


async def attach_run_events(
    services,
    request: Request,
    initial: RunResponse,
    cursor: int,
) -> AsyncIterator[str]:
    """Observe saved state. SSE IDs are retained activity cursors, not invocations.

    Every attachment replays the run's opening and sends its current public
    snapshot. Activity after the cursor is replayed with its original IDs. State
    and terminal frames do not advance the cursor, so a disconnected client can
    recover the current state without losing activity. Resume uses the existing
    explicit application endpoints and a fresh attachment.
    """
    encoder = EventEncoder()
    if await request.is_disconnected():
        return
    try:
        initial = _scoped_run(services, initial.thread_id, initial.run_id, cursor)
    except (StoreNotFound, HTTPException):
        yield encoder.encode(
            RunErrorEvent(
                message="The run attachment is no longer available.",
                code="ATTACHMENT_UNAVAILABLE",
            )
        )
        return
    yield encoder.encode(
        RunStartedEvent(
            thread_id=initial.thread_id, run_id=initial.run_id, protocol_version="1.0"
        )
    )
    state = public_run_state(initial)
    yield encoder.encode(StateSnapshotEvent(snapshot=state))
    run, last_state, last_output = initial, state, monotonic()
    while True:
        if await request.is_disconnected():
            return
        try:
            # Recheck scope/deletion before each batch, including the first one.
            run = _scoped_run(services, run.thread_id, run.run_id, cursor)
        except (StoreNotFound, HTTPException):
            yield encoder.encode(
                RunErrorEvent(
                    message="The run attachment is no longer available.",
                    code="ATTACHMENT_UNAVAILABLE",
                )
            )
            return
        had_events = bool(run.events)
        for event in run.events:
            yield f"id: {run.run_id}:{event.id}\n" + encoder.encode(
                CustomEvent(name="analytics.activity", value=public_activity(event))
            )
            cursor = event.id
        state = public_run_state(run)
        if state != last_state or had_events:
            yield encoder.encode(StateSnapshotEvent(snapshot=state))
            last_state, last_output = state, monotonic()
        if run.status in _CLOSED_STATUSES:
            yield encoder.encode(_terminal(run))
            return
        if monotonic() - last_output >= _HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_output = monotonic()
        await asyncio.sleep(_POLL_SECONDS)


def ui_events_router(services) -> APIRouter:
    router = APIRouter()

    @router.get("/api/conversations/{thread_id}/runs/{run_id}/events")
    async def observe_run(
        thread_id: str,
        run_id: str,
        request: Request,
        after_event_id: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        """Attach to an existing run; this endpoint never starts execution."""
        cursor = _cursor(run_id, after_event_id, last_event_id)
        run = _scoped_run(services, thread_id, run_id, cursor)
        if cursor > run.next_event_id:
            raise HTTPException(409, "The activity cursor is ahead of the saved run.")
        return StreamingResponse(
            attach_run_events(services, request, run, cursor),
            media_type=EventEncoder().get_content_type(),
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
