"""Attempt-owned previews with finite logs and isolated browser evidence."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import math
import re
import socket
import struct
import uuid
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit

from general_agent.coding.runtime import DockerRuntime, RuntimeUnavailable
from general_agent.coding.source import source_revision, source_snapshot
from general_agent.config import Settings

MAX_PREVIEWS = 2
MAX_HISTORY = 16
MAX_PNG_BYTES = 5 * 1024 * 1024


class ProcessSessionError(ValueError):
    pass


class CursorLog:
    """A finite byte tail; absolute cursors make discarded output explicit."""

    def __init__(self, capacity: int):
        if type(capacity) is not int or not 1 <= capacity <= 10 * 1024 * 1024:
            raise ProcessSessionError("Process log capacity must be between one byte and ten MiB.")
        self.capacity = capacity
        self.data = bytearray()
        self.cursor = 0

    def append(self, descriptor: int, content: bytes) -> None:
        chunk = (b"[stderr] " if descriptor == 2 else b"") + content
        self.cursor += len(chunk)
        self.data.extend(chunk)
        if len(self.data) > self.capacity:
            del self.data[:len(self.data) - self.capacity]

    def read(self, cursor: int, limit: int) -> dict:
        if type(cursor) is not int or cursor < 0 or cursor > self.cursor or type(limit) is not int or not 0 < limit <= 12_000:
            raise ProcessSessionError("Invalid process log cursor or page size.")
        base = self.cursor - len(self.data)
        start = max(cursor, base)
        contents = bytes(self.data[start - base:start - base + limit])
        return {"output": contents.decode("utf-8", errors="replace"), "cursor": start + len(contents),
                "base_cursor": base, "gap": cursor < base, "truncated": base > 0}


@dataclass
class _Session:
    id: str
    command: str
    port: int | None
    browser: bool
    runtime: DockerRuntime
    source_revision: str
    timeout: float
    log: CursorLog
    runtime_identity: str | None = None
    main_runtime_identity: str | None = None
    state: str = "starting"
    task: asyncio.Task | None = None
    exit_code: int | None = None
    error: str | None = None
    stopped: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ProcessSessions:
    """Previews use private copies and never export mutations to durable source."""

    def __init__(self, settings: Settings, runtime: DockerRuntime, *, setup_records=(), runtime_factory=DockerRuntime):
        self.settings, self.runtime = settings, runtime
        self.setup_records = copy.deepcopy(tuple(setup_records))
        self.runtime_factory = runtime_factory
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._deadline = asyncio.get_running_loop().time() + settings.run_timeout_seconds

    def _revision(self) -> str:
        snapshot = source_snapshot(
            self.runtime.repo, max_files=self.settings.max_repository_files,
            max_bytes=self.settings.max_repository_mb * 1024 * 1024,
            tracked_paths=self.runtime.source_paths,
        )
        return source_revision(snapshot)

    def _session(self, process_id: str) -> _Session:
        if not isinstance(process_id, str) or not re.fullmatch(r"[0-9a-f]{32}", process_id) or process_id not in self._sessions:
            raise ProcessSessionError("No process belongs to this attempt with that ID.")
        return self._sessions[process_id]

    def _record(self, session: _Session) -> dict:
        return {"id": session.id, "owner_id": self.runtime.owner_id, "command": session.command,
                "port": session.port, "browser": session.browser, "state": session.state,
                "source_revision": session.source_revision, "runtime_identity": session.runtime.identity,
                "stale": self.runtime.source_revision != session.source_revision,
                "exit_code": session.exit_code, "error": session.error, "timeout": session.timeout}

    def records(self) -> list[dict]:
        return [self._record(session) for session in self._sessions.values()]

    def archive(self) -> list[dict]:
        return [self.read_output(session.id, cursor=max(0, session.log.cursor - 12_000))
                for session in self._sessions.values()]

    async def start(self, command: str, *, port: int | None = None, timeout: float | None = None, browser: bool = False) -> dict:
        if not isinstance(command, str) or not command.strip() or len(command) > 16_384:
            raise ProcessSessionError("A bounded, non-empty preview command is required.")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ProcessSessionError("A valid local preview port is required.")
        if browser and port is None:
            raise ProcessSessionError("A browser preview needs its owned local server port.")
        remaining = self._deadline - asyncio.get_running_loop().time()
        if timeout is not None and (type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0):
            raise ProcessSessionError("A finite, positive preview timeout is required.")
        lifetime = min(timeout if timeout is not None else remaining, remaining)
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise ProcessSessionError("The preview lifetime has expired or is invalid.")
        async with self._lock:
            if self._closed:
                raise ProcessSessionError("This attempt's previews are closed.")
            active = [value for value in self._sessions.values() if value.state in {"starting", "running", "stopping"}]
            if len(active) >= MAX_PREVIEWS:
                raise ProcessSessionError("At most two preview processes may run in one attempt.")
            if self.settings.coding_runtime == "local" and port is not None:
                # Local ports are shared with other applications. Refuse an
                # existing listener before dispatch; browser probes additionally
                # verify the listener's process-group ownership after startup.
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        listener.bind(("127.0.0.1", port))
                        listener.listen(1)
                except OSError as exc:
                    raise ProcessSessionError("The selected local preview port is already in use or unavailable.") from exc
            while len(self._sessions) >= MAX_HISTORY:
                expired = next((key for key, value in self._sessions.items() if value.state not in {"starting", "running", "stopping"}), None)
                if expired is None:
                    raise ProcessSessionError("The preview history is full.")
                del self._sessions[expired]
            settings = self.settings
            if self.settings.coding_runtime == "docker":
                image = self.settings.coding_browser_image if browser else self.runtime.image_id
                settings = replace(self.settings, coding_image=image)
            preview = self.runtime_factory(settings, self.runtime.repo, self.runtime.owner_id)
            preview.track_source(self.runtime.source_paths)
            process_id = uuid.uuid4().hex
            session = _Session(process_id, command, port, browser, preview, self._revision(), lifetime,
                               CursorLog(self.settings.max_command_output_bytes))
            self._sessions[process_id] = session
            try:
                await preview.start()
                if browser and not preview.browser_capable:
                    raise ProcessSessionError("The selected runtime needs the configured Playwright and Chromium browser tools.")
                if browser and self.settings.coding_runtime == "docker" and self.runtime.image_id not in {preview.image_id, preview.base_image_id}:
                    raise ProcessSessionError("Build the browser image from this exact coding image before starting a browser preview.")
                if browser and self.settings.coding_runtime == "local" and preview.runtime_id != self.runtime.runtime_id:
                    raise ProcessSessionError("The preview and coding runtime toolchains differ.")
                for setup in self.setup_records:
                    await preview.install_setup(setup)
                session.runtime_identity = preview.identity
                session.main_runtime_identity = self.runtime.identity
                if self._revision() != session.source_revision or preview.source_revision != session.source_revision:
                    raise ProcessSessionError("Session source changed while starting the preview; restart it on current files.")
                session.timeout = min(session.timeout, self._deadline - asyncio.get_running_loop().time())
                if session.timeout <= 0:
                    raise ProcessSessionError("The attempt expired while starting its preview.")
                session.state = "running"
                session.task = asyncio.create_task(self._drive(session), name=f"preview-{process_id}")
                return self._record(session)
            except BaseException:
                session.state = "failed"
                await preview.close()
                raise

    async def _drive(self, session: _Session) -> None:
        final_state = "failed"
        try:
            result = await session.runtime.run_preview(session.command, timeout=session.timeout, on_output=session.log.append)
            session.exit_code = result.exit_code
            final_state = "stopped" if session.stopped else "timed_out" if result.timed_out or result.exit_code == 124 else "exited"
        except asyncio.CancelledError:
            final_state = "stopped"
        except Exception as exc:
            session.error = str(exc)[:1000]
        finally:
            session.state = "stopping"
            try:
                await session.runtime.close()
            except Exception as exc:
                final_state, session.error = "failed", str(exc)[:1000]
            session.state = final_state

    def read_output(self, process_id: str, *, cursor: int = 0, limit: int = 12_000) -> dict:
        session = self._session(process_id)
        return {**self._record(session), **session.log.read(cursor, limit)}

    async def stop(self, process_id: str) -> dict:
        session = self._session(process_id)
        session.stopped = True
        if session.task is not None and not session.task.done():
            session.state = "stopping"
            if not session.task.cancelling():
                session.task.cancel()
            await asyncio.shield(asyncio.gather(session.task, return_exceptions=True))
        # A task cancelled before its first instruction never enters _drive's
        # finally block. The manager still owns and must close that runtime.
        await session.runtime.close()
        if session.state in {"starting", "running", "stopping"}:
            session.state = "stopped"
        return self._record(session)

    async def browser_check(self, process_id: str, *, path: str = "/", selector: str | None = None,
                            expected_text: str | None = None, timeout: float = 15) -> dict:
        session = self._session(process_id)
        if not session.browser or session.port is None or session.state != "running":
            raise ProcessSessionError("Browser checks require this attempt's running browser preview.")
        validate_browser_request(path, selector, expected_text, timeout)
        async with session.lock:
            before = self._revision()
            preview_before = await session.runtime.preview_revision()
            await session.runtime._refresh_dependency_identity()
            environment_before = session.runtime.identity
            if environment_before != session.runtime_identity or self.runtime.identity != session.main_runtime_identity:
                return {"metadata": {"status": "stale", "source_revision": session.source_revision,
                        "main_runtime_identity": self.runtime.identity, "process_id": process_id,
                        "reason": "The preview or main dependency environment changed after preview startup; restart it."}, "png": b""}
            if before != session.source_revision or preview_before != session.source_revision:
                return {"metadata": {"status": "stale", "source_revision": session.source_revision,
                        "main_runtime_identity": self.runtime.identity, "process_id": process_id,
                        "reason": "Preview source differs from the current session; stop and restart it."}, "png": b""}
            payload = await session.runtime.browser_probe(port=session.port, path=path, selector=selector,
                                                          expected_text=expected_text, timeout=timeout)
            metadata, png = decode_browser_result(payload)
            after = self._revision()
            preview_after = await session.runtime.preview_revision()
            await session.runtime._refresh_dependency_identity()
            metadata.update(process_id=process_id, owner_id=self.runtime.owner_id, source_revision=before,
                            runtime_identity=session.runtime.identity, before_runtime_identity=environment_before,
                            main_runtime_identity=self.runtime.identity)
            if before != after or preview_after != before:
                metadata.update(status="stale", reason="Source changed during the browser check.")
            elif session.runtime.identity != environment_before:
                metadata.update(status="stale", reason="Installed dependencies changed during the browser check.")
            return {"metadata": metadata, "png": png}

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
        results = await asyncio.gather(*(self.stop(key) for key in tuple(self._sessions)), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result


def validate_browser_request(path: str, selector: str | None, expected_text: str | None, timeout: float) -> None:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or len(path) > 2048 or "\\" in path:
        raise ProcessSessionError("A server-relative browser path is required.")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or any(ord(value) < 32 for value in path):
        raise ProcessSessionError("Browser checks can only use the preview's owned local origin.")
    if selector is not None and (not isinstance(selector, str) or not 0 < len(selector) <= 500):
        raise ProcessSessionError("A bounded selector is required.")
    if expected_text is not None and (not isinstance(expected_text, str) or len(expected_text) > 1000):
        raise ProcessSessionError("Expected browser text exceeds its bound.")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ProcessSessionError("Browser checks require a timeout of at most 30 seconds.")


def decode_browser_result(payload: bytes) -> tuple[dict, bytes]:
    if len(payload) < 4:
        raise RuntimeUnavailable("Missing browser evidence.")
    length = struct.unpack(">I", payload[:4])[0]
    if not 0 < length <= 65_536 or length + 4 > len(payload):
        raise RuntimeUnavailable("Invalid browser evidence framing.")
    metadata = json.loads(payload[4:4 + length])
    png = payload[4 + length:]
    if not isinstance(metadata, dict) or metadata.get("protocol") != 1 or metadata.get("status") not in {"passed", "failed"}:
        raise RuntimeUnavailable("Invalid browser check metadata.")
    if len(png) > MAX_PNG_BYTES or len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeUnavailable("Invalid or oversized browser screenshot.")
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) != (1280, 720) or metadata.get("width") != width or metadata.get("height") != height:
        raise RuntimeUnavailable("Invalid browser screenshot dimensions.")
    return metadata, png
