"""Bounded, owner-scoped POSIX subprocess execution with an explicit environment.

Process groups provide cancellation, not a security sandbox. Children that
deliberately leave their group require a separate execution boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import signal
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_TERM_GRACE_SECONDS = 0.1
_CANCEL_CLEANUP_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class ProcessResult:
    output: str
    exit_code: int
    truncated: bool
    timed_out: bool = False
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class BinaryProcessResult:
    stdout: bytes
    stderr: bytes
    exit_code: int
    truncated: bool
    timed_out: bool = False
    cancelled: bool = False


class _OwnedProcess(asyncio.SubprocessProtocol):
    def __init__(self, max_output_bytes: int, input_data: bytes | None = None,
                 on_output: Callable[[int, bytes], None] | None = None) -> None:
        self.limit = max_output_bytes
        self.input_data = input_data
        self.on_output = on_output
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.truncated = False
        self.transport: asyncio.SubprocessTransport | None = None
        self.completed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.cancel_requested = asyncio.Event()
        self.finished = asyncio.Event()
        self.stop_requested = False
        self.force_requested = False
        self.error: Exception | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.SubprocessTransport, transport)
        if self.stop_requested:
            self.signal(signal.SIGKILL if self.force_requested else signal.SIGTERM)
            if self.force_requested:
                self.transport.close()
        elif self.input_data is not None:
            pipe = cast(asyncio.WriteTransport, self.transport.get_pipe_transport(0))
            pipe.write(self.input_data)
            pipe.write_eof()

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        if self.on_output is not None:
            try:
                self.on_output(fd, data)
            except Exception as exc:
                self.error = exc
                self.force_close()
                if not self.completed.done():
                    self.completed.set_result(None)
                return
        remaining = self.limit - len(self.stdout) - len(self.stderr)
        target = self.stdout if fd == 1 else self.stderr
        target.extend(data[:remaining])
        self.truncated |= len(data) > remaining

    def connection_lost(self, exc: Exception | None) -> None:
        self.error = exc
        if not self.completed.done():
            self.completed.set_result(None)

    def signal(self, value: signal.Signals) -> None:
        if self.transport is not None:
            # The group may still contain children after its leader was reaped.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.transport.get_pid(), value)

    def force_close(self) -> None:
        self.stop_requested = True
        self.force_requested = True
        self.signal(signal.SIGKILL)
        if self.transport is not None:
            self.transport.close()

    def group_exists(self) -> bool:
        if self.transport is None:
            return False
        try:
            os.killpg(self.transport.get_pid(), 0)
        except ProcessLookupError:
            return False
        return True


class _OwnerCancelled(Exception):
    pass


class ProcessSupervisor:
    """Execute finite commands and cancel their groups by owner ID.

    Use an instance on one asyncio event loop. Registration precedes spawning,
    so cancellation also reaches a process whose startup is still pending.
    The command deadline includes startup, exit, output pipes, and normal
    cleanup. At expiry cleanup sends SIGKILL and closes pipes without another
    unbounded wait. Direct task cancellation has a bounded cleanup grace.
    """

    def __init__(self) -> None:
        self._owners: dict[str, set[_OwnedProcess]] = {}
        self._spawns: set[asyncio.Task] = set()

    async def run_shell(
        self,
        command: str,
        *,
        owner_id: str,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int,
        on_output: Callable[[int, bytes], None] | None = None,
    ) -> ProcessResult:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        return await self.run(
            ("/bin/sh", "-c", command),
            owner_id=owner_id,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            on_output=on_output,
        )

    async def run(
        self,
        argv: Sequence[str],
        *,
        owner_id: str,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int,
        pass_fds: tuple[int, ...] = (),
        on_output: Callable[[int, bytes], None] | None = None,
    ) -> ProcessResult:
        raw = await self.run_bytes(
            argv,
            owner_id=owner_id,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            pass_fds=pass_fds,
            on_output=on_output,
        )
        notice = (
            f"[stderr] Command timed out after {timeout:g} seconds." if raw.timed_out else ""
        )
        output, truncated = _format_output(raw, max_output_bytes, notice)
        return ProcessResult(output, raw.exit_code, truncated, raw.timed_out, raw.cancelled)

    async def run_bytes(
        self,
        argv: Sequence[str],
        *,
        owner_id: str,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int,
        input_data: bytes | None = None,
        pass_fds: tuple[int, ...] = (),
        on_output: Callable[[int, bytes], None] | None = None,
    ) -> BinaryProcessResult:
        """Transfer finite bytes without decoding or inheriting standard input."""
        if isinstance(argv, (str, bytes)) or not argv or any(
            not isinstance(part, str) or not part for part in argv
        ):
            raise ValueError("argv must contain non-empty strings")
        if not owner_id:
            raise ValueError("owner_id must be non-empty")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if input_data is not None and not isinstance(input_data, bytes):
            raise ValueError("input_data must be finite bytes")
        if on_output is not None and not callable(on_output):
            raise ValueError("on_output must be an application callback")
        if any(type(descriptor) is not int or descriptor < 0 for descriptor in pass_fds):
            raise ValueError("pass_fds must contain explicitly selected descriptors")
        cwd = Path(cwd)
        if not cwd.is_absolute():
            raise ValueError("cwd must be an explicit absolute path")
        command_env = dict(env)
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in command_env.items()
        ):
            raise ValueError("env must contain string keys and values")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        owned = _OwnedProcess(max_output_bytes, input_data, on_output)
        self._owners.setdefault(owner_id, set()).add(owned)
        spawn = asyncio.create_task(
            loop.subprocess_exec(
                lambda: owned,
                *argv,
                cwd=str(cwd),
                env=command_env,
                stdin=(asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                pass_fds=pass_fds,
            )
        )
        self._spawns.add(spawn)
        spawn.add_done_callback(lambda task: self._spawn_finished(task, owned))
        cancellation = asyncio.create_task(owned.cancel_requested.wait())
        timed_out = False
        cancelled = False
        try:
            async with asyncio.timeout_at(deadline):
                await _wait_or_cancel(spawn, cancellation)
                await _wait_or_cancel(owned.completed, cancellation)
                if owned.error is not None:
                    raise owned.error
                await _cleanup(owned, deadline)
        except _OwnerCancelled:
            cancelled = True
            if await _shield_cleanup(
                owned, min(deadline, loop.time() + _CANCEL_CLEANUP_SECONDS)
            ):
                raise asyncio.CancelledError
        except TimeoutError:
            timed_out = True
            owned.force_close()
        except asyncio.CancelledError:
            await _shield_cleanup(
                owned, min(deadline, loop.time() + _CANCEL_CLEANUP_SECONDS)
            )
            raise
        except BaseException:
            owned.force_close()
            raise
        finally:
            cancellation.cancel()
            # A late startup is still owned: its protocol/callback immediately
            # kills its group. Do not cancel away the only startup handle.
            if not spawn.done():
                owned.force_close()
            self._owners[owner_id].discard(owned)
            if not self._owners[owner_id]:
                self._owners.pop(owner_id)
            owned.finished.set()

        returncode = owned.transport.get_returncode() if owned.transport else None
        exit_code = 124 if timed_out else (-signal.SIGTERM if cancelled else returncode)
        if exit_code is None:
            raise RuntimeError("process completed without an exit status")
        return BinaryProcessResult(
            bytes(owned.stdout), bytes(owned.stderr), int(exit_code),
            owned.truncated, timed_out, cancelled,
        )

    async def cancel_owner(self, owner_id: str) -> None:
        owned = tuple(self._owners.get(owner_id, ()))
        for process in owned:
            process.cancel_requested.set()
        await asyncio.gather(*(process.finished.wait() for process in owned))

    def _spawn_finished(self, task: asyncio.Task, owned: _OwnedProcess) -> None:
        self._spawns.discard(task)
        # Retrieve startup failures even if the command already timed out.
        with contextlib.suppress(BaseException):
            task.result()
        if owned.stop_requested:
            owned.force_close()


async def _wait_or_cancel(
    operation: asyncio.Future, cancellation: asyncio.Task
) -> None:
    await asyncio.wait((operation, cancellation), return_when=asyncio.FIRST_COMPLETED)
    if cancellation.done():
        raise _OwnerCancelled
    operation.result()


async def _cleanup(owned: _OwnedProcess, deadline: float) -> None:
    owned.stop_requested = True
    if owned.transport is None:
        owned.force_close()
        return
    loop = asyncio.get_running_loop()
    owned.signal(signal.SIGTERM)
    grace = min(deadline, loop.time() + _TERM_GRACE_SECONDS)
    while owned.group_exists() and loop.time() < grace:
        await asyncio.sleep(min(0.01, max(0, grace - loop.time())))
    owned.force_close()
    if not owned.completed.done() and loop.time() < deadline:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout_at(deadline):
                await asyncio.shield(owned.completed)


async def _shield_cleanup(owned: _OwnedProcess, deadline: float) -> bool:
    cleanup = asyncio.create_task(_cleanup(owned, deadline))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # Repeated Stop/task cancellation must not interrupt teardown.
            cancelled = True
            continue
    cleanup.result()
    return cancelled


def _format_output(
    raw: BinaryProcessResult, limit: int, notice: str
) -> tuple[str, bool]:
    parts: list[str] = []
    if raw.stdout:
        parts.append(raw.stdout.decode("utf-8", errors="replace").rstrip())
    if raw.stderr:
        stderr = raw.stderr.decode("utf-8", errors="replace").rstrip()
        parts.append("\n".join(f"[stderr] {line}" for line in stderr.splitlines()))
    encoded = "\n".join(parts).encode("utf-8")
    truncated = raw.truncated
    if notice:
        suffix = notice.encode("utf-8")
        available = max(0, limit - len(suffix) - 1)
        truncated |= len(encoded) > available or len(suffix) > limit
        prefix = encoded[:available].decode("utf-8", errors="ignore").encode("utf-8")
        encoded = prefix + (b"\n" if prefix else b"") + suffix
    truncated |= len(encoded) > limit
    return encoded[:limit].decode("utf-8", errors="ignore"), truncated
