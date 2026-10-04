"""Cancellable trusted-host shell backend for DeepAgents."""

from __future__ import annotations

import base64
import contextlib
import contextvars
import os
import json
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from datetime import UTC, datetime

from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import (
    DeleteResult,
    DEFAULT_GREP_TIMEOUT,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    _get_backend_read_file_type,
    check_empty_content,
    compile_grep_include_glob,
    compile_recursive_glob,
    perform_string_replacement,
    slice_read_response,
)

from general_agent.processes import ProcessSupervisor

from general_agent.workspace import (
    WorkspacePathError,
    agent_physical_path,
    agent_virtual_path,
    corp_storage_key,
    current_corp_id,
    current_conversation_id,
    reset_current_workspace,
    set_current_workspace,
    validate_workspace_path,
    visible_workspace_parts,
    workspace_directory,
    workspace_file,
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
        self._supervisor = ProcessSupervisor()

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
        """Route and validate within the explicitly selected workspace scope."""

        routed = agent_physical_path(key)
        normalized = "/" + str(key or "").strip().replace("\\", "/").lstrip("/")
        if normalized == "/tmp" or normalized.startswith("/tmp/"):
            run_id = _RUN_ID.get()
            corp_id = current_corp_id()
            if not run_id or not corp_id:
                raise WorkspacePathError("A current run is required for temporary files.")
            remainder = normalized.removeprefix("/tmp").lstrip("/")
            routed = (Path("users") / corp_storage_key(corp_id) / ".tmp" / run_id / remainder).as_posix()
        return validate_workspace_path(self.cwd, self.cwd / routed)

    def _to_virtual_path(self, path: Path) -> str:
        validate_workspace_path(self.cwd, path)
        relative = path.relative_to(self.cwd).as_posix()
        run_id = _RUN_ID.get()
        corp_id = current_corp_id()
        if run_id and corp_id:
            prefix = (Path("users") / corp_storage_key(corp_id) / ".tmp" / run_id).as_posix()
            if relative == prefix or relative.startswith(prefix + "/"):
                remainder = relative.removeprefix(prefix).lstrip("/")
                if not visible_workspace_parts(Path(remainder).parts):
                    raise WorkspacePathError("Protected temporary paths are not exposed.")
                return "/tmp" + ("/" + remainder if remainder else "")
        virtual = agent_virtual_path(relative)
        # In particular, do not expose another run's temporary files or an
        # application directory through the reverse conversion.
        if self._resolve_path(virtual) != path:
            raise WorkspacePathError("The path is outside the active workspace scope.")
        return virtual

    def _read_bytes(self, path: Path) -> bytes:
        with workspace_file(self.cwd, path, os.O_RDONLY) as descriptor:
            with os.fdopen(os.dup(descriptor), "rb") as handle:
                content = handle.read(self.max_file_size_bytes + 1)
        if len(content) > self.max_file_size_bytes:
            raise WorkspacePathError("The file exceeds the filesystem read size limit.")
        return content

    def _write_bytes(self, path: Path, content: bytes) -> None:
        with workspace_file(
            self.cwd, path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            create_parents=True,
        ) as descriptor:
            with os.fdopen(os.dup(descriptor), "wb") as handle:
                handle.write(content)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if Path(str(file_path)).suffix.lower() in _BINARY_DOCUMENT_SUFFIXES:
            return ReadResult(error=(
                f"Binary document '{file_path}' cannot be read with read_file. "
                "Load the matching pdf, docx, pptx, or xlsx skill and follow "
                "its inspection workflow."
            ))
        try:
            content = self._read_bytes(self._resolve_path(file_path))
            if _get_backend_read_file_type(file_path) != "text":
                return ReadResult(file_data={
                    "content": base64.standard_b64encode(content).decode("ascii"),
                    "encoding": "base64",
                })
            text = content.decode("utf-8")
            empty = check_empty_content(text)
            result = (
                ReadResult(file_data={"content": empty, "encoding": "utf-8"})
                if empty else slice_read_response(
                    {"content": text, "encoding": "utf-8"}, offset, limit
                )
            )
            if result.file_data and len(result.file_data["content"]) > self._file_read_limit:
                notice = (f"\n\n[Read truncated at {self._file_read_limit:,} characters. "
                          "Use a smaller line window or grep for the needed section.]")
                result.file_data["content"] = (
                    result.file_data["content"][:max(0, self._file_read_limit - len(notice))]
                    + notice[:self._file_read_limit]
                )
            return result
        except (OSError, ValueError) as exc:
            return ReadResult(error=f"Cannot read '{file_path}': {_file_error(exc)}")

    def write(self, file_path: str, content: str) -> WriteResult:
        if _is_skill_path(file_path):
            return WriteResult(error="Built-in skills are application-managed and read-only.")
        try:
            self._write_bytes(self._resolve_path(file_path), content.encode("utf-8"))
            return WriteResult(path=file_path)
        except (OSError, ValueError) as exc:
            return WriteResult(error=f"Cannot write '{file_path}': {_file_error(exc)}")

    def edit(
        self, file_path: str, old_string: str, new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if _is_skill_path(file_path):
            return EditResult(error="Built-in skills are application-managed and read-only.")
        try:
            path = self._resolve_path(file_path)
            with workspace_file(self.cwd, path, os.O_RDWR) as descriptor:
                with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                    content = handle.read(self.max_file_size_bytes + 1)
                if len(content.encode("utf-8")) > self.max_file_size_bytes:
                    raise WorkspacePathError("The file exceeds the filesystem read size limit.")
                replacement = perform_string_replacement(
                    content, old_string.replace("\r\n", "\n").replace("\r", "\n"),
                    new_string.replace("\r\n", "\n").replace("\r", "\n"), replace_all,
                )
                if isinstance(replacement, str):
                    return EditResult(error=replacement)
                updated, occurrences = replacement
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.ftruncate(descriptor, 0)
                with os.fdopen(os.dup(descriptor), "wb") as handle:
                    handle.write(updated.encode("utf-8"))
            return EditResult(path=file_path, occurrences=occurrences)
        except (OSError, ValueError) as exc:
            return EditResult(error=f"Cannot edit '{file_path}': {_file_error(exc)}")

    def delete(self, file_path: str) -> DeleteResult:
        if _is_skill_path(file_path):
            return DeleteResult(error="Built-in skills are application-managed and read-only.")
        try:
            path = self._resolve_path(file_path)
            if path == self._resolve_path("/") or str(file_path).rstrip("/") in {"/shared", "/chats", "/tmp"}:
                raise WorkspacePathError("Workspace scope roots cannot be deleted.")
            with workspace_directory(self.cwd, path.parent) as parent:
                info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise WorkspacePathError("Symlinks are not allowed in workspace paths.")
                if stat.S_ISDIR(info.st_mode):
                    if not shutil.rmtree.avoids_symlink_attacks:
                        raise WorkspacePathError("This platform lacks safe directory deletion.")
                    shutil.rmtree(path.name, dir_fd=parent)
                else:
                    os.unlink(path.name, dir_fd=parent)
            return DeleteResult(path=file_path)
        except (OSError, ValueError) as exc:
            return DeleteResult(error=f"Cannot delete '{file_path}': {_file_error(exc)}")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses = []
        for path, content in files:
            try:
                if _is_skill_path(path):
                    raise WorkspacePathError("Installed skills are read-only.")
                self._write_bytes(self._resolve_path(path), content)
                responses.append(FileUploadResponse(path=path, error=None))
            except (OSError, ValueError):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses = []
        for path in paths:
            try:
                content = self._read_bytes(self._resolve_path(path))
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except FileNotFoundError:
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
            except (OSError, ValueError):
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
        return responses

    def _file_info(self, path: Path, info: os.stat_result) -> dict:
        directory = stat.S_ISDIR(info.st_mode)
        return {
            "path": self._to_virtual_path(path) + ("/" if directory else ""),
            "is_dir": directory, "size": info.st_size if not directory else 0,
            "modified_at": datetime.fromtimestamp(info.st_mtime, tz=UTC).isoformat(),
        }

    def _entries(self, path: Path):
        with workspace_directory(self.cwd, path) as directory:
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    if not visible_workspace_parts((entry.name,)):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or (
                            stat.S_ISREG(info.st_mode) and info.st_nlink != 1
                        ):
                            continue
                        child = path / entry.name
                        self._to_virtual_path(child)
                        if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
                            yield child, info
                    except (OSError, ValueError):
                        continue

    def ls(self, path: str) -> LsResult:
        try:
            return LsResult(entries=[self._file_info(child, info)
                                    for child, info in self._entries(self._resolve_path(path))])
        except (OSError, ValueError) as exc:
            return LsResult(error=f"Cannot list workspace path: {_file_error(exc)}", entries=[])

    def _inventory(self, path: Path, deadline: float):
        with workspace_directory(self.cwd, path.parent) as parent:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            yield path, info
            return
        if not stat.S_ISDIR(info.st_mode):
            return
        for child, child_info in self._entries(path):
            if time.monotonic() >= deadline:
                raise TimeoutError("Filesystem search deadline exceeded.")
            if stat.S_ISDIR(child_info.st_mode):
                yield from self._inventory(child, deadline)
            else:
                yield child, child_info

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        matches = []
        try:
            if ".." in Path(pattern).parts:
                raise WorkspacePathError("Path traversal is not allowed in glob patterns.")
            matcher = compile_recursive_glob(pattern.lstrip("/"))
            base = self._resolve_path(path or "/")
            deadline = time.monotonic() + 5
            for child, info in self._inventory(base, deadline):
                if matcher(child.relative_to(base).as_posix()):
                    matches.append(self._file_info(child, info))
            return GlobResult(matches=matches)
        except TimeoutError:
            return GlobResult(matches=matches, truncated=True)
        except (OSError, ValueError) as exc:
            return GlobResult(matches=matches, error=f"Cannot glob workspace path: {_file_error(exc)}")

    def _ripgrep_snapshot(self, pattern: str, content: bytes, deadline: float, count: int | None):
        """Run ripgrep on already validated bytes, never a host filesystem path.

        Upstream recursive search cannot enforce our per-component policy or
        descriptor-based opens. Reuse its literal/JSON semantics on stdin instead.
        """
        executable = shutil.which("rg", path=self._env["PATH"])
        if not executable:
            return None
        command = [executable, "--json", "--fixed-strings", "--text", "--color=never"]
        if count is not None:
            command += ["--max-count", str(count + 1)]
        command += ["--", pattern]
        result = subprocess.run(
            command, input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=self._env, timeout=max(0.001, deadline - time.monotonic()), check=False,
        )
        if result.returncode not in {0, 1}:
            return None
        matches = []
        for raw in result.stdout.splitlines():
            frame = json.loads(raw)
            if frame["type"] == "match":
                data = frame["data"]
                matches.append((data["line_number"], data["lines"]["text"].rstrip("\r\n")))
        return matches

    def grep(
        self, pattern: str, path: str | None = None, glob: str | None = None,
        *, max_count: int | None = None, context_lines: int = 0,
    ) -> GrepResult:
        if context_lines < 0:
            raise ValueError("context_lines must be non-negative")
        matches = []
        try:
            base = self._resolve_path(path or "/")
            matcher = compile_grep_include_glob(glob) if glob else None
            deadline = time.monotonic() + DEFAULT_GREP_TIMEOUT
            for child, info in self._inventory(base, deadline):
                relative = child.relative_to(base.parent if child == base else base).as_posix()
                if matcher and not matcher(relative):
                    continue
                if info.st_size > self.max_file_size_bytes:
                    continue
                try:
                    content = self._read_bytes(child)
                    lines = content.decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                except (OSError, ValueError):
                    continue
                remaining = max_count - len(matches) if max_count is not None else None
                found = self._ripgrep_snapshot(pattern, content, deadline, remaining)
                if found is None:
                    found = [(index, line) for index, line in enumerate(lines, 1) if pattern in line]
                virtual = self._to_virtual_path(child)
                for number, text in found:
                    if max_count is not None and len(matches) >= max_count:
                        return GrepResult(matches=matches, truncated=True)
                    match = {"path": virtual, "line": number, "text": text}
                    if context_lines:
                        match["context_before"] = [
                            {"line": index, "text": lines[index - 1]}
                            for index in range(max(1, number - context_lines), number)
                            if pattern not in lines[index - 1]
                        ]
                        match["context_after"] = [
                            {"line": index, "text": lines[index - 1]}
                            for index in range(number + 1, min(len(lines), number + context_lines) + 1)
                            if pattern not in lines[index - 1]
                        ]
                    matches.append(match)
            return GrepResult(matches=matches)
        except (TimeoutError, subprocess.TimeoutExpired):
            return GrepResult(matches=matches, truncated=True)
        except (OSError, ValueError) as exc:
            return GrepResult(matches=matches, error=f"Cannot search workspace path: {_file_error(exc)}")

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
        result = await self._supervisor.run_shell(
            command, owner_id=_RUN_ID.get() or "unscoped", cwd=command_cwd,
            env=command_env, timeout=effective_timeout,
            max_output_bytes=self._output_limit,
        )
        return ExecuteResponse(output=result.output, exit_code=result.exit_code,
                               truncated=result.truncated)

    async def cancel_run(self, run_id: str) -> None:
        await self._supervisor.cancel_owner(run_id)


def _is_skill_path(path: str) -> bool:
    normalized = "/" + str(path or "").strip().replace("\\", "/").lstrip("/")
    return normalized == "/skills" or normalized.startswith("/skills/")


def _file_error(error: Exception) -> str:
    """Keep physical paths and foreign scope details out of tool errors."""

    if isinstance(error, WorkspacePathError):
        return str(error)
    if isinstance(error, OSError):
        return error.strerror or type(error).__name__
    return type(error).__name__
