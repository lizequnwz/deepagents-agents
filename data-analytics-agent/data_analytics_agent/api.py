"""FastAPI application for source-bound conversations, runs, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse

from data_analytics_agent.coordinator import build_agent
from data_analytics_agent.backends import SQLBackend, create_backend
from data_analytics_agent.config import Settings
from data_analytics_agent.data_sources import DataSource, DataSourceCatalog
from data_analytics_agent.run_manager import (
    RunManager,
    decisions_to_command,
)
from data_analytics_agent.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    CreateRunResponse,
    DataSourceSummary,
    DataSourcesResponse,
    DecisionRequest,
    ExampleQuestionResponse,
    ExecutionLimitsResponse,
    HealthResponse,
    MessageRequest,
    ResultPage,
    RunResponse,
    RunStatus,
)
from data_analytics_agent.semantic import validate_semantic_model
from data_analytics_agent.stores import (
    ConversationStore,
    ResultStore,
    RunStore,
    StoreNotFound,
)


def _create_snowflake_client() -> Any:
    """Create the optional snowlib client at the application boundary."""

    try:
        from snowlib import SnowflakeManager
    except ImportError as exc:
        raise RuntimeError(
            "Snowflake sources require the optional snowlib package."
        ) from exc
    return SnowflakeManager().get_client()


@dataclass
class Services:
    settings: Settings = field(default_factory=Settings)
    conversations: ConversationStore = field(default_factory=ConversationStore)
    runs: RunStore = field(default_factory=RunStore)
    results: ResultStore = field(default_factory=ResultStore)
    agent: Any | None = None
    catalog: DataSourceCatalog | None = None
    snowflake_client: Any | None = None
    _manager: RunManager | None = None
    _backends: dict[str, SQLBackend] = field(default_factory=dict)
    _agents: dict[str, Any] = field(default_factory=dict)
    _source_summaries: dict[str, DataSourceSummary] | None = None
    _lock: RLock = field(default_factory=RLock)

    def source_catalog(self) -> DataSourceCatalog:
        with self._lock:
            if self.catalog is None:
                self.catalog = self.settings.load_catalog()
            return self.catalog

    def source(self, source_id: str) -> DataSource:
        try:
            return self.source_catalog().get(source_id)
        except KeyError as exc:
            raise StoreNotFound(source_id) from exc

    def backend_for_source(self, source_id: str) -> SQLBackend:
        with self._lock:
            backend = self._backends.get(source_id)
            if backend is None:
                source = self.source(source_id)
                if (
                    source.backend_type == "snowflake"
                    and self.snowflake_client is None
                ):
                    self.snowflake_client = _create_snowflake_client()
                backend = create_backend(
                    source,
                    self.settings.project_root,
                    snowflake_client=self.snowflake_client,
                )
                self._backends[source_id] = backend
            return backend

    def source_summaries(self) -> list[DataSourceSummary]:
        with self._lock:
            if self._source_summaries is None:
                summaries: dict[str, DataSourceSummary] = {}
                for source_id, source in self.source_catalog().sources.items():
                    errors: list[str] = []
                    warnings: list[str] = []
                    backend: SQLBackend | None = None
                    try:
                        backend = self.backend_for_source(source_id)
                    except Exception as exc:
                        errors.append(str(exc))
                    if backend is not None:
                        errors.extend(backend.readiness_errors())
                    semantic = validate_semantic_model(
                        source.semantic_model_path,
                        dialect=source.dialect,
                        backend=backend if not errors else None,
                    )
                    errors.extend(semantic.errors)
                    warnings.extend(semantic.warnings)
                    summaries[source_id] = DataSourceSummary(
                        source_id=source_id,
                        name=source.name,
                        description=source.description,
                        backend_type=source.backend_type,
                        dialect=source.dialect,
                        ready=not errors,
                        errors=errors,
                        warnings=warnings,
                        examples=[
                            ExampleQuestionResponse(
                                label=example.label,
                                question=example.question,
                            )
                            for example in source.examples
                        ],
                        limits=ExecutionLimitsResponse(
                            timeout_seconds=source.limits.timeout_seconds,
                            max_result_rows=source.limits.max_result_rows,
                            model_sample_rows=source.limits.model_sample_rows,
                        ),
                    )
                self._source_summaries = summaries
            return list(self._source_summaries.values())

    def source_summary(self, source_id: str) -> DataSourceSummary:
        for summary in self.source_summaries():
            if summary.source_id == source_id:
                return summary
        raise StoreNotFound(source_id)

    def require_ready_source(self, source_id: str) -> DataSource:
        summary = self.source_summary(source_id)
        if not summary.ready:
            raise ValueError(
                f"Data source {summary.name!r} is unavailable: "
                + " ".join(summary.errors)
            )
        return self.source(source_id)

    def agent_for_source(self, source_id: str) -> Any:
        if self.agent is not None:
            return self.agent
        with self._lock:
            graph = self._agents.get(source_id)
            if graph is None:
                source = self.require_ready_source(source_id)
                graph = build_agent(
                    self.settings,
                    self.results,
                    source=source,
                    backend=self.backend_for_source(source_id),
                )
                self._agents[source_id] = graph
            return graph

    def manager(self) -> RunManager:
        with self._lock:
            if self._manager is None:
                self._manager = RunManager(
                    agent_resolver=self.agent_for_source,
                    source_resolver=self.source,
                    conversations=self.conversations,
                    runs=self.runs,
                    results=self.results,
                    debug_details=self.settings.agent_debug_details,
                )
            return self._manager


def create_app(services: Services | None = None) -> FastAPI:
    container = services or Services()
    app = FastAPI(
        title="Data Analytics Agent API",
        version="0.5.0",
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
        default_source_id: str | None = None
        ready_count = 0
        try:
            catalog = container.source_catalog()
            default_source_id = catalog.default_source_id
            ready_count = sum(
                summary.ready for summary in container.source_summaries()
            )
            if ready_count == 0:
                errors.append("No configured data source is ready.")
        except Exception as exc:
            message = str(exc)
            if message not in errors:
                errors.append(message)
        if container.agent is not None:
            errors = [
                error
                for error in errors
                if not error.startswith("OPENAI_API_KEY is missing")
            ]
        return HealthResponse(
            status="not_ready" if errors else "ok",
            model=container.settings.model,
            default_source_id=default_source_id,
            ready_source_count=ready_count,
            visualization_enabled=(
                container.settings.enable_data_visualization
            ),
            errors=errors,
        )

    @app.get("/api/data-sources", response_model=DataSourcesResponse)
    async def get_data_sources() -> DataSourcesResponse:
        try:
            catalog = container.source_catalog()
            summaries = container.source_summaries()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        return DataSourcesResponse(
            default_source_id=catalog.default_source_id,
            sources=summaries,
        )

    @app.post(
        "/api/conversations",
        response_model=CreateConversationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        request: CreateConversationRequest | None = None,
    ) -> CreateConversationResponse:
        try:
            catalog = container.source_catalog()
            source_id = (
                request.source_id if request and request.source_id else None
            ) or catalog.default_source_id
            container.require_ready_source(source_id)
        except StoreNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Unknown data source "
                    f"{request.source_id if request else None!r}."
                ),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        return CreateConversationResponse(
            thread_id=container.conversations.create(source_id),
            source_id=source_id,
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
        try:
            container.require_ready_source(conversation.source_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        if conversation.active_run_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A run is already active for this conversation.",
            )
        manager = container.manager()
        run_id = container.runs.create(
            thread_id,
            conversation.source_id,
            request.message.strip(),
        )
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
            command = decisions_to_command(
                run.approval,
                request.decisions,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        try:
            container.runs.claim_approval(run_id, run.approval)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        background_tasks.add_task(
            container.manager().resume,
            run_id,
            command,
        )
        return CreateRunResponse(run_id=run_id, status=RunStatus.RUNNING)

    @app.get("/api/results/{result_id}", response_model=ResultPage)
    async def get_result(
        result_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> ResultPage:
        return container.results.page_unscoped(
            result_id, offset=offset, limit=limit
        )

    return app


app = create_app()
