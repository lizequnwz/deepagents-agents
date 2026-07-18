"""FastAPI application for conversations, runs, HITL decisions, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse

from text2sql_agent.agent import build_agent
from text2sql_agent.config import Settings
from text2sql_agent.run_manager import RunManager, decisions_to_command
from text2sql_agent.schemas import (
    ConversationResponse,
    CreateConversationResponse,
    CreateRunResponse,
    DecisionRequest,
    HealthResponse,
    MessageRequest,
    ResultPage,
    RunResponse,
    RunStatus,
)
from text2sql_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
    StoreNotFound,
)


@dataclass
class Services:
    settings: Settings = field(default_factory=Settings)
    conversations: ConversationStore = field(default_factory=ConversationStore)
    runs: RunStore = field(default_factory=RunStore)
    results: ResultStore = field(default_factory=ResultStore)
    agent: Any | None = None
    _manager: RunManager | None = None
    _lock: RLock = field(default_factory=RLock)

    def manager(self) -> RunManager:
        with self._lock:
            if self._manager is None:
                graph = self.agent or build_agent(self.settings, self.results)
                self._manager = RunManager(
                    agent=graph,
                    conversations=self.conversations,
                    runs=self.runs,
                    results=self.results,
                )
            return self._manager


def create_app(services: Services | None = None) -> FastAPI:
    container = services or Services()
    app = FastAPI(
        title="Chinook Deep-Agent Text-to-SQL API",
        version="0.2.0",
    )
    app.state.services = container

    @app.exception_handler(StoreNotFound)
    async def not_found_handler(_request, _exc):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Resource not found."},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        errors = container.settings.readiness_errors()
        return HealthResponse(
            status="not_ready" if errors else "ok",
            model=container.settings.model,
            database_path=str(container.settings.database_path),
            errors=errors,
        )

    @app.post(
        "/api/conversations",
        response_model=CreateConversationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation() -> CreateConversationResponse:
        return CreateConversationResponse(
            thread_id=container.conversations.create()
        )

    @app.get(
        "/api/conversations/{thread_id}",
        response_model=ConversationResponse,
    )
    async def get_conversation(thread_id: str) -> ConversationResponse:
        return container.conversations.get(thread_id)

    @app.post(
        "/api/conversations/{thread_id}/messages",
        response_model=CreateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def post_message(
        thread_id: str,
        request: MessageRequest,
        background_tasks: BackgroundTasks,
    ) -> CreateRunResponse:
        readiness_errors = container.settings.readiness_errors()
        if readiness_errors and container.agent is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=" ".join(readiness_errors),
            )
        conversation = container.conversations.get(thread_id)
        if conversation.active_run_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A run is already active for this conversation.",
            )
        manager = container.manager()
        run_id = container.runs.create(thread_id, request.message.strip())
        try:
            container.conversations.begin_run(thread_id, run_id)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        background_tasks.add_task(manager.start, run_id)
        return CreateRunResponse(run_id=run_id, status=RunStatus.QUEUED)

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    async def get_run(
        run_id: str,
        after_event_id: int = Query(default=0, ge=0),
    ) -> RunResponse:
        return container.runs.get(
            run_id, after_event_id=after_event_id
        )

    @app.post(
        "/api/runs/{run_id}/decisions",
        response_model=CreateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def post_decision(
        run_id: str,
        request: DecisionRequest,
        background_tasks: BackgroundTasks,
    ) -> CreateRunResponse:
        run = container.runs.get(run_id)
        if run.status != RunStatus.APPROVAL_REQUIRED or run.approval is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This run is not awaiting a decision.",
            )
        try:
            command = decisions_to_command(run.approval, request.decisions)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        container.runs.resume(run_id)
        background_tasks.add_task(
            container.manager().resume, run_id, command
        )
        return CreateRunResponse(run_id=run_id, status=RunStatus.RUNNING)

    @app.get("/api/results/{result_id}", response_model=ResultPage)
    async def get_result(
        result_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> ResultPage:
        return container.results.page_unscoped(
            result_id, offset=offset, limit=limit
        )

    return app


app = create_app()
