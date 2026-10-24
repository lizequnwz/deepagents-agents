"""FastAPI application for source-bound conversations, runs, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse
from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from data_analytics_agent.persistence import LocalStorage
import csv
import io
import json
from pydantic_core import to_json
from pathlib import Path
import pyarrow.parquet as pq

from data_analytics_agent.coordinator import build_agent
from data_analytics_agent.backends import SQLBackend, create_backend
from data_analytics_agent.config import Settings
from data_analytics_agent.transcription import (
    MAX_AUDIO_BYTES,
    TranscriptionResponse,
    transcribe_audio,
)
from data_analytics_agent.data_sources import DataSource, DataSourceCatalog
from data_analytics_agent.logging_config import configure_api_logging
from data_analytics_agent.run_manager import RunManager
from data_analytics_agent.workspace_api import workspace_router
from data_analytics_agent.dashboard.store import DashboardStore
from data_analytics_agent.dashboard_api import dashboard_router
from data_analytics_agent.approvals import decisions_to_command
from data_analytics_agent.reporting.schemas import ReportResponse, ReportSpec
from data_analytics_agent.excel import ExcelSelection, inspect_workbook
from data_analytics_agent.uploads import (
    UploadReview,
    UploadSource,
    UploadedFile,
    upload_for_thread,
    stage_upload,
    confirm_upload,
    file_source,
    uploads_for_thread,
)
from data_analytics_agent.documents import (
    Document,
    documents_for_thread,
    get_document,
    stage_document,
    import_document_table,
)
from data_analytics_agent.presentation_edits import (
    ChartPresentationEdit,
    ReportTitleEdit,
    edit_report_title,
    PresentationConflict,
    PresentationRenderError,
    edit_chart_presentation,
)
from data_analytics_agent.schemas import (
    API_CONTRACT_VERSION,
    ConversationResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    CreateRunResponse,
    DataSourceSummary,
    DataSourcesResponse,
    DecisionRequest,
    ExampleQuestionResponse,
    ExecutionLimitsResponse,
    FinalAnswer,
    HealthResponse,
    MessageRequest,
    AnalyticalMessageRequest,
    ClarificationReply,
    SteeringResponse,
    ResultPage,
    RunResponse,
    RunStatus,
)
from data_analytics_agent.semantic import SemanticCatalog, load_semantic_catalog
from data_analytics_agent.stores import (
    ConversationStore,
    ReportStore,
    ResultStore,
    RunStore,
    DataAnalysisStore,
    StoreNotFound,
)

logger = logging.getLogger(__name__)


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
    conversations: ConversationStore | None = None
    runs: RunStore | None = None
    results: ResultStore | None = None
    analyses: DataAnalysisStore | None = None
    reports: ReportStore | None = None
    dashboards: DashboardStore | None = None
    agent: Any | None = None
    catalog: DataSourceCatalog | None = None
    snowflake_client: Any | None = None
    _manager: RunManager | None = None
    _backends: dict[str, SQLBackend] = field(default_factory=dict)
    _agents: dict[tuple[str, str, str], Any] = field(default_factory=dict)
    _semantic_catalogs: dict[str, SemanticCatalog] = field(default_factory=dict)
    _source_summaries: dict[str, DataSourceSummary] | None = None
    _lock: RLock = field(default_factory=RLock)

    storage: LocalStorage | None = None
    checkpointer: Any | None = None
    deleting_conversations: set[str] = field(default_factory=set)
    uploading_conversations: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.storage = self.storage or LocalStorage(self.settings.storage_dir)
        self.conversations = self.conversations or ConversationStore(self.storage)
        self.runs = self.runs or RunStore(self.storage)
        self.results = self.results or ResultStore(
            self.storage,
            max_rows=self.settings.max_result_rows,
            max_bytes=self.settings.max_dataset_bytes,
        )
        self.analyses = self.analyses or DataAnalysisStore(self.storage)
        self.reports = self.reports or ReportStore(self.storage)
        self.dashboards = self.dashboards or DashboardStore(self.storage)
        self.runs.analysis_budget_seconds = self.settings.analysis_budget_seconds
        self.runs.recover()
        self.dashboards.recover(self.runs)
        for conversation in self.conversations.list():
            if (
                conversation.active_run_id
                and self.runs.get(conversation.active_run_id).status == RunStatus.PAUSED
            ):
                self.conversations.fail_run(
                    conversation.thread_id, conversation.active_run_id
                )

    def source_catalog(self) -> DataSourceCatalog:
        with self._lock:
            if self.catalog is None:
                self.catalog = self.settings.load_catalog()
            return self.catalog

    def source(self, source_id: str) -> DataSource | UploadSource:
        if source := file_source(self, source_id):
            return source
        try:
            return self.source_catalog().get(source_id)
        except KeyError as exc:
            raise StoreNotFound(source_id) from exc

    def backend_for_source(self, source_id: str) -> SQLBackend:
        if file_source(self, source_id):
            raise ValueError(
                "Uploaded files have no warehouse backend. Query their saved datasets."
            )
        with self._lock:
            backend = self._backends.get(source_id)
            if backend is None:
                source = self.source(source_id)
                if source.backend_type == "snowflake" and self.snowflake_client is None:
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
                    semantic = load_semantic_catalog(
                        source.semantic_model_path,
                        dialect=source.dialect,
                        backend=backend if not errors else None,
                    )
                    errors.extend(semantic.diagnostics.errors)
                    warnings.extend(semantic.diagnostics.warnings)
                    if semantic.catalog is not None:
                        self._semantic_catalogs[source_id] = semantic.catalog
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
        if source := file_source(self, source_id):
            tables = [
                item
                for item in self.storage.load("uploads", UploadedFile).values()
                if item.source_id == source_id
            ]
            ready = all(item.confirmed for item in tables)
            return DataSourceSummary(
                source_id=source_id,
                name=source.name,
                description=source.description,
                backend_type="upload",
                dialect="duckdb",
                ready=ready,
                errors=[] if ready else ["Review the file schema before analysis."],
                limits=ExecutionLimitsResponse(
                    timeout_seconds=source.limits.timeout_seconds,
                    max_result_rows=source.limits.max_result_rows,
                    model_sample_rows=source.limits.model_sample_rows,
                ),
            )
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

    def semantic_catalog_for_source(self, source_id: str) -> SemanticCatalog:
        if file_source(self, source_id):
            raise ValueError("An uploaded schema is not a curated semantic catalog.")
        self.require_ready_source(source_id)
        try:
            return self._semantic_catalogs[source_id]
        except KeyError as exc:
            raise ValueError(
                f"Semantic catalog for source {source_id!r} is unavailable."
            ) from exc

    def agent_for_source(self, source_id: str) -> Any:
        if self.agent is not None:
            return self.agent
        with self._lock:
            source = self.require_ready_source(source_id)
            is_upload = isinstance(source, UploadSource)
            catalog = None if is_upload else self.semantic_catalog_for_source(source_id)
            key = (source_id, self.source_version(source_id), source.dialect)
            graph = self._agents.get(key)
            if graph is None:
                source = self.require_ready_source(source_id)
                graph = build_agent(
                    self.settings,
                    self.results,
                    self.runs,
                    analysis_store=self.analyses,
                    report_store=self.reports,
                    conversation_store=self.conversations,
                    dashboard_store=self.dashboards,
                    checkpointer=self.checkpointer,
                    source=source,
                    semantic_catalog=catalog,
                    backend=None if is_upload else self.backend_for_source(source_id),
                )
                self._agents[key] = graph
            return graph

    def source_version(self, source_id):
        if file_source(self, source_id):
            import hashlib

            tables = [
                item.model_dump(mode="json")
                for item in self.storage.load("uploads", UploadedFile).values()
                if item.source_id == source_id
            ]
            docs = [
                doc.reference()
                for doc in self.storage.load("documents", Document).values()
                if doc.source_id == source_id
            ]
            return hashlib.sha256(
                json.dumps(
                    {"tables": tables, "documents": docs}, sort_keys=True
                ).encode()
            ).hexdigest()
        return self.semantic_catalog_for_source(source_id).content_hash

    def manager(self) -> RunManager:
        with self._lock:
            if self._manager is None:
                self._manager = RunManager(
                    agent_resolver=self.agent_for_source,
                    source_resolver=self.source,
                    catalog_version_resolver=self.source_version,
                    conversations=self.conversations,
                    runs=self.runs,
                    results=self.results,
                    analyses=self.analyses,
                    reports=self.reports,
                    dashboards=self.dashboards,
                    python_execution_limits=(self.settings.python_execution_limits()),
                    presentation_budget_seconds=self.settings.presentation_budget_seconds,
                )
            return self._manager


def create_app(services: Services | None = None) -> FastAPI:
    container = services or Services()
    log_path = configure_api_logging(container.settings.project_root)

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncSqliteSaver.from_conn_string(
            str(container.storage.root / "checkpoints.sqlite")
        ) as checkpointer:
            await checkpointer.setup()
            container.checkpointer = checkpointer
            yield
            if container._manager:
                import asyncio

                tasks = list(container._manager.tasks.items())
                for run_id, task in tasks:
                    await container._manager.stop(run_id)
                if tasks:
                    await asyncio.gather(
                        *(task for _, task in tasks), return_exceptions=True
                    )
            container._agents.clear()
            container.checkpointer = None

    app = FastAPI(
        lifespan=lifespan,
        title="Data Analytics Agent API",
        version="0.8.0",
    )
    app.state.services = container
    logger.info("api.configured log_file=%s", log_path)

    @app.exception_handler(StoreNotFound)
    async def not_found_handler(_request, _exc):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Resource not found."},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        errors = container.settings.readiness_errors(include_sources=False)
        source_errors = []
        default_source_id: str | None = None
        ready_count = 0
        try:
            catalog = container.source_catalog()
            default_source_id = catalog.default_source_id
            ready_count = sum(summary.ready for summary in container.source_summaries())
            if ready_count == 0:
                source_errors.append(
                    "No configured warehouse source is ready. You can upload a file."
                )
        except Exception as exc:
            message = str(exc)
            source_errors.append(message)
        if container.agent is not None:
            errors = [
                error
                for error in errors
                if not error.startswith("OPENAI_API_KEY is missing")
            ]
        return HealthResponse(
            status="not_ready" if errors else "ok",
            model=container.settings.model,
            api_contract_version=API_CONTRACT_VERSION,
            default_source_id=default_source_id,
            ready_source_count=ready_count,
            upload_max_bytes=container.settings.upload_max_bytes,
            source_errors=source_errors,
            sql_approval_required=(container.settings.require_sql_approval),
            python_approval_required=(container.settings.require_python_approval),
            visualization_enabled=(container.settings.enable_data_visualization),
            data_analysis_enabled=(container.settings.enable_data_analysis),
            reporting_enabled=True,
            errors=errors,
        )

    @app.get("/api/evaluation-context")
    async def get_evaluation_context(source_id: list[str] = Query(default=[])):
        from data_analytics_agent.evaluation import evaluation_context

        catalog = container.source_catalog() if source_id else None
        if catalog and any(name not in catalog.sources for name in source_id):
            raise HTTPException(422, "Unknown evaluation source.")
        return await run_in_threadpool(
            evaluation_context, container.settings, catalog, source_id
        )

    @app.post("/api/transcriptions", response_model=TranscriptionResponse)
    async def transcribe(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_AUDIO_BYTES:
                raise HTTPException(
                    413, "Recording is too large. Record a shorter question."
                )
            content.extend(chunk)
        return await transcribe_audio(
            bytes(content), container.settings.transcription_model
        )

    @app.get("/api/data-sources", response_model=DataSourcesResponse)
    async def get_data_sources() -> DataSourcesResponse:
        try:
            catalog = container.source_catalog()
            summaries = container.source_summaries()
        except Exception as exc:
            return DataSourcesResponse(
                default_source_id=None, sources=[], errors=[str(exc)]
            )
        return DataSourcesResponse(
            default_source_id=catalog.default_source_id,
            sources=summaries,
        )

    def upload_response(upload):
        result = container.results.get(
            upload.result_id, upload.thread_id, source_id=upload.source_id
        )
        return {
            **upload.model_dump(mode="json", exclude={"original_path"}),
            "sample_rows": json.loads(
                to_json(result.preview[:10], inf_nan_mode="null")
            ),
            "imported_at": container.results.get(
                upload.original_result_id, upload.thread_id, source_id=upload.source_id
            ).created_at,
            "source_freshness": None,
        }

    async def upload_bytes(request):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > container.settings.upload_max_bytes:
                raise HTTPException(413, "File exceeds UPLOAD_MAX_BYTES.")
            content.extend(chunk)
        return bytes(content)

    @app.post("/api/uploads/workbook")
    async def workbook_info(request: Request):
        try:
            return await run_in_threadpool(
                inspect_workbook, await upload_bytes(request), container.settings
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/uploads", status_code=201)
    async def upload_file(
        request: Request,
        filename: str = Query(min_length=1, max_length=255),
        sheet: str | None = Query(default=None, max_length=200),
        cell_range: str | None = Query(default=None, max_length=40),
        use_cached_formulas: bool = False,
        thread_id: str | None = Query(default=None),
    ):
        content = await upload_bytes(request)
        try:
            upload = await run_in_threadpool(
                stage_upload,
                container,
                content,
                filename,
                ExcelSelection(
                    sheet=sheet,
                    cell_range=cell_range,
                    use_cached_formulas=use_cached_formulas,
                )
                if sheet and cell_range
                else None,
                thread_id,
            )
            return upload_response(upload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/conversations/{thread_id}/source", response_model=DataSourceSummary)
    async def conversation_source(thread_id: str):
        source_id = container.conversations.get(thread_id).source_id
        try:
            return container.source_summary(source_id)
        except StoreNotFound:
            raise
        except Exception as exc:
            raise HTTPException(
                503, f"Saved source configuration is unavailable: {exc}"
            ) from exc

    @app.get("/api/conversations/{thread_id}/uploads/{upload_id}")
    async def uploaded_file(thread_id: str, upload_id: str):
        return upload_response(upload_for_thread(container, thread_id, upload_id))

    @app.get("/api/conversations/{thread_id}/uploads")
    async def uploaded_tables(thread_id: str):
        return {
            "uploads": [
                upload_response(item)
                for item in uploads_for_thread(container, thread_id)
            ]
        }

    @app.post("/api/conversations/{thread_id}/uploads/{upload_id}/confirm")
    async def review_upload(thread_id: str, upload_id: str, review: UploadReview):
        with container._lock:
            ensure_not_deleting(thread_id)
            if thread_id in container.uploading_conversations:
                raise HTTPException(
                    409, "File import or schema review is already in progress."
                )
            container.uploading_conversations.add(thread_id)
        try:
            return upload_response(
                await run_in_threadpool(
                    confirm_upload, container, thread_id, review, upload_id
                )
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            with container._lock:
                container.uploading_conversations.discard(thread_id)

    @app.post("/api/documents", status_code=201)
    async def upload_document(
        request: Request,
        filename: str = Query(min_length=1, max_length=255),
        thread_id: str | None = None,
    ):
        try:
            doc = await run_in_threadpool(
                stage_document,
                container,
                await upload_bytes(request),
                filename,
                thread_id,
            )
            return doc.reference()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/conversations/{thread_id}/documents")
    async def list_document_files(thread_id: str):
        source_id = container.conversations.get(thread_id).source_id
        return {
            "documents": [
                doc.reference()
                for doc in documents_for_thread(container.storage, thread_id, source_id)
            ]
        }

    @app.get("/api/conversations/{thread_id}/documents/{document_id}")
    async def inspect_document(
        thread_id: str, document_id: str, page: int = Query(default=1, ge=1)
    ):
        source_id = container.conversations.get(thread_id).source_id
        doc = get_document(container.storage, document_id, thread_id, source_id)
        if page > doc.page_count:
            raise HTTPException(422, "Choose an existing page.")
        payload = json.loads(Path(doc.extracted_path).read_text())
        return {
            **doc.reference(),
            "page": page,
            "text": payload["pages"][page - 1]["text"][:20000],
            "tables": [
                {
                    "table_index": i,
                    "page": table["page"],
                    "row_count": len(table["rows"]),
                    "preview": table["rows"][:10],
                }
                for i, table in enumerate(payload["tables"])
                if table["page"] == page
            ],
        }

    @app.post(
        "/api/conversations/{thread_id}/documents/{document_id}/tables", status_code=201
    )
    async def import_document_rows(
        thread_id: str,
        document_id: str,
        table_index: int = Query(ge=0),
        header_row: int = Query(default=0, ge=0),
    ):
        source_id = container.conversations.get(thread_id).source_id
        doc = get_document(container.storage, document_id, thread_id, source_id)
        try:
            return upload_response(
                await run_in_threadpool(
                    import_document_table, container, doc, table_index, header_row
                )
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/conversations/{thread_id}/documents/{document_id}/download")
    async def download_document(thread_id: str, document_id: str):
        source_id = container.conversations.get(thread_id).source_id
        doc = get_document(container.storage, document_id, thread_id, source_id)
        return FileResponse(doc.original_path, filename=doc.filename)

    @app.post(
        "/api/conversations",
        response_model=CreateConversationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        request: CreateConversationRequest | None = None,
    ) -> CreateConversationResponse:
        if (
            request
            and request.source_id
            and request.source_id.startswith(("upload:", "documents:"))
        ):
            raise HTTPException(
                422,
                "Each upload belongs to its original conversation. Upload a file to start another.",
            )
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
                    f"Unknown data source {request.source_id if request else None!r}."
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
        conversation = container.conversations.get(thread_id)
        return conversation.model_copy(
            update={
                "diagnostics": container.runs.conversation_diagnostics(
                    conversation.run_ids
                )
            }
        )

    @app.post(
        "/api/conversations/{thread_id}/messages",
        response_model=CreateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def post_message(
        thread_id: str,
        request: AnalyticalMessageRequest,
        background_tasks: BackgroundTasks,
    ) -> CreateRunResponse:
        readiness_errors = container.settings.readiness_errors(include_sources=False)
        if readiness_errors and container.agent is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=" ".join(readiness_errors),
            )
        ensure_not_deleting(thread_id)
        with container._lock:
            if thread_id in container.uploading_conversations:
                raise HTTPException(
                    409,
                    "Wait for file import or schema review before starting analysis.",
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
        if not request.message.strip():
            raise HTTPException(422, "Question cannot be blank.")
        if request.previous_report_id:
            require_current_report(conversation, request.previous_report_id)

        def dashboard_context():
            if request.dashboard_id is None:
                return None
            revision = container.dashboards.get(
                request.dashboard_id, thread_id, source_id=conversation.source_id
            )
            if revision.revision_id != request.dashboard_revision:
                raise HTTPException(
                    409,
                    "The displayed dashboard changed. Reload before asking a follow-up.",
                )
            return {
                "dashboard_id": revision.dashboard_id,
                "revision_id": revision.revision_id,
                "original_question": revision.question,
                "spec": revision.spec.model_dump(mode="json"),
                "applied_filters": revision.applied_filters,
            }

        manager = container.manager()
        with container._lock:
            ensure_not_deleting(thread_id)
            if thread_id in container.uploading_conversations:
                raise HTTPException(
                    409,
                    "Wait for file import or schema review before starting analysis.",
                )
            latest = container.conversations.get(thread_id)
            if latest.active_run_id:
                raise HTTPException(
                    409, "A run is already active for this conversation."
                )
            try:
                container.require_ready_source(conversation.source_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            context = dashboard_context()
            run_id = container.runs.create(
                thread_id,
                conversation.source_id,
                request.message.strip(),
                model=container.settings.model,
                previous_report_id=request.previous_report_id,
            )
            if context is not None:
                container.storage.put(
                    "workspace_run_context",
                    run_id,
                    {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "source_id": conversation.source_id,
                        "context": context,
                    },
                )
            if request.dashboard:
                container.storage.put(
                    "dashboard_requests",
                    run_id,
                    {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "source_id": conversation.source_id,
                    },
                )
            container.conversations.begin_run(thread_id, run_id)
        background_tasks.add_task(manager.start, run_id)
        return CreateRunResponse(run_id=run_id, status=RunStatus.QUEUED)

    def require_current_report(conversation, report_id):
        if (
            not conversation.turns
            or not conversation.turns[-1].answer.report
            or conversation.turns[-1].answer.report.report_id != report_id
        ):
            raise HTTPException(
                409,
                "The displayed report is stale. Reload before revising it.",
            )

    @app.get("/api/conversations/{thread_id}/datasets")
    async def conversation_datasets(thread_id: str):
        conversation = container.conversations.get(thread_id)
        items = container.results.list_for_conversation(
            thread_id, source_id=conversation.source_id
        )
        return {
            "datasets": [
                {
                    "result_id": item.result_id,
                    "label": item.short_label,
                    "row_count": item.row_count,
                    "columns": item.columns,
                    "kind": item.kind,
                    "complete": not item.truncated,
                    "snapshot_at": item.created_at.isoformat(),
                    "grain": item.upload_provenance.grain
                    if item.upload_provenance and item.upload_provenance.grain
                    else "Business grain must be checked against the saved question and calculation.",
                    "question": item.originating_question,
                    "parent_result_ids": item.parent_result_ids,
                }
                for item in reversed(items)
            ]
        }

    @app.post(
        "/api/runs/{run_id}/corrections",
        response_model=SteeringResponse,
        status_code=202,
    )
    async def post_correction(
        run_id: str, request: MessageRequest, background_tasks: BackgroundTasks
    ):
        from data_analytics_agent.schemas import Decision

        run = container.runs.get(run_id)
        ensure_not_deleting(run.thread_id)
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="Correction cannot be blank.")
        # The run-store lock serializes acceptance with publication/completion.
        dashboard_action = container.dashboards.action_for_run(run_id)
        correction = (
            None
            if dashboard_action is not None
            else container.runs.accept_correction(run_id, message)
        )
        if correction is None:
            follow_up = container.runs.create(
                run.thread_id, run.source_id, message, model=container.settings.model
            )
            owner = container.conversations.get(run.thread_id).active_run_id or run_id
            container.runs.add_follow_up(owner, follow_up)
            container.conversations.queue_run(run.thread_id, follow_up)
            if dashboard_action is not None:
                container.storage.put(
                    "workspace_run_context",
                    follow_up,
                    {
                        "run_id": follow_up,
                        "thread_id": run.thread_id,
                        "source_id": run.source_id,
                        "dashboard_id": dashboard_action.dashboard_id,
                    },
                )
            if container.conversations.get(run.thread_id).active_run_id is None:
                container.conversations.begin_run(run.thread_id, follow_up)
                background_tasks.add_task(container.manager().start, follow_up)
            return SteeringResponse(
                run_id=follow_up,
                message_id=follow_up,
                disposition="follow_up",
                message=(
                    "Saved as a follow-up. The current dashboard action keeps its declared filters."
                    if dashboard_action is not None
                    else "Accepted as a follow-up turn; published findings are preserved."
                ),
            )
        # A changed request invalidates the old proposal rather than approving it.
        current = container.runs.get(run_id)
        if current.status == RunStatus.APPROVAL_REQUIRED and current.approval:
            command = decisions_to_command(
                current.approval,
                [
                    Decision(
                        action="reject",
                        feedback="User corrected the request: " + message,
                    )
                    for _ in current.approval.actions
                ],
            )
            container.runs.claim_approval(run_id, current.approval)
            background_tasks.add_task(container.manager().resume, run_id, command)
        return SteeringResponse(
            run_id=run_id,
            message_id=correction.message_id,
            disposition="pending",
            message="Received; applying after the current step.",
        )

    @app.post(
        "/api/runs/{run_id}/clarification",
        response_model=CreateRunResponse,
        status_code=202,
    )
    async def answer_clarification(
        run_id: str, request: ClarificationReply, background_tasks: BackgroundTasks
    ):
        from langgraph.types import Command

        run = container.runs.get(run_id)
        ensure_not_deleting(run.thread_id)
        if run.status != RunStatus.CLARIFICATION_REQUIRED or run.clarification is None:
            raise HTTPException(
                status_code=409, detail="This run is not awaiting clarification."
            )
        if not request.message.strip():
            raise HTTPException(status_code=422, detail="Answer cannot be blank.")
        if (
            request.interrupt_id is not None
            and request.interrupt_id != run.clarification.interrupt_id
        ):
            raise HTTPException(
                409, "This clarification has changed. Reload before answering."
            )
        container.runs.accept_correction(run_id, request.message)
        container.runs.resume(run_id)
        background_tasks.add_task(
            container.manager().resume,
            run_id,
            Command(resume={run.clarification.interrupt_id: request.message}),
        )
        return CreateRunResponse(run_id=run_id, status=RunStatus.RUNNING)

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    async def get_run(
        run_id: str,
        after_event_id: int = Query(default=0, ge=0),
    ) -> RunResponse:
        return container.runs.get(run_id, after_event_id=after_event_id)

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
        ensure_not_deleting(run.thread_id)
        if run.status != RunStatus.APPROVAL_REQUIRED or run.approval is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This run is not awaiting a decision.",
            )
        if request.interrupt_id != run.approval.interrupt_id:
            raise HTTPException(
                409, "This review has changed. Refresh before deciding."
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
            approval_wait_ms = container.runs.claim_approval(run_id, run.approval)
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
        logger.info(
            "run.resumed run_id=%s thread_id=%s approval_wait_ms=%d",
            run_id,
            run.thread_id,
            approval_wait_ms,
        )
        return CreateRunResponse(run_id=run_id, status=RunStatus.RUNNING)

    @app.get("/api/results/{result_id}", response_model=ResultPage)
    async def get_result(
        result_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> ResultPage:
        return container.results.page_unscoped(result_id, offset=offset, limit=limit)

    @app.get("/api/results/{result_id}/python-source")
    async def get_dataset_python_source(result_id: str):
        result = container.results.get_unscoped(result_id)
        return container.runs.dataset_python_source(result)

    def ensure_not_deleting(thread_id):
        if thread_id in container.deleting_conversations:
            raise HTTPException(409, "This conversation is being deleted.")

    @app.delete("/api/conversations/{thread_id}")
    async def delete_conversation(thread_id: str):
        from data_analytics_agent.history import delete_history

        return await delete_history(container, {thread_id})

    @app.delete("/api/conversations")
    async def clear_history():
        from data_analytics_agent.history import delete_history

        return await delete_history(
            container, {item.thread_id for item in container.conversations.list()}
        )

    @app.get("/api/conversations")
    async def list_conversations():
        def title_for(item):
            if item.turns:
                return item.turns[0].user_message
            if item.run_ids:
                return container.runs.get(item.run_ids[0]).question
            tables = uploads_for_thread(container, item.thread_id)
            if tables:
                return tables[0].filename
            documents = documents_for_thread(
                container.storage, item.thread_id, item.source_id
            )
            return documents[0].filename if documents else "New conversation"

        return [
            {
                "thread_id": item.thread_id,
                "source_id": item.source_id,
                "title": title_for(item)[:100],
                "active_run_id": item.active_run_id,
                "run_ids": item.run_ids,
            }
            for item in container.conversations.list()
        ]

    @app.post("/api/runs/{run_id}/stop")
    async def stop_run(run_id: str):
        run = container.runs.get(run_id)
        if run.status not in {
            RunStatus.RUNNING,
            RunStatus.QUEUED,
            RunStatus.APPROVAL_REQUIRED,
            RunStatus.CLARIFICATION_REQUIRED,
        }:
            raise HTTPException(409, "Run is not active.")
        await container.manager().stop(run_id)
        return container.runs.get(run_id)

    def claim_saved_run(run_id):
        with container._lock:
            run = container.runs.get(run_id)
            ensure_not_deleting(run.thread_id)
            if run.thread_id in container.uploading_conversations:
                raise HTTPException(
                    409, "Wait for file import or schema review before resuming work."
                )
            if not run.findings and any(
                not item.confirmed
                for item in uploads_for_thread(container, run.thread_id)
            ):
                raise HTTPException(
                    409, "Confirm the pending table before resuming analysis."
                )
            if run.status not in {RunStatus.PAUSED, RunStatus.FAILED}:
                raise HTTPException(409, "Run is not resumable.")
            task = container.manager().tasks.get(run_id)
            if container.runs.workers_active(run_id) or (task and not task.done()):
                raise HTTPException(
                    409,
                    "The previous attempt is still stopping. Retry after it finishes.",
                )
            try:
                container.conversations.begin_run(run.thread_id, run_id)
            except RuntimeError as exc:
                raise HTTPException(409, str(exc)) from exc
            container.runs.set_status(run_id, RunStatus.QUEUED)
            return run

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume_run(run_id: str, background_tasks: BackgroundTasks):
        run = claim_saved_run(run_id)
        manager = container.manager()
        background_tasks.add_task(
            manager.retry_report if run.findings else manager.resume, run_id
        )
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/runs/{run_id}/retry-report", status_code=202)
    async def retry_report(run_id: str, background_tasks: BackgroundTasks):
        if not container.runs.get(run_id).findings:
            raise HTTPException(409, "There are no saved findings.")
        claim_saved_run(run_id)
        background_tasks.add_task(container.manager().retry_report, run_id)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/runs/{run_id}/download")
    async def download_analysis(run_id: str, report_id: str):
        from tempfile import TemporaryDirectory
        from starlette.background import BackgroundTask
        from data_analytics_agent.exports import write_bundle, ExportConflict

        temporary = TemporaryDirectory(prefix="analysis-export-")
        target = Path(temporary.name) / "analysis.zip"

        def build():
            with container._lock:
                run = container.runs.get(run_id)
                ensure_not_deleting(run.thread_id)
                write_bundle(container, run_id, report_id, target)

        try:
            await run_in_threadpool(build)
        except ExportConflict as exc:
            temporary.cleanup()
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            temporary.cleanup()
            raise HTTPException(422, str(exc)) from exc
        except BaseException:
            temporary.cleanup()
            raise
        return FileResponse(
            target,
            filename=f"analysis-{run_id[:8]}.zip",
            media_type="application/zip",
            background=BackgroundTask(temporary.cleanup),
        )

    @app.get("/api/results/{result_id}/download")
    async def download_dataset(result_id: str, format: str = "csv"):
        result = container.results.get_unscoped(result_id)
        if format == "parquet":
            return FileResponse(
                result.parquet_path,
                filename=f"{result_id}.parquet",
                media_type="application/octet-stream",
            )
        if format != "csv":
            raise HTTPException(422, "Use csv or parquet.")

        def chunks():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(result.columns)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            for batch in pq.ParquetFile(result.parquet_path).iter_batches(
                batch_size=2048
            ):
                for row in batch.to_pylist():
                    writer.writerow([row.get(column) for column in result.columns])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        return StreamingResponse(
            chunks(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{result_id}.csv"'},
        )

    @app.get("/api/figures/{filename}")
    async def get_figure(filename: str):
        if Path(filename).name != filename or not filename.endswith(".png"):
            raise HTTPException(404)
        path = container.storage.artifacts / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    @app.get("/api/reports/{report_id}", response_model=ReportResponse)
    async def get_report(report_id: str) -> ReportResponse:
        return container.reports.response_unscoped(report_id)

    @app.get("/api/reports/{report_id}/spec", response_model=ReportSpec)
    async def get_report_spec(report_id: str) -> ReportSpec:
        return container.reports.get_unscoped(report_id).spec

    @app.post("/api/runs/{run_id}/presentation", response_model=FinalAnswer)
    async def edit_presentation(
        run_id: str, request: ChartPresentationEdit
    ) -> FinalAnswer:
        run = container.runs.get(run_id)
        ensure_not_deleting(run.thread_id)
        try:
            with container._lock:
                return edit_chart_presentation(container, run_id, request)
        except PresentationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except PresentationRenderError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/runs/{run_id}/report-title", response_model=FinalAnswer)
    async def update_report_title(run_id: str, request: ReportTitleEdit) -> FinalAnswer:
        run = container.runs.get(run_id)
        ensure_not_deleting(run.thread_id)
        try:
            with container._lock:
                return edit_report_title(container, run_id, request)
        except PresentationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except PresentationRenderError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/reports/{report_id}/view")
    async def view_report(report_id: str) -> Response:
        report = container.reports.get_unscoped(report_id)
        return Response(
            content=report.html.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'inline; filename="report-{report.report_id[:8]}-'
                    f'v{report.version}.html"'
                ),
                "ETag": f'"{report.html_sha256}"',
            },
        )

    @app.get("/api/reports/{report_id}/download")
    async def download_report(report_id: str) -> Response:
        report = container.reports.get_unscoped(report_id)
        return Response(
            content=report.html.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="report-{report.report_id[:8]}-'
                    f'v{report.version}.html"'
                ),
                "ETag": f'"{report.html_sha256}"',
            },
        )

    app.include_router(dashboard_router(container))
    app.include_router(workspace_router(container))
    return app


app = create_app()
