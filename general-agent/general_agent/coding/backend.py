"""DeepAgents file tools over one isolated, policy-filtered repository copy."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import threading
from pathlib import Path

from PIL import Image

from deepagents.backends.protocol import (
    BackendProtocol, DeleteResult, EditResult, ExecuteResponse, FileDownloadResponse,
    FileUploadResponse, GlobResult, GrepResult, LsResult, ReadResult,
    SandboxBackendProtocol, WriteResult,
)
from deepagents.backends.utils import (
    compile_grep_include_glob, compile_recursive_glob, perform_string_replacement,
    slice_read_response,
)

from general_agent.coding.source import (
    source_file, source_manifest, source_revision, source_snapshot, validate_source_path,
)
from general_agent.workspace import workspace_directory


class RepositoryBackend(BackendProtocol):
    def __init__(self, repo: Path, *, read_only: bool, read_limit: int = 20000,
                 max_bytes: int = 50 * 1024 * 1024, max_files: int = 5000,
                 tracked_paths: tuple[str, ...] = ()):
        self.repo = repo
        self.read_only = read_only
        self.read_limit = read_limit
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.lock = asyncio.Lock()
        self._mutex = threading.RLock()
        self.tracked_paths = tracked_paths or tuple(source_manifest(repo))
        self.revision = source_revision(self._manifest())

    def _snapshot(self):
        return source_snapshot(self.repo, tracked_paths=self.tracked_paths,
                               max_files=self.max_files, max_bytes=self.max_bytes)

    def _manifest(self):
        return source_manifest(self.repo, tracked_paths=self.tracked_paths,
                               max_files=self.max_files, max_bytes=self.max_bytes)

    def _relative(self, path: str, *, directory: bool = False) -> str:
        if path in {"", "/"} and directory:
            return ""
        return validate_source_path(path.lstrip("/")).as_posix()

    def reconcile(self) -> None:
        self.revision = source_revision(self._manifest())

    def _admit_mutation(self) -> None:
        if self.read_only:
            raise ValueError("This mode permits repository inspection only.")
        if source_revision(self._manifest()) != self.revision:
            raise ValueError("Repository changed outside this operation; inspect the new revision first.")

    def _capacity(self, relative: str, data: bytes) -> None:
        files = self._manifest()
        size = sum(item["size"] for item in files.values()) - files.get(relative, {}).get("size", 0) + len(data)
        count = len(files) + (relative not in files)
        if size > self.max_bytes or count > self.max_files:
            raise ValueError("Repository source storage limit exceeded.")

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            relative = self._relative(file_path)
            if Path(relative).suffix.lower() in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsm"}:
                return ReadResult(error="Binary document: use the matching document skill's inspect/render/verify workflow.")
            with self._mutex, source_file(self.repo, relative) as fd:
                with os.fdopen(os.dup(fd), "rb") as handle:
                    content = handle.read(5 * 1024 * 1024 + 1)
            if len(content) > 5 * 1024 * 1024 or b"\x00" in content:
                if Path(relative).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and len(content) <= 5 * 1024 * 1024:
                    with Image.open(io.BytesIO(content)) as picture:
                        if picture.width * picture.height > 5_000_000:
                            return ReadResult(error="Image exceeds the five-million-pixel inspection limit.")
                        picture.verify()
                    return ReadResult(file_data={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"})
                return ReadResult(error="Binary or oversized source requires an explicit asset inspection.")
            text = content.decode("utf-8")
            result = slice_read_response({"content": text, "encoding": "utf-8"}, offset, limit)
            if result.file_data and len(result.file_data["content"]) > self.read_limit:
                result.file_data["content"] = result.file_data["content"][:self.read_limit] + "\n[Page with a smaller line window.]"
            return result
        except (OSError, ValueError) as exc:
            return ReadResult(error=f"Cannot read source: {type(exc).__name__}.")

    def ls(self, path: str) -> LsResult:
        try:
            prefix = self._relative(path, directory=True)
            files = self._manifest()
            entries = {}
            for name, metadata in files.items():
                if prefix and not name.startswith(prefix + "/"):
                    continue
                remainder = name[len(prefix) + 1:] if prefix else name
                first = remainder.split("/")[0]
                child = "/" + (prefix + "/" if prefix else "") + first
                entries[child] = {"path": child, "is_dir": "/" in remainder,
                                  "size": metadata["size"] if "/" not in remainder else 0}
            return LsResult(entries=sorted(entries.values(), key=lambda item: item["path"]))
        except (OSError, ValueError):
            return LsResult(error="Cannot list this source path.")

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            prefix = self._relative(path or "/", directory=True)
            matcher = compile_recursive_glob(pattern)
            result = []
            for name, metadata in self._manifest().items():
                if prefix and not name.startswith(prefix + "/"):
                    continue
                relative = name[len(prefix) + 1:] if prefix else name
                if matcher(relative):
                    result.append({"path": "/" + name, "is_dir": False, "size": metadata["size"]})
            return GlobResult(matches=result)
        except (OSError, ValueError):
            return GlobResult(error="Cannot expand this source pattern.")

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None,
             *, max_count: int | None = None) -> GrepResult:
        try:
            prefix = self._relative(path or "/", directory=True)
            matcher = compile_grep_include_glob(glob) if glob else None
            cap = min(max_count if max_count is not None else 200, 1000)
            if cap <= 0:
                return GrepResult(matches=[])
            matches = []
            for name, metadata in self._snapshot().items():
                if prefix and name != prefix and not name.startswith(prefix + "/"):
                    continue
                if matcher and not matcher(name):
                    continue
                content = metadata["content"]
                if b"\x00" in content:
                    continue
                try:
                    lines = content.decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                for number, line in enumerate(lines, 1):
                    if pattern in line:
                        if len(matches) == cap:
                            return GrepResult(matches=matches, truncated=True)
                        matches.append({"path": "/" + name, "line": number, "text": line[:2000]})
            return GrepResult(matches=matches)
        except (OSError, ValueError):
            return GrepResult(error="Cannot search this source path.")

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            with self._mutex:
                self._admit_mutation()
                relative = self._relative(file_path)
                data = content.encode("utf-8")
                if len(data) > 5 * 1024 * 1024:
                    raise ValueError("Source file exceeds size limit.")
                self._capacity(relative, data)
                with source_file(self.repo, relative, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                                 create_parents=True) as fd:
                    with os.fdopen(os.dup(fd), "wb") as handle:
                        handle.write(data)
                self.tracked_paths = tuple(sorted(set(self.tracked_paths) | {relative}))
                self.reconcile()
            return WriteResult(path=file_path)
        except (OSError, ValueError) as exc:
            return WriteResult(error=str(exc) if isinstance(exc, ValueError) else "Cannot write source.")

    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> EditResult:
        try:
            with self._mutex:
                self._admit_mutation()
                relative = self._relative(file_path)
                with source_file(self.repo, relative, os.O_RDWR) as fd:
                    with os.fdopen(os.dup(fd), "r", encoding="utf-8") as handle:
                        content = handle.read(5 * 1024 * 1024 + 1)
                    updated = perform_string_replacement(content, old_string, new_string, replace_all)
                    if isinstance(updated, str):
                        return EditResult(error=updated)
                    replacement, count = updated
                    data = replacement.encode("utf-8")
                    if len(data) > 5 * 1024 * 1024:
                        raise ValueError("Source file exceeds size limit.")
                    self._capacity(relative, data)
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    with os.fdopen(os.dup(fd), "wb") as handle:
                        handle.write(data)
                self.reconcile()
            return EditResult(path=file_path, occurrences=count)
        except (OSError, ValueError) as exc:
            return EditResult(error=str(exc) if isinstance(exc, ValueError) else "Cannot edit source.")

    def delete(self, file_path: str) -> DeleteResult:
        try:
            with self._mutex:
                self._admit_mutation()
                relative = self._relative(file_path)
                # Whole-file removal only; directory deletion is deliberately not recursive.
                with source_file(self.repo, relative) as fd:
                    expected = os.fstat(fd)
                    target = self.repo / relative
                    with workspace_directory(self.repo, target.parent) as parent:
                        actual = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
                        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                            raise ValueError("Source changed before deletion.")
                        os.unlink(target.name, dir_fd=parent)
                self.reconcile()
            return DeleteResult(path=file_path)
        except (OSError, ValueError) as exc:
            return DeleteResult(error=str(exc) if isinstance(exc, ValueError) else "Cannot delete source.")

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        async with self.lock:
            return self.write(file_path, content)

    async def aedit(self, file_path: str, old_string: str, new_string: str,
                    replace_all: bool = False) -> EditResult:
        async with self.lock:
            return self.edit(file_path, old_string, new_string, replace_all)

    async def adelete(self, file_path: str) -> DeleteResult:
        async with self.lock:
            return self.delete(file_path)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="Repository uploads are not exposed.") for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for path in paths:
            try:
                with source_file(self.repo, self._relative(path)) as fd:
                    with os.fdopen(os.dup(fd), "rb") as handle:
                        data = handle.read(5 * 1024 * 1024 + 1)
                results.append(FileDownloadResponse(path=path, content=data))
            except (OSError, ValueError):
                results.append(FileDownloadResponse(path=path, error="invalid_path"))
        return results


class ExecutableRepositoryBackend(RepositoryBackend, SandboxBackendProtocol):
    def __init__(self, repo: Path, *, runtime, read_limit: int = 20000):
        super().__init__(repo, read_only=False, read_limit=read_limit)
        self.runtime = runtime

    @property
    def id(self) -> str:
        return self.runtime.owner_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        raise RuntimeError("Coding execution requires the asynchronous session controller.")

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        async with self.lock:
            result = self.write(file_path, content)
            if result.error is None:
                self.runtime.track_source(self.tracked_paths)
                await self.runtime.sync_to_container()
            return result

    async def aedit(self, file_path: str, old_string: str, new_string: str,
                    replace_all: bool = False) -> EditResult:
        async with self.lock:
            result = self.edit(file_path, old_string, new_string, replace_all)
            if result.error is None:
                self.runtime.track_source(self.tracked_paths)
                await self.runtime.sync_to_container()
            return result

    async def adelete(self, file_path: str) -> DeleteResult:
        async with self.lock:
            result = self.delete(file_path)
            if result.error is None:
                self.runtime.track_source(self.tracked_paths)
                await self.runtime.sync_to_container()
            return result

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        async with self.lock:
            return await self.execute_locked(command, timeout=timeout)

    async def execute_locked(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """The check recorder holds the same writer lock around both manifests."""
        self._admit_mutation()
        self.runtime.track_source(self.tracked_paths)
        await self.runtime.sync_to_container()
        result = await self.runtime.execute(command, timeout=timeout)
        await self.runtime.sync_from_container()
        self.tracked_paths = tuple(set(self.tracked_paths) | set(self.runtime.source_paths))
        self.reconcile()
        return ExecuteResponse(output=result.output, exit_code=result.exit_code,
                               truncated=result.truncated)
