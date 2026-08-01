"""Loopback-only FastAPI service for the trusted local General Agent."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from general_agent.agent import build_agent
from general_agent.config import Settings, load_settings
from general_agent.execution import CancellableLocalShellBackend
from general_agent.file_inspector import inspect_path
from general_agent.run_manager import RunManager
from general_agent.schemas import (
    Conversation,
    ConversationCreate,
    ConversationRename,
    ConversationSummary,
    RenameRequest,
    Run,
    RunStatus,
    WorkspaceEntry,
)
from general_agent.store import ActiveRunError, Store
from general_agent.workspace import Workspace, WorkspacePathError, validate_corp_id

logger = logging.getLogger("general_agent.api")

SUPPORTED_UPLOAD_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xls", ".xlsx", ".csv", ".tsv",
    ".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".sh",
    ".zsh", ".fish", ".sql", ".ini", ".cfg", ".xml", ".html",
    ".css", ".log",
}


def create_app(
    *,
    settings: Settings | None = None,
    graph_override: Any | None = None,
) -> FastAPI:
    configured_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_settings = configured_settings or load_settings()
        active_settings.prepare_directories()
        workspace = Workspace(
            active_settings.workspace_root,
            active_settings.data_root,
            active_settings.default_corp_id,
        )
        store = Store(
            active_settings.application_db,
            active_settings.data_root,
            active_settings.default_corp_id,
        )
        backend = CancellableLocalShellBackend(
            active_settings.workspace_root,
            package_root=active_settings.package_root,
            temp_root=active_settings.temp_root,
            timeout=active_settings.command_timeout_seconds,
            max_output_bytes=active_settings.max_command_output_bytes,
            max_file_read_chars=active_settings.max_file_read_chars,
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
        try:
            yield
        finally:
            await manager.shutdown()
            store.close()
            await checkpoint_context.__aexit__(None, None, None)

    app = FastAPI(
        title="Deep Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

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
            "workspace": str(settings.workspace_root),
            "trusted_host_execution": True,
            "active_run_id": active[0] if active else None,
            "max_upload_files": settings.max_upload_files,
            "max_upload_mb": settings.max_upload_mb,
            "max_run_tokens": settings.max_run_tokens,
        }

    @app.post("/conversations", response_model=ConversationSummary)
    async def create_conversation(request: Request, body: ConversationCreate) -> ConversationSummary:
        corp_id = _request_corp(request)
        conversation = request.app.state.store.create_conversation(
            body.title, corp_id=corp_id
        )
        request.app.state.workspace.ensure_chat(corp_id, conversation.conversation_id)
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
        if len(files) > settings.max_upload_files:
            raise HTTPException(400, f"At most {settings.max_upload_files} files may be attached.")
        for upload in files:
            if Path(upload.filename or "").suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
                raise HTTPException(400, f"Unsupported upload type: {upload.filename!r}.")
        manager: RunManager = request.app.state.manager
        try:
            request.app.state.workspace.ensure_chat(corp_id, conversation_id)
            run_id = manager.create_run(
                corp_id,
                conversation_id,
                text.strip() or "Work with the attached files.",
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

    @app.get("/workspace", response_model=list[WorkspaceEntry])
    async def list_workspace(
        request: Request,
        path: str = "",
        scope: Literal["chat", "shared"] = "shared",
        conversation_id: str | None = None,
    ) -> list[WorkspaceEntry]:
        corp_id = _request_corp(request)
        _require_relative_api_path(path, allow_empty=True)
        try:
            return request.app.state.workspace.list_scope(
                corp_id=corp_id,
                scope=scope,
                conversation_id=conversation_id,
                relative_path=path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace directory not found.") from exc

    @app.post("/workspace/uploads", response_model=list[WorkspaceEntry])
    async def upload_workspace_files(
        request: Request,
        files: Annotated[list[UploadFile], File()],
        scope: Literal["chat", "shared"] = "shared",
        conversation_id: str | None = None,
    ) -> list[WorkspaceEntry]:
        corp_id = _request_corp(request)
        settings = request.app.state.settings
        if not files:
            raise HTTPException(400, "At least one file is required.")
        if len(files) > settings.max_upload_files:
            raise HTTPException(400, f"At most {settings.max_upload_files} files may be uploaded.")
        entries: list[WorkspaceEntry] = []
        try:
            for upload in files:
                if Path(upload.filename or "").suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
                    raise HTTPException(400, f"Unsupported upload type: {upload.filename!r}.")
                entries.append(
                    request.app.state.workspace.manual_upload(
                        corp_id=corp_id,
                        original_name=upload.filename or "upload",
                        source=upload.file,
                        max_bytes=settings.max_upload_mb * 1024 * 1024,
                        scope=scope,
                        conversation_id=conversation_id,
                    )
                )
        finally:
            for upload in files:
                await upload.close()
        return entries

    @app.post("/workspace/promote", response_model=WorkspaceEntry)
    async def promote_workspace_entry(
        request: Request,
        path: str,
        conversation_id: str,
    ) -> WorkspaceEntry:
        corp_id = _request_corp(request)
        _require_relative_api_path(path)
        try:
            return request.app.state.workspace.promote(
                corp_id, path, conversation_id
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace path not found.") from exc

    @app.delete("/workspace/chats/{conversation_id}", status_code=204)
    async def cleanup_chat_workspace(request: Request, conversation_id: str) -> None:
        corp_id = _request_corp(request)
        try:
            conversation = request.app.state.store.get_conversation(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc
        if conversation.active_run_id:
            raise HTTPException(409, "Stop the active run before cleaning up its files.")
        request.app.state.workspace.cleanup_chat(corp_id, conversation_id)

    @app.get("/workspace/inspect")
    async def inspect_workspace_file(request: Request, path: str) -> dict[str, Any]:
        corp_id = _request_corp(request)
        _require_relative_api_path(path)
        try:
            target = request.app.state.workspace.resolve_user(
                corp_id, path, must_exist=True
            )
            return inspect_path(target, request.app.state.settings)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace file not found.") from exc

    @app.get("/workspace/download")
    async def download_workspace_file(request: Request, path: str) -> FileResponse:
        corp_id = _request_corp(request)
        _require_relative_api_path(path)
        try:
            target = request.app.state.workspace.resolve_user(
                corp_id, path, must_exist=True
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace file not found.") from exc
        if not target.is_file():
            raise HTTPException(400, "Only regular files can be downloaded.")
        return FileResponse(target, filename=target.name)

    @app.patch("/workspace", response_model=dict[str, str])
    async def rename_workspace_file(
        request: Request, path: str, body: RenameRequest
    ) -> dict[str, str]:
        corp_id = _request_corp(request)
        _require_relative_api_path(path)
        try:
            return {
                "path": request.app.state.workspace.rename(
                    corp_id, path, body.new_name
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace path not found.") from exc
        except FileExistsError as exc:
            raise HTTPException(409, "A workspace entry already has that name.") from exc

    @app.delete("/workspace", status_code=204)
    async def delete_workspace_file(request: Request, path: str) -> None:
        corp_id = _request_corp(request)
        _require_relative_api_path(path)
        try:
            request.app.state.workspace.delete(corp_id, path)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Workspace path not found.") from exc

    @app.get("/attachments/{attachment_id}/download")
    async def download_attachment(request: Request, attachment_id: str) -> FileResponse:
        corp_id = _request_corp(request)
        try:
            path, name = request.app.state.store.attachment_path(
                attachment_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Attachment not found.") from exc
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
        return FileResponse(path, filename=name)

    return app


def _http_error(status: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content={"detail": detail})


def _request_corp(request: Request) -> str:
    """Resolve the lightweight user namespace supplied by the Streamlit UI."""

    configured_default = request.app.state.settings.default_corp_id
    return validate_corp_id(request.headers.get("X-Corp-ID") or configured_default)


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


def _require_relative_api_path(path: str, *, allow_empty: bool = False) -> None:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw and allow_empty:
        return
    if not raw:
        raise WorkspacePathError("A file or directory path is required.")
    if raw.startswith("/"):
        raise WorkspacePathError("API paths must be relative to the workspace.")


app = create_app()
