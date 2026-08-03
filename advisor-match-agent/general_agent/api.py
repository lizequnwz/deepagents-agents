"""Loopback-only FastAPI service for Advisor Match Agent."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from general_agent.agent import build_agent
from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource
from general_agent.config import Settings, load_settings
from general_agent.observability import (
    configure_logging,
    log_event,
    reset_request_id,
    set_request_id,
    shutdown_logging,
)
from general_agent.run_manager import RunManager
from general_agent.schemas import (
    Conversation,
    ConversationCreate,
    ConversationRename,
    ConversationSummary,
    Run,
    RunStatus,
)
from general_agent.store import ActiveRunError, Store
from general_agent.workspace import Workspace, WorkspacePathError, validate_corp_id

logger = logging.getLogger("general_agent.api")

def create_app(
    *,
    settings: Settings | None = None,
    graph_override: Any | None = None,
) -> FastAPI:
    configured_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if configured_settings is None:
            active_settings = load_settings()
        else:
            active_settings = configured_settings
            errors = active_settings.readiness_errors(require_model=False)
            if errors:
                raise ValueError(" ".join(errors))
            active_settings.prepare_directories()
        log_path = configure_logging(active_settings)
        log_event(
            logger,
            logging.INFO,
            "api.service.starting",
            host=active_settings.api_host,
            port=active_settings.api_port,
            model=active_settings.model_name,
            log_file=log_path,
        )
        try:
            workspace = Workspace(active_settings.data_root)
            store = Store(
                active_settings.application_db,
                active_settings.data_root,
                active_settings.default_corp_id,
            )
            backend = AdvisorWorkspaceBackend(active_settings.runtime_root)
            advisor_source = SyntheticAdvisorReferenceSource(
                active_settings.project_root
                / "general_agent/advisor_matching/data/master_advisors.csv"
            )
            _migrate_checkpoint_threads(
                active_settings.checkpoint_db, active_settings.default_corp_id
            )
            checkpoint_context = AsyncSqliteSaver.from_conn_string(
                str(active_settings.checkpoint_db)
            )
            checkpointer = await checkpoint_context.__aenter__()
            await checkpointer.setup()
            graph = graph_override or build_agent(
                active_settings,
                workspace=workspace,
                backend=backend,
                store=store,
                advisor_source=advisor_source,
                checkpointer=checkpointer,
            )
            manager = RunManager(
                settings=active_settings,
                store=store,
                workspace=workspace,
                backend=backend,
                graph=graph,
            )
            app.state.settings = active_settings
            app.state.workspace = workspace
            app.state.store = store
            app.state.backend = backend
            app.state.checkpointer = checkpointer
            app.state.manager = manager
        except Exception:
            log_event(
                logger,
                logging.ERROR,
                "api.service.startup_failed",
                exception_type=_current_exception_type(),
                exc_info=True,
            )
            shutdown_logging()
            raise
        log_event(logger, logging.INFO, "api.service.ready")
        try:
            yield
        finally:
            log_event(
                logger,
                logging.INFO,
                "api.service.stopping",
                active_runs=manager.active_run_count,
            )
            try:
                await manager.shutdown()
                store.close()
                await checkpoint_context.__aexit__(None, None, None)
                log_event(logger, logging.INFO, "api.service.stopped")
            except Exception:
                log_event(
                    logger,
                    logging.ERROR,
                    "api.service.shutdown_failed",
                    exception_type=_current_exception_type(),
                    exc_info=True,
                )
                raise
            finally:
                shutdown_logging()

    app = FastAPI(
        title="Advisor Match Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def operational_request_log(request: Request, call_next):
        request_id = "req_" + uuid.uuid4().hex[:16]
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started_at = time.monotonic()
        response = None
        logged_failure = False
        try:
            response = await call_next(request)
        except Exception:
            logged_failure = True
            duration_ms = int((time.monotonic() - started_at) * 1000)
            route = _request_route(request)
            log_event(
                logger,
                logging.ERROR,
                "api.request.failed",
                method=request.method,
                route=route,
                status=500,
                duration_ms=duration_ms,
                corp_id=getattr(request.state, "corp_id", "unresolved"),
                exception_type=_current_exception_type(),
                exc_info=True,
            )
            response = _http_error(500, "The API encountered an unexpected error.")
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = request_id
        if not logged_failure:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            level = _request_log_level(
                request.method, _request_route(request), response.status_code
            )
            log_event(
                logger,
                level,
                "api.request.completed",
                request_id=request_id,
                method=request.method,
                route=_request_route(request),
                status=response.status_code,
                duration_ms=duration_ms,
                corp_id=getattr(request.state, "corp_id", "unresolved"),
            )
        return response

    @app.exception_handler(WorkspacePathError)
    async def workspace_error(_request: Request, exc: WorkspacePathError):
        return _http_error(400, str(exc))

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        corp_id = _request_corp(request)
        active: list[str] = []
        for summary in request.app.state.store.list_conversations(corp_id):
            if summary.active_run_id:
                active.append(summary.active_run_id)
        settings = request.app.state.settings
        return {
            "status": "ok",
            "version": "0.1.0",
            "model": settings.model_name,
            "trusted_host_execution": False,
            "active_run_id": active[0] if active else None,
            "max_upload_mb": settings.max_upload_mb,
            "max_run_tokens": settings.max_run_tokens,
        }

    @app.post("/conversations", response_model=ConversationSummary)
    async def create_conversation(request: Request, body: ConversationCreate) -> ConversationSummary:
        corp_id = _request_corp(request)
        conversation = request.app.state.store.create_conversation(
            body.title, corp_id=corp_id
        )
        log_event(
            logger,
            logging.INFO,
            "api.conversation.created",
            conversation_id=conversation.conversation_id,
            corp_id=corp_id,
        )
        return conversation

    @app.get("/conversations", response_model=list[ConversationSummary])
    async def list_conversations(request: Request) -> list[ConversationSummary]:
        return request.app.state.store.list_conversations(_request_corp(request))

    @app.get("/conversations/{conversation_id}", response_model=Conversation)
    async def get_conversation(request: Request, conversation_id: str) -> Conversation:
        corp_id = _request_corp(request)
        try:
            return request.app.state.store.get_conversation(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc

    @app.patch("/conversations/{conversation_id}", status_code=204)
    async def rename_conversation(
        request: Request, conversation_id: str, body: ConversationRename
    ) -> None:
        corp_id = _request_corp(request)
        try:
            request.app.state.store.rename_conversation(
                conversation_id, body.title, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc

    @app.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(request: Request, conversation_id: str) -> None:
        corp_id = _request_corp(request)
        try:
            run_ids = request.app.state.store.delete_conversation(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc
        except ActiveRunError as exc:
            raise HTTPException(409, str(exc)) from exc
        for run_id in run_ids:
            with contextlib.suppress(Exception):
                await request.app.state.checkpointer.adelete_thread(
                    f"{corp_id}:{run_id}"
                )
        log_event(
            logger,
            logging.INFO,
            "api.conversation.deleted",
            conversation_id=conversation_id,
            corp_id=corp_id,
            runs=len(run_ids),
        )

    @app.post("/conversations/{conversation_id}/messages", response_model=Run)
    async def send_message(
        request: Request,
        conversation_id: str,
        text: Annotated[str, Form()] = "",
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> Run:
        corp_id = _request_corp(request)
        files = files or []
        settings = request.app.state.settings
        if not text.strip() and not files:
            raise HTTPException(400, "A message or at least one file is required.")
        if len(files) > 1:
            raise HTTPException(400, "Attach at most one advisor CSV or XLSX file.")
        for upload in files:
            if Path(upload.filename or "").suffix.lower() not in {".csv", ".xlsx"}:
                raise HTTPException(400, "Advisor matching accepts only CSV or XLSX attachments.")
        manager: RunManager = request.app.state.manager
        try:
            run_id = manager.create_run(
                corp_id,
                conversation_id,
                text.strip() or "Match the advisors in the attached file.",
            )
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc
        except ActiveRunError as exc:
            raise HTTPException(409, str(exc)) from exc
        attachments = []
        try:
            for upload in files:
                attachment = manager.add_upload(
                    run_id,
                    corp_id,
                    conversation_id,
                    original_name=upload.filename or "upload",
                    content_type=upload.content_type,
                    source=upload.file,
                )
                attachments.append(attachment)
        except (ValueError, WorkspacePathError) as exc:
            request.app.state.store.finish_run(
                run_id, RunStatus.FAILED, error=str(exc), corp_id=corp_id
            )
            raise HTTPException(400, str(exc)) from exc
        finally:
            for upload in files:
                await upload.close()
        manager.start(run_id, corp_id, attachments)
        return request.app.state.store.get_run(run_id, corp_id=corp_id)

    @app.get("/runs/{run_id}", response_model=Run)
    async def get_run(
        request: Request,
        run_id: str,
        after_event_id: Annotated[int, Query(ge=0)] = 0,
    ) -> Run:
        corp_id = _request_corp(request)
        try:
            return request.app.state.store.get_run(
                run_id, after_event_id=after_event_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Run not found.") from exc

    @app.post("/runs/{run_id}/stop", response_model=Run)
    async def stop_run(request: Request, run_id: str) -> Run:
        corp_id = _request_corp(request)
        try:
            changed = await request.app.state.manager.stop(run_id, corp_id)
            run = request.app.state.store.get_run(run_id, corp_id=corp_id)
        except KeyError as exc:
            raise HTTPException(404, "Run not found.") from exc
        if not changed and run.status not in {RunStatus.STOPPING, RunStatus.STOPPED}:
            raise HTTPException(409, "The run is no longer active.")
        return run

    @app.get("/attachments/{attachment_id}/download")
    async def download_attachment(request: Request, attachment_id: str) -> FileResponse:
        corp_id = _request_corp(request)
        try:
            path, name, _sha256 = request.app.state.store.attachment_path(
                attachment_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Attachment not found.") from exc
        request.app.state.workspace.validate_file(corp_id, "attachments", path)
        log_event(
            logger,
            logging.INFO,
            "api.attachment.download_ready",
            attachment_id=attachment_id,
            corp_id=corp_id,
        )
        return FileResponse(path, filename=name)

    @app.get("/artifacts/{artifact_id}/download")
    async def download_artifact(request: Request, artifact_id: str) -> FileResponse:
        corp_id = _request_corp(request)
        try:
            path, name = request.app.state.store.artifact_path(
                artifact_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Artifact not found.") from exc
        request.app.state.workspace.validate_file(corp_id, "artifacts", path)
        log_event(
            logger,
            logging.INFO,
            "api.artifact.download_ready",
            artifact_id=artifact_id,
            corp_id=corp_id,
        )
        return FileResponse(path, filename=name)

    return app


def _http_error(status: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content={"detail": detail})


def _request_corp(request: Request) -> str:
    """Resolve the lightweight user namespace supplied by the Streamlit UI."""

    configured_default = request.app.state.settings.default_corp_id
    corp_id = validate_corp_id(
        request.headers.get("X-Corp-ID") or configured_default
    )
    request.state.corp_id = corp_id
    return corp_id


def _request_route(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def _request_log_level(method: str, route: str, status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    if method == "GET" and route in {"/health", "/runs/{run_id}"}:
        return logging.DEBUG
    return logging.INFO


def _current_exception_type() -> str:
    import sys

    exception = sys.exc_info()[1]
    return type(exception).__name__ if exception is not None else "Exception"


def _migrate_checkpoint_threads(path: Path, default_corp_id: str) -> None:
    """Assign pre-corp checkpoint threads to the configured default user."""

    if not path.exists():
        return
    prefix = validate_corp_id(default_corp_id) + ":"
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in ("checkpoints", "writes"):
            if table in tables:
                connection.execute(
                    f"UPDATE {table} SET thread_id=? || thread_id "
                    "WHERE instr(thread_id, ':')=0",
                    (prefix,),
                )
app = create_app()
