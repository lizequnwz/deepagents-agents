"""Non-shell, skill-read-only filesystem backend for Advisor Match Agent."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import AsyncIterator
from pathlib import Path

from deepagents.backends import FilesystemBackend

from general_agent.workspace import (
    WorkspacePathError,
    agent_physical_path,
    agent_virtual_path,
    corp_storage_key,
    current_corp_id,
    reset_current_workspace,
    set_current_workspace,
)

_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("advisor_match_run_id", default=None)


class AdvisorWorkspaceBackend(FilesystemBackend):
    """Expose installed skill references without any command or workspace file access."""

    def __init__(self, root_dir: Path) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)

    @contextlib.asynccontextmanager
    async def run_scope(self, run_id: str, corp_id: str, conversation_id: str | None = None) -> AsyncIterator[None]:
        run_token = _RUN_ID.set(run_id)
        workspace_tokens = set_current_workspace(corp_id, conversation_id or run_id)
        try:
            yield
        finally:
            reset_current_workspace(workspace_tokens)
            _RUN_ID.reset(run_token)

    async def cancel_run(self, _run_id: str) -> None:
        """Custom advisor tools are bounded and observe graph-task cancellation."""

    def _resolve_path(self, key: str) -> Path:
        normalized = "/" + str(key or "").strip().replace("\\", "/").lstrip("/")
        if normalized != "/skills" and not normalized.startswith("/skills/"):
            raise ValueError("Advisor filesystem tools may read installed skills only.")
        try:
            routed = agent_physical_path(normalized)
        except WorkspacePathError as exc:
            raise ValueError(str(exc)) from exc
        return super()._resolve_path("/" + routed if routed else "/")

    def _to_virtual_path(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.cwd).as_posix()
        return agent_virtual_path(relative)

    @property
    def active_run_id(self) -> str | None:
        return _RUN_ID.get()

    def run_temp_path(self, name: str) -> Path:
        run_id = _RUN_ID.get()
        corp_id = current_corp_id()
        if not run_id or not corp_id or not name or Path(name).name != name:
            raise RuntimeError("Active run context is unavailable or invalid.")
        root = self.cwd / "users" / corp_storage_key(corp_id) / ".tmp" / run_id
        root.mkdir(parents=True, exist_ok=True)
        return root / name
