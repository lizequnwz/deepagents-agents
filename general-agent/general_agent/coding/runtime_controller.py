"""Read-only container-side controller; its arguments come from the application."""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import dataclasses
import importlib.util
import io
import json
import os
import shutil
import signal
import stat
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath

REPO = Path("/work/repo")


def _path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\x00" in name:
        raise ValueError("Invalid source archive path")
    return path


def _repo() -> None:
    if REPO.is_symlink() or not REPO.is_dir():
        raise ValueError("The source root is not a regular directory")


def _import(max_files: int, max_bytes: int, ignored: set[str]) -> None:
    _repo()
    for child in REPO.iterdir():
        # Preserve dependency directories, while invalidating generated output
        # and bytecode after every source synchronization.
        if child.name in ignored and child.name in {"node_modules", ".venv", "venv"}:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    total = 0
    files = 0
    seen: set[str] = set()
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for member in archive:
            path = _path(member.name)
            if not member.isfile() or member.sparse is not None or member.mode & 0o7000:
                raise ValueError("Source import accepts only regular files")
            if any(part in ignored for part in path.parts) or str(path) in seen:
                raise ValueError("Invalid or duplicate source import path")
            seen.add(str(path))
            files += 1
            total += member.size
            if files > max_files or total > max_bytes or member.size > 5 * 1024 * 1024:
                raise ValueError("Source import exceeds resource limits")
            destination = REPO.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            reader = archive.extractfile(member)
            if reader is None:
                raise ValueError("Missing source data")
            with reader:
                content = reader.read(member.size + 1)
            if len(content) != member.size:
                raise ValueError("Incomplete source data")
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as writer:
                writer.write(content)
                os.fchmod(writer.fileno(), member.mode & 0o777)


def _export(max_files: int, max_bytes: int, ignored: set[str]) -> None:
    _repo()
    files: list[tuple[Path, os.stat_result]] = []
    total = 0
    visited = 0
    for directory, names, filenames in os.walk(REPO, followlinks=False):
        names[:] = sorted(name for name in names if name not in ignored)
        visited += len(names) + len(filenames)
        if visited > max_files * 4:
            raise ValueError("Source export contains too many entries")
        candidates = [Path(directory) / name for name in filenames]
        for name in tuple(names):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                candidates.append(candidate)
                names.remove(name)
        for path in sorted(candidates):
            if any(part in ignored for part in path.relative_to(REPO).parts):
                continue
            info = path.lstat()
            total += info.st_size
            if len(files) >= max_files or total > max_bytes or info.st_size > 5 * 1024 * 1024:
                raise ValueError("Source export exceeds resource limits")
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o7000:
                raise ValueError("Source export refuses links and special files")
            files.append((path, info))
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for path, before in files:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as reader:
                current = os.fstat(reader.fileno())
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
                ):
                    raise ValueError("Source changed during export")
                content = reader.read(before.st_size + 1)
                after = os.fstat(reader.fileno())
            if len(content) != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                raise ValueError("Source changed during export")
            member = tarfile.TarInfo(path.relative_to(REPO).as_posix())
            member.size = len(content)
            member.mode = stat.S_IMODE(before.st_mode)
            archive.addfile(member, io.BytesIO(content))


def _processes() -> list[tuple[int, str]]:
    processes = []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            status = (path / "stat").read_text()
            state = status.rsplit(")", 1)[1].split()[0]
            if path.stat().st_uid == os.getuid():
                processes.append((int(path.name), state))
        except (OSError, ValueError, IndexError):
            continue
    return processes


def _identity() -> int:
    # The host captures this value before importing source or executing model
    # commands. Later workspace changes never redefine the protected process.
    return int(Path("/work/.primary-pid").read_text())


def _protect_controller() -> None:
    # Same-UID children must not reopen this process's stdout via /proc and
    # forge command evidence, or modify its memory with ptrace. This controller
    # always runs in Linux, and unsupported protection is a hard blocker.
    library = ctypes.CDLL(None, use_errno=True)
    library.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    library.prctl.restype = ctypes.c_int
    if library.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE, SUID_DUMP_DISABLE
        raise OSError(ctypes.get_errno(), "Unable to protect coding controller descriptors")


