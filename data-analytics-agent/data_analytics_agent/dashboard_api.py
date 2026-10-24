"""Dashboard HTTP lifecycle over the existing governed analytical runs."""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import Field

from data_analytics_agent.dashboard.schemas import (
    DashboardAction,
    DashboardActionRecord,
    DashboardFilter,
    DashboardModel,
    DashboardSpec,
    DashboardViewEdit,
)
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.dashboard.store import DashboardConflict
from data_analytics_agent.schemas import RunStatus


class CreateDashboardRequest(DashboardModel):
    run_id: str = Field(min_length=1)
    request_id: str = Field(default_factory=lambda: str(uuid4()), max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    spec: DashboardSpec | None = None
    filters: list[DashboardFilter] | None = None


def dashboard_router(services) -> APIRouter:
    router = APIRouter(prefix="/api/conversations/{thread_id}/dashboards")
    service = DashboardService(
        results=services.results,
        analyses=services.analyses,
        runs=services.runs,
        reports=services.reports,
        dashboards=services.dashboards,
    )

    def conversation(thread_id, *, idle=False):
        if thread_id in services.deleting_conversations:
            raise HTTPException(409, "Wait for history deletion to finish.")
        item = services.conversations.get(thread_id)
        if idle and (
            item.active_run_id or thread_id in services.uploading_conversations
        ):
            raise HTTPException(
                409, "Finish active work before changing the dashboard."
            )
        return item

    def failure(exc):
        return HTTPException(
            409 if isinstance(exc, DashboardConflict) else 422, str(exc)
        )

    @router.get("")
    def list_dashboards(thread_id: str):
        item = conversation(thread_id)
        return {
            "dashboards": services.dashboards.list_for_conversation(
                thread_id, source_id=item.source_id
            )
        }

    @router.post("", status_code=201)
    def create_dashboard(thread_id: str, request: CreateDashboardRequest):
        with services._lock:
            item = conversation(thread_id, idle=True)
            run = services.runs.get(request.run_id)
            if run.thread_id != thread_id or run.source_id != item.source_id:
                raise HTTPException(404, "Resource not found.")
            if run.status != RunStatus.COMPLETED:
                raise HTTPException(
                    409, "Complete the answer and report before saving a dashboard."
                )
            try:
                revised = service.create_from_report(
                    request.run_id,
                    thread_id=thread_id,
                    source_id=item.source_id,
                    title=request.title,
                    spec=request.spec,
                    filters=request.filters,
                    request_id=request.request_id,
                )
                return service.view(
                    revised.dashboard_id, thread_id, source_id=item.source_id
                )
            except ValueError as exc:
                raise failure(exc) from exc

    @router.get("/{dashboard_id}")
    def get_dashboard(thread_id: str, dashboard_id: str):
        item = conversation(thread_id)
        return service.view(dashboard_id, thread_id, source_id=item.source_id)

    @router.get("/{dashboard_id}/revisions")
    def dashboard_revisions(thread_id: str, dashboard_id: str):
        item = conversation(thread_id)
        return {
            "revisions": services.dashboards.history(
                dashboard_id, thread_id, source_id=item.source_id
            )
        }

    @router.post("/{dashboard_id}/view")
    def edit_view(thread_id: str, dashboard_id: str, request: DashboardViewEdit):
        with services._lock:
            item = conversation(thread_id, idle=True)
            try:
                service.edit_view(
                    dashboard_id,
                    thread_id,
                    source_id=item.source_id,
                    edit=request,
                )
                return service.view(dashboard_id, thread_id, source_id=item.source_id)
            except ValueError as exc:
                raise failure(exc) from exc

    @router.post("/{dashboard_id}/actions", status_code=202)
    def dashboard_action(
        thread_id: str,
        dashboard_id: str,
        request: DashboardAction,
        background_tasks: BackgroundTasks,
    ):
        with services._lock:
            item = conversation(thread_id)
            services.dashboards.get(dashboard_id, thread_id, source_id=item.source_id)
            previous = next(
                (
                    action
                    for action in services.storage.load(
                        "dashboard_actions", DashboardActionRecord
                    ).values()
                    if action.dashboard_id == dashboard_id
                    and action.request_id == request.request_id
                ),
                None,
            )
            # A network retry must resolve its original run even while that run is active.
            if previous and previous.request_id == request.request_id:
                try:
                    record = services.dashboards.begin_action(
                        dashboard_id,
                        thread_id,
                        source_id=item.source_id,
                        action=request,
                    )
                except ValueError as exc:
                    raise failure(exc) from exc
                if record.run_id is None:
                    raise HTTPException(
                        409,
                        record.error
                        or "This action did not start. Submit a new request.",
                    )
                return {
                    "run_id": record.run_id,
                    "status": services.runs.get(record.run_id).status,
                    "action_id": record.action_id,
                }
            conversation(thread_id, idle=True)
            readiness = services.settings.readiness_errors(include_sources=False)
            if readiness and services.agent is None:
                raise HTTPException(503, " ".join(readiness))
            try:
                services.require_ready_source(item.source_id)
                plan = service.action_plan(
                    dashboard_id,
                    thread_id,
                    source_id=item.source_id,
                    action=request,
                )
                record = services.dashboards.begin_action(
                    dashboard_id, thread_id, source_id=item.source_id, action=request
                )
            except ValueError as exc:
                raise failure(exc) from exc
            run_id = None
            try:
                manager = services.manager()
                run_id = services.runs.create(
                    thread_id,
                    item.source_id,
                    {
                        "filter": "Apply dashboard filters",
                        "refresh": "Refresh dashboard data",
                        "drill": request.question or "Investigate dashboard component",
                    }[request.action],
                    model=services.settings.model,
                )
                services.storage.put(
                    "dashboard_run_context",
                    run_id,
                    {
                        "thread_id": thread_id,
                        "source_id": item.source_id,
                        "run_id": run_id,
                        "brief": plan.question,
                    },
                )
                services.dashboards.attach_action_run(record.action_id, run_id)
                services.conversations.begin_run(thread_id, run_id)
            except Exception as exc:
                services.dashboards.fail_action(record.action_id, str(exc))
                if run_id:
                    services.runs.fail(run_id, str(exc))
                    services.conversations.fail_run(thread_id, run_id)
                raise
        background_tasks.add_task(manager.start, run_id)
        return {
            "run_id": run_id,
            "status": RunStatus.QUEUED,
            "action_id": record.action_id,
        }

    return router
