"""Cancellable trusted-host shell backend for DeepAgents."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import signal
import sys
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path

from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    ReadResult,
    WriteResult,
)

from general_agent.workspace import (
    WorkspacePathError,
    agent_physical_path,
    agent_virtual_path,
    corp_storage_key,
    current_corp_id,
    current_conversation_id,
    reset_current_workspace,
    set_current_workspace,
)

_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "general_agent_run_id", default=None
)
_BINARY_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".dotx",
    ".ppt",
    ".pptx",
    ".potx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xltx",
}


class CancellableLocalShellBackend(LocalShellBackend):
    """Run commands on the host while supporting run-scoped cancellation.

    This is deliberately not a sandbox. `virtual_mode` protects only built-in
    filesystem tools; shell commands retain the local user's host permissions.
    """

    def __init__(
        self,
        root_dir: Path,
        *,
        package_root: Path,
        temp_root: Path,
        timeout: int,
        max_output_bytes: int,
        max_file_read_chars: int = 20_000,
    ) -> None:
        system_path = os.environ.get(
            "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        )
        path = os.pathsep.join([str(Path(sys.executable).parent), system_path])
        env = {
            "PATH": path,
            "PYTHONPATH": str(package_root),
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(temp_root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        super().__init__(
            root_dir=root_dir,
            virtual_mode=True,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            env=env,
            inherit_env=False,
        )
        self._timeout = timeout
        self._output_limit = max_output_bytes
        self._file_read_limit = max_file_read_chars
        self._processes: dict[str, set[asyncio.subprocess.Process]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def run_scope(
        self,
        run_id: str,
        corp_id: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[None]:
        run_token = _RUN_ID.set(run_id)
        workspace_tokens = set_current_workspace(corp_id, conversation_id or run_id)
        try:
            yield
        finally:
            reset_current_workspace(workspace_tokens)
            _RUN_ID.reset(run_token)

    def _resolve_path(self, key: str) -> Path:
        """Route ordinary file tools into the current chat's virtual root."""

        try:
            routed = agent_physical_path(key)
        except WorkspacePathError as exc:
            raise ValueError(str(exc)) from exc
        run_id = _RUN_ID.get()
        corp_id = current_corp_id()
        normalized = "/" + str(key or "").strip().replace("\\", "/").lstrip("/")
        if run_id and corp_id and (
            normalized == "/tmp" or normalized.startswith("/tmp/")
        ):
            remainder = normalized.removeprefix("/tmp").lstrip("/")
            routed = (
                Path("users")
                / corp_storage_key(corp_id)
                / ".tmp"
                / run_id
                / remainder
            ).as_posix()
        return super()._resolve_path("/" + routed if routed else "/")

    def _to_virtual_path(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.cwd).as_posix()
        run_id = _RUN_ID.get()
        corp_id = current_corp_id()
        if run_id and corp_id:
            temp_prefix = (
                Path("users")
                / corp_storage_key(corp_id)
                / ".tmp"
                / run_id
            ).as_posix()
            if relative == temp_prefix:
                return "/tmp"
            if relative.startswith(temp_prefix + "/"):
                return "/tmp/" + relative.removeprefix(temp_prefix + "/")
        return agent_virtual_path(relative)

    def glob(self, pattern: str, path: str | None = None):
        # FilesystemBackend otherwise bypasses `_resolve_path` when `path=None`.
        return super().glob(pattern, "/" if path is None and current_conversation_id() else path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        suffix = Path(str(file_path)).suffix.lower()
        if suffix in _BINARY_DOCUMENT_SUFFIXES:
            return ReadResult(
                error=(
                    f"Binary document '{file_path}' cannot be read with read_file. "
                    "Load the matching pdf, docx, pptx, or xlsx skill and follow "
                    "its inspection workflow."
                )
            )
        result = super().read(file_path, offset, limit)
        if (
            result.file_data
            and result.file_data.get("encoding") == "utf-8"
            and len(result.file_data.get("content", "")) > self._file_read_limit
        ):
            notice = (
                f"\n\n[Read truncated at {self._file_read_limit:,} characters. "
                "Use a smaller line window or grep for the needed section.]"
            )
            content = result.file_data["content"]
            result.file_data = {
                **result.file_data,
                "content": content[: self._file_read_limit - len(notice)] + notice,
            }
        return result

    def write(self, file_path: str, content: str) -> WriteResult:
        if _is_skill_path(file_path):
            return WriteResult(error="Built-in skills are application-managed and read-only.")
        return super().write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if _is_skill_path(file_path):
            return EditResult(error="Built-in skills are application-managed and read-only.")
        return super().edit(file_path, old_string, new_string, replace_all)

    def delete(self, file_path: str) -> DeleteResult:
        if _is_skill_path(file_path):
            return DeleteResult(error="Built-in skills are application-managed and read-only.")
        return super().delete(file_path)

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        if not isinstance(command, str) or not command.strip():
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )
        effective_timeout = timeout if timeout is not None else self._timeout
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        conversation_id = current_conversation_id()
        corp_id = current_corp_id()
        command_cwd = (
            self.cwd
            / "users"
            / corp_storage_key(corp_id)
            / "chats"
            / conversation_id
            if conversation_id and corp_id
            else self.cwd
        )
        command_cwd.mkdir(parents=True, exist_ok=True)
        user_root = (
            self.cwd / "users" / corp_storage_key(corp_id) if corp_id else self.cwd
        )
        package_root = user_root / ".packages"
        node_package_root = package_root / "node"
        temp_root = user_root / ".tmp" / (_RUN_ID.get() or "unscoped")
        package_root.mkdir(parents=True, exist_ok=True)
        node_package_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        command_env = {
            **self._env,
            "NODE_PATH": str(node_package_root / "node_modules"),
            "PYTHONPATH": str(package_root),
            "TMPDIR": str(temp_root),
            "GENERAL_AGENT_WORKSPACE_ROOT": str(self.cwd),
            "GENERAL_AGENT_CHAT_DIR": str(command_cwd),
            "GENERAL_AGENT_SHARED_DIR": str(user_root / "shared"),
            "GENERAL_AGENT_PACKAGE_DIR": str(package_root),
            "GENERAL_AGENT_NODE_PACKAGE_DIR": str(node_package_root),
            "GENERAL_AGENT_TEMP_DIR": str(temp_root),
            "GENERAL_AGENT_SKILLS_DIR": str(self.cwd / ".app" / "skills"),
        }
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(command_cwd),
            env=command_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        run_id = _RUN_ID.get() or "unscoped"
        async with self._lock:
            self._processes[run_id].add(process)
        try:
            stdout_task = asyncio.create_task(_read_limited(process.stdout, self._output_limit))
            stderr_task = asyncio.create_task(_read_limited(process.stderr, self._output_limit))
            try:
                await asyncio.wait_for(process.wait(), timeout=effective_timeout)
            except TimeoutError:
                await _terminate(process)
                stdout, stdout_truncated = await stdout_task
                stderr, stderr_truncated = await stderr_task
                output, output_truncated = _combine_output(
                    stdout, stderr, self._output_limit
                )
                timeout_line = f"[stderr] Command timed out after {effective_timeout} seconds."
                output = f"{output}\n{timeout_line}" if output else timeout_line
                return ExecuteResponse(
                    output=output,
                    exit_code=124,
                    truncated=stdout_truncated or stderr_truncated or output_truncated,
                )
            except asyncio.CancelledError:
                await _terminate(process)
                stdout_task.cancel()
                stderr_task.cancel()
                raise
            stdout, stdout_truncated = await stdout_task
            stderr, stderr_truncated = await stderr_task
            output, output_truncated = _combine_output(
                stdout, stderr, self._output_limit
            )
            return ExecuteResponse(
                output=output,
                exit_code=int(process.returncode or 0),
                truncated=stdout_truncated or stderr_truncated or output_truncated,
            )
        finally:
            async with self._lock:
                self._processes[run_id].discard(process)
                if not self._processes[run_id]:
                    self._processes.pop(run_id, None)

    async def cancel_run(self, run_id: str) -> None:
        async with self._lock:
            processes = list(self._processes.get(run_id, ()))
        await asyncio.gather(*(_terminate(process) for process in processes))


async def _read_limited(
    stream: asyncio.StreamReader | None, limit: int
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    output = bytearray()
    truncated = False
    while chunk := await stream.read(64 * 1024):
        remaining = limit - len(output)
        if remaining > 0:
            output.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(output), truncated


def _combine_output(stdout: bytes, stderr: bytes, limit: int) -> tuple[str, bool]:
    parts: list[str] = []
    if stdout:
        parts.append(stdout.decode("utf-8", errors="replace").rstrip())
    if stderr:
        decoded = stderr.decode("utf-8", errors="replace").rstrip()
        parts.append("\n".join(f"[stderr] {line}" for line in decoded.splitlines()))
    combined = "\n".join(part for part in parts if part)
    encoded = combined.encode("utf-8")
    if len(encoded) <= limit:
        return combined, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()


def _is_skill_path(path: str) -> bool:
    normalized = "/" + str(path or "").strip().replace("\\", "/").lstrip("/")
    return normalized == "/skills" or normalized.startswith("/skills/")