def _quiesce(primary: int) -> None:
    protected = {1, primary, os.getpid()}
    deadline = time.monotonic() + 1
    while True:
        active = [(pid, state) for pid, state in _processes() if pid not in protected and state != "Z"]
        if not active:
            return
        for pid, _state in active:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        if time.monotonic() >= deadline:
            raise ValueError("Unable to stop all coding command processes")
        time.sleep(0.01)


async def _execute(command: str, timeout: float, output_limit: int, *, stream: bool = False) -> None:
    spec = importlib.util.spec_from_file_location("coding_processes", "/opt/general-agent/processes.py")
    if spec is None or spec.loader is None:
        raise ValueError("Missing process supervisor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    environment = {
        name: os.environ[name]
        for name in (
            "PATH", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE",
            "NODE_PATH", "HOME", "TMPDIR", "GENERAL_AGENT_REPO_DIR", "GENERAL_AGENT_TEMP_DIR",
            "GOROOT", "GOTOOLCHAIN", "GOPROXY", "GOSUMDB", "GOPATH", "GOCACHE",
            "RUSTUP_HOME", "CARGO_HOME", "CARGO_NET_OFFLINE", "JAVA_HOME",
        )
        if name in os.environ
    }
    result = await module.ProcessSupervisor().run_shell(
        command, owner_id="command", cwd=REPO, env=environment,
        timeout=timeout, max_output_bytes=output_limit,
        on_output=(lambda fd, data: os.write(fd, data)) if stream else None,
    )
    if stream:
        raise SystemExit(result.exit_code if result.exit_code >= 0 else 128 - result.exit_code)
    print(json.dumps({"protocol": 1, "result": dataclasses.asdict(result)}, ensure_ascii=True))


async def _typescript() -> None:
    # The fixed SDK parses JSON snapshots. It never loads project plugins or executes source.
    spec = importlib.util.spec_from_file_location("coding_processes", "/opt/general-agent/processes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    content = sys.stdin.buffer.read(3 * 1024 * 1024 + 1)
    if len(content) > 3 * 1024 * 1024:
        raise ValueError("Navigation input exceeds its bound")
    result = await module.ProcessSupervisor().run_bytes(
        ("/usr/local/bin/node", "/opt/general-agent/typescript_controller.cjs"), owner_id="navigation",
        cwd=Path("/work/tmp"), env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        timeout=5, max_output_bytes=250000, input_data=content,
    )
    if result.exit_code != 0 or result.truncated:
        raise ValueError("TypeScript snapshot analysis failed or exceeded its bound")
    sys.stdout.buffer.write(result.stdout)


def main() -> None:
    _protect_controller()
    action = sys.argv[1]
    if action == "idle":
        for path in (REPO, Path("/work/tmp/home"), Path("/work/deps")):
            path.mkdir(parents=True, exist_ok=True)
        Path("/work/.primary-pid").write_text(str(os.getpid()))
        while True:
            time.sleep(3600)
    elif action == "identity":
        print(_identity())
    elif action == "quiesce":
        _quiesce(int(sys.argv[2]))
    elif action == "import":
        _import(int(sys.argv[2]), int(sys.argv[3]), set(json.loads(sys.argv[4])))
    elif action == "export":
        _export(int(sys.argv[2]), int(sys.argv[3]), set(json.loads(sys.argv[4])))
    elif action == "execute":
        _repo()
        asyncio.run(_execute(sys.argv[2], float(sys.argv[3]), int(sys.argv[4])))
    elif action == "stream-execute":
        _repo()
        asyncio.run(_execute(sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), stream=True))
    elif action == "typescript":
        asyncio.run(_typescript())
    else:
        raise ValueError("Unknown controller action")


if __name__ == "__main__":
    main()
