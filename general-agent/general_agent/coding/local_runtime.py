"""Trusted-host coding execution in a private, validated source mirror.

This protects the coding workflow's source copies and evidence boundaries; it
does not sandbox commands or restrict their host/network permissions.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from general_agent.coding.runtime import (
    RuntimeUnavailable, SourceTransferError, _pack_source, _replace_session_source,
    _shielded, _unpack_source, cleanup_owner_directories,
)
from general_agent.coding.source import (
    ignored_source, source_file, source_revision, source_snapshot, validate_source_path,
)
from general_agent.config import Settings
from general_agent.processes import ProcessResult, ProcessSupervisor
from general_agent.workspace import remove_workspace_tree, workspace_directory, workspace_file

_HERE = Path(__file__).parent
_WORKER = Path(__file__).absolute()
_TRUSTED_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
_ID = re.compile(r"[a-f0-9]{32}\Z")
_MAX_FILE_BYTES = 5 * 1024 * 1024


@contextlib.contextmanager
def parent_death_command(python: str, argv: list[str], supervisor: ProcessSupervisor):
    """Pass a lifetime handle to the fixed worker and safely retire its FDs."""
    read_descriptor, write_descriptor = os.pipe()
    try:
        yield ([python, "-I", str(_WORKER), "--worker", str(read_descriptor), json.dumps(argv)], (read_descriptor,))
    finally:
        os.close(write_descriptor)
        supervisor.release_descriptors((read_descriptor,))


def _browser_cache() -> str:
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return str(home / ("Library/Caches/ms-playwright" if sys.platform == "darwin" else ".cache/ms-playwright"))


def _operator_path() -> tuple[str, ...]:
    """Use the operator's absolute tool directories, without relative lookups."""
    return tuple(dict.fromkeys([str(Path(sys.executable).absolute().parent),
        *(part for part in os.environ.get("PATH", "").split(os.pathsep) if Path(part).is_absolute()),
        *_TRUSTED_PATH.split(os.pathsep)]))


def local_toolchain(settings: Settings) -> dict:
    """Resolve operator tools once per observation from absolute host paths."""
    python = str(Path(sys.executable).absolute())
    path = os.pathsep.join(_operator_path())
    tools = {name: shutil.which(name, path=path) for name in ("uv", "node", "npm")}
    if tools["uv"] is None:
        with contextlib.suppress(ImportError, FileNotFoundError):
            from uv import find_uv_bin
            tools["uv"] = find_uv_bin()
    return {"python": python, **tools}


def _file_digest(path: Path, *, max_bytes: int = 256 * 1024 * 1024) -> str:
    digest, size = hashlib.sha256(), 0
    with workspace_file(Path("/"), path, os.O_RDONLY) as descriptor:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise RuntimeUnavailable("A configured local tool exceeds its file bound.")
        with os.fdopen(os.dup(descriptor), "rb") as reader:
            for chunk in iter(lambda: reader.read(262_144), b""):
                size += len(chunk)
                if size > max_bytes:
                    raise RuntimeUnavailable("A configured local tool exceeds its file bound.")
                digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeUnavailable("A configured local tool changed during inspection.")
    return digest.hexdigest()


def _typescript_sdk(settings: Settings) -> Path | None:
    explicit = settings.coding_typescript_sdk
    path = explicit or settings.project_root / "tooling/coding/node_modules/typescript/lib/typescript.js"
    if explicit is None and not path.exists():
        return None
    if not path.is_absolute() or path.name != "typescript.js" or path.parent.name != "lib":
        raise RuntimeUnavailable("The TypeScript SDK must use an absolute operator-configured path.")
    with workspace_file(Path("/"), path.parent.parent / "package.json", os.O_RDONLY) as descriptor:
        with os.fdopen(os.dup(descriptor), "rb") as reader:
            metadata = json.loads(reader.read(16_385))
    if not isinstance(metadata, dict) or metadata.get("name") != "typescript" or metadata.get("version") != "5.9.3":
        raise RuntimeUnavailable("The local TypeScript SDK must be version 5.9.3.")
    _file_digest(path, max_bytes=20 * 1024 * 1024)
    return path


def local_toolchain_identity(settings: Settings) -> str:
    """Same bounded operator-tool fingerprint for runtime and acquisition."""
    tools = local_toolchain(settings)
    records = {name: {"path": value, "sha256": _file_digest(Path(value).resolve(strict=True))} if value else None
               for name, value in tools.items()}
    records["shell"] = _file_digest(Path("/bin/sh").resolve(strict=True))
    records["python_version"] = sys.version
    records["platform"] = platform.platform()
    records["operator_path"] = _operator_path()
    records["controllers"] = {name: _file_digest(_HERE / name) for name in (
        "local_runtime.py", "setup_controller.py", "typescript_controller.cjs", "browser_controller.py")}
    sdk = _typescript_sdk(settings)
    if sdk:
        libraries = sorted(sdk.parent.glob("lib*.d.ts"))
        if len(libraries) > 250:
            raise RuntimeUnavailable("The TypeScript standard library exceeds its inventory bound.")
        records["typescript"] = {"path": str(sdk), "sdk": _file_digest(sdk),
                                 "libraries": {path.name: _file_digest(path, max_bytes=2 * 1024 * 1024) for path in libraries}}
    else:
        records["typescript"] = None
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        records["playwright_version"] = importlib.metadata.version("playwright")
    return "local:" + hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LocalRuntime:
    """Execute with host permissions, reconcile only approved session source."""

    def __init__(self, settings: Settings, repo: Path, owner_id: str):
        self.settings, self.repo = settings, Path(repo)
        if not self.repo.is_absolute() or not self.repo.is_relative_to(settings.coding_root) or not _ID.fullmatch(owner_id):
            raise ValueError("Local execution requires an application-owned session copy and attempt ID.")
        self.owner_id = owner_id
        self.runtime_id: str | None = None
        self.browser_capable = False
        self.typescript_version: str | None = None
        self._private: Path | None = None
        self._exec_repo: Path | None = None
        self._python: Path | None = None
        self._config: Path | None = None
        self._tracked_paths: set[str] = set()
        self._synced_revision: str | None = None
        self._dependency_identities: dict[str, str] = {}
        self._setup_manifests: dict[str, str] = {}
        self._installed_revision: str | None = None
        self._started, self._closed = False, False
        self._supervisor = ProcessSupervisor()
        self._lock = asyncio.Lock()

    @property
    def identity(self):
        if self.runtime_id is None:
            return None
        return self.runtime_id + (":dependencies=" + ";".join(f"{kind}={value}" for kind, value in sorted(self._dependency_identities.items()))
                                 if self._dependency_identities else "") + ":installed=" + str(self._installed_revision)

    @property
    def source_paths(self):
        return tuple(sorted(self._tracked_paths))

    @property
    def source_revision(self):
        return self._synced_revision

    def track_source(self, paths):
        self._tracked_paths.update(validate_source_path(path).as_posix() for path in paths)

    @property
    def _max_bytes(self):
        return self.settings.max_repository_mb * 1024 * 1024

    def _snapshot(self, root: Path):
        return source_snapshot(root, max_files=self.settings.max_repository_files, max_bytes=self._max_bytes,
                               max_file_bytes=_MAX_FILE_BYTES, tracked_paths=self.source_paths)

    def _require_started(self):
        if not self._started or self._closed:
            raise RuntimeUnavailable("The local coding runtime is not running.")

    def _env(self, *, controller=False):
        assert self._private is not None
        tools = local_toolchain(self.settings)
        deps, temporary = self._private / "deps", self._private / "tmp"
        python = Path(tools["python"]) if controller else self._python
        path = ":".join(dict.fromkeys([str(python.parent), str(deps / "python/bin"), str(deps / "node/node_modules/.bin"),
                    *(str(Path(value).parent) for value in tools.values() if value), *_operator_path()]))
        return {"PATH": path, "HOME": str(temporary / "home"), "TMPDIR": str(temporary), "LANG": "C.UTF-8",
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(deps / "python"),
                "NODE_PATH": str(deps / "node/node_modules"), "PIP_TARGET": str(deps / "python"),
                "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CACHE_DIR": str(temporary / "pip"),
                "UV_CACHE_DIR": str(temporary / "uv"), "UV_PROJECT_ENVIRONMENT": str(self._private / "python"),
                "UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1", "UV_PYTHON": str(self._python),
                "NPM_CONFIG_USERCONFIG": "/dev/null", "NPM_CONFIG_CACHE": str(temporary / "npm"),
                "NPM_CONFIG_PREFIX": str(deps / "node-global"),
                "PLAYWRIGHT_BROWSERS_PATH": _browser_cache(),
                "GENERAL_AGENT_REPO_DIR": str(self._exec_repo), "GENERAL_AGENT_TEMP_DIR": str(temporary)}

    async def _run(self, argv, *, timeout, max_output_bytes, input_data=None, on_output=None, binary=False, controller=False):
        with parent_death_command(local_toolchain(self.settings)["python"], argv, self._supervisor) as (arguments, descriptors):
            options = {"owner_id": self.owner_id, "cwd": self._exec_repo,
                       "env": self._env(controller=controller), "timeout": timeout,
                       "max_output_bytes": max_output_bytes, "pass_fds": descriptors, "on_output": on_output}
            if binary:
                return await self._supervisor.run_bytes(arguments, input_data=input_data, **options)
            return await self._supervisor.run(arguments, **options)

    @classmethod
    async def check_readiness(cls, settings):
        try:
            runtime_id = await asyncio.to_thread(local_toolchain_identity, settings)
            sdk = await asyncio.to_thread(_typescript_sdk, settings)
            browser = await cls._browser_readiness(settings)
            return {"ready": True, "errors": [], "runtime": "local", "runtime_id": runtime_id,
                    "browser": browser, "typescript_version": "5.9.3" if sdk else None,
                    "trust": "Commands use this user's host and network permissions; this is not a sandbox."}
        except (OSError, ValueError, RuntimeError) as exc:
            return {"ready": False, "errors": [f"Local coding tools are unavailable: {exc}"], "runtime": "local", "runtime_id": None,
                    "browser": False, "typescript_version": None}

    @staticmethod
    async def _browser_readiness(settings):
        if importlib.util.find_spec("playwright") is None or shutil.which("lsof", path=_TRUSTED_PATH + ":/usr/sbin:/sbin") is None:
            return False
        try:
            if importlib.metadata.version("playwright") != "1.63.0":
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
        with tempfile.TemporaryDirectory(prefix="coding-browser-readiness-") as temporary:
            result = await ProcessSupervisor().run(
                [local_toolchain(settings)["python"], "-I", "-c",
                 "from playwright.sync_api import sync_playwright\nwith sync_playwright() as p: print(p.chromium.executable_path)"],
                owner_id=uuid.uuid4().hex, cwd=Path(temporary), timeout=5, max_output_bytes=4096,
                env={"PATH": _TRUSTED_PATH, "HOME": pwd.getpwuid(os.getuid()).pw_dir,
                     "TMPDIR": temporary, "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1", "PLAYWRIGHT_BROWSERS_PATH": _browser_cache()})
            return result.exit_code == 0 and not result.truncated and Path(result.output.strip()).is_file()

    async def readiness(self):
        result = await self.check_readiness(self.settings)
        if result["ready"]:
            self.runtime_id, self.browser_capable = result["runtime_id"], result["browser"]
            self.typescript_version = result["typescript_version"]
        return result

    @classmethod
    async def cleanup_owner(cls, settings, owner_id):
        # EOF handles terminate workers; never signal a persisted/reused PID.
        return await asyncio.to_thread(cleanup_owner_directories, settings, owner_id)

    async def start(self):
        if self._closed:
            raise RuntimeUnavailable("This local coding runtime is closed.")
        async with self._lock:
            if self._started:
                return
            snapshot = self._snapshot(self.repo)
            result = await self.readiness()
            if not result["ready"]:
                raise RuntimeUnavailable(" ".join(result["errors"]))
            with workspace_directory(self.settings.coding_root, self.repo.parent) as parent:
                name = f"local-runtime-{self.owner_id}-{uuid.uuid4().hex}"
                os.mkdir(name, mode=0o700, dir_fd=parent)
            self._private = self.repo.parent / name
            try:
                with workspace_file(self.settings.coding_root, self._private / ".owner.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL) as descriptor:
                    os.write(descriptor, json.dumps({"owner": self.owner_id, "parent": str(self.repo.parent)}).encode())
                for relative in ("repo", "deps", "acquired", "tmp/home"):
                    with workspace_directory(self._private, self._private / relative, create=True):
                        pass
                self._exec_repo = self._private / "repo"
                self._python = self._private / "python/bin/python"
                self._config = self._private / "setup.json"
                self._config.write_text(json.dumps({"repo": str(self._exec_repo), "deps": str(self._private / "deps"),
                    "acquired": str(self._private / "acquired"), "tmp": str(self._private / "tmp"), **local_toolchain(self.settings)}))
                created = await self._run([local_toolchain(self.settings)["python"], "-I", "-m", "venv", str(self._private / "python")],
                                           controller=True, timeout=15, max_output_bytes=4096)
                self._require_success(created, "create the private Python environment")
                self._python_config = _file_digest(self._private / "python/pyvenv.cfg")
                _unpack_source(_pack_source(snapshot), self._exec_repo, max_files=self.settings.max_repository_files, max_bytes=self._max_bytes)
                self._tracked_paths.update(snapshot)
                self._synced_revision = source_revision(snapshot)
                self._started = True
                await self._refresh_dependency_identity()
            except BaseException:
                await _shielded(self._cleanup(), suppress_errors=True)
                raise

    def _validate_export(self):
        visited = 0

        def walk(path):
            nonlocal visited
            with workspace_directory(self._private, path) as descriptor, os.scandir(descriptor) as entries:
                for entry in entries:
                    visited += 1
                    if visited > self.settings.max_repository_files * 4:
                        raise SourceTransferError("Local source export exceeds its inventory bound.")
                    selected = path / entry.name
                    relative = selected.relative_to(self._exec_repo).as_posix()
                    if ignored_source(relative):
                        continue
                    try:
                        validate_source_path(relative)
                    except ValueError:
                        raise SourceTransferError("Local command created a protected source path.") from None
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        walk(selected)
                    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o7000:
                        raise SourceTransferError("Local source export refuses links, aliases, and special files.")
        walk(self._exec_repo)

    async def _sync_to_locked(self):
        await self._supervisor.cancel_owner(self.owner_id)
        snapshot = self._snapshot(self.repo)
        with tempfile.TemporaryDirectory(dir=self._private, prefix="source-import-") as temporary:
            staged = Path(temporary) / "repo"
            staged.mkdir()
            _unpack_source(_pack_source(snapshot), staged, max_files=self.settings.max_repository_files, max_bytes=self._max_bytes)
            _replace_session_source(self._exec_repo, staged)
        self._restore_dependency_link()
        self._tracked_paths.update(snapshot)
        self._synced_revision = source_revision(snapshot)

    async def sync_to_runtime(self):
        async with self._lock:
            self._require_started()
            await self._sync_to_locked()

    async def _sync_from_locked(self):
        await self._supervisor.cancel_owner(self.owner_id)
        if source_revision(self._snapshot(self.repo)) != self._synced_revision:
            raise SourceTransferError("Session source changed while the local command was working.")
        self._validate_export()
        snapshot = self._snapshot(self._exec_repo)
        with tempfile.TemporaryDirectory(dir=self.repo.parent, prefix="local-export-") as temporary:
            staged = Path(temporary) / "repo"
            staged.mkdir()
            _unpack_source(_pack_source(snapshot), staged, max_files=self.settings.max_repository_files, max_bytes=self._max_bytes)
            _replace_session_source(self.repo, staged)
        self._tracked_paths.update(snapshot)
        self._synced_revision = source_revision(snapshot)

    async def sync_from_runtime(self):
        async with self._lock:
            self._require_started()
            await self._sync_from_locked()

    async def _refresh_dependency_identity(self):
        self._installed_revision = "unavailable"
        self.runtime_id = await asyncio.to_thread(local_toolchain_identity, self.settings)
        if _file_digest(self._private / "python/pyvenv.cfg") != self._python_config:
            raise RuntimeUnavailable("The private Python environment configuration changed.")
        result = await self._run([local_toolchain(self.settings)["python"], "-I", str(_HERE / "setup_controller.py"),
            "--local", str(self._config), "dependency-identity", str(self.settings.coding_storage_mb * 1024 * 1024)],
            binary=True, controller=True, timeout=10, max_output_bytes=4096)
        self._require_success(result, "inspect installed local dependencies")
        digest = result.stdout.decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise RuntimeUnavailable("The local dependency inventory returned an invalid identity.")
        python_libraries = self._private / "python/lib"
        libraries = await asyncio.to_thread(self._dependency_tree, python_libraries)
        self._installed_revision = hashlib.sha256((digest + ":" + libraries).encode()).hexdigest()

    def _dependency_tree(self, root: Path) -> str:
        digest, total, visited = hashlib.sha256(), 0, 0
        deadline = time.monotonic() + 10
        def walk(path):
            nonlocal total, visited
            with workspace_directory(self._private, path) as descriptor, os.scandir(descriptor) as entries:
                inventory = []
                for entry in entries:
                    visited += 1
                    if visited > 100_000 or time.monotonic() > deadline:
                        raise RuntimeUnavailable("Private Python dependencies exceed their inventory bound.")
                    inventory.append(entry)
                for entry in sorted(inventory, key=lambda value: value.name):
                    selected = path / entry.name
                    info = entry.stat(follow_symlinks=False)
                    relative = selected.relative_to(root).as_posix()
                    if stat.S_ISDIR(info.st_mode):
                        digest.update((relative + ":directory\n").encode())
                        walk(selected)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o7000:
                        total += info.st_size
                        if total > self.settings.coding_storage_mb * 1024 * 1024:
                            raise RuntimeUnavailable("Private Python dependencies exceed their storage bound.")
                        digest.update(json.dumps([relative, stat.S_IMODE(info.st_mode), _file_digest(selected)]).encode())
                    else:
                        raise RuntimeUnavailable("Private Python dependencies contain aliases or special files.")
        walk(root)
        return digest.hexdigest()

    def _restore_dependency_link(self):
        destination = self._private / "deps/node/node_modules"
        if destination.exists():
            with workspace_directory(self._private, destination), workspace_directory(self._private, self._exec_repo) as descriptor:
                try:
                    os.symlink(str(destination), "node_modules", dir_fd=descriptor, target_is_directory=True)
                except FileExistsError:
                    if os.readlink("node_modules", dir_fd=descriptor) != str(destination):
                        raise RuntimeUnavailable("The local dependency link differs from its prepared target.")

    async def execute(self, command, timeout=None):
        effective = timeout if timeout is not None else self.settings.command_timeout_seconds
        if not isinstance(command, str) or not command.strip() or len(command) > 16_384 or not math.isfinite(effective) or effective <= 0:
            raise ValueError("A bounded command and finite positive timeout are required.")
        async with self._lock:
            self._require_started()
            from general_agent.coding.setup import SetupBlocked, SetupManager
            for kind, identity in self._setup_manifests.items():
                if SetupManager(self.settings)._inputs(self.repo, kind)[1] != identity:
                    raise SetupBlocked("Dependency manifests changed; explicitly prepare them before running commands.")
            await self._refresh_dependency_identity()
            try:
                result = await self._run(["/bin/sh", "-c", command], timeout=effective,
                                         max_output_bytes=self.settings.max_command_output_bytes)
                await self._sync_from_locked()
                await self._refresh_dependency_identity()
                return result
            except asyncio.CancelledError:
                await _shielded(self._sync_from_locked())
                await _shielded(self._refresh_dependency_identity())
                raise
            except BaseException:
                await _shielded(self._sync_from_locked(), suppress_errors=True)
                await _shielded(self._refresh_dependency_identity(), suppress_errors=True)
                raise

    async def install_setup(self, record):
        from general_agent.coding.setup import read_setup_artifact
        async with self._lock:
            self._require_started()
            await self._refresh_dependency_identity()
            artifact = await asyncio.to_thread(read_setup_artifact, self.settings, self.repo, record, self.runtime_id)
            result = await self._run([local_toolchain(self.settings)["python"], "-I", str(_HERE / "setup_controller.py"),
                "--local", str(self._config), "package-import", record["kind"], str(self.settings.coding_storage_mb * 1024 * 1024)],
                binary=True, controller=True, input_data=artifact, timeout=self.settings.command_timeout_seconds,
                max_output_bytes=self.settings.max_command_output_bytes)
            self._require_success(result, "install explicitly prepared local dependencies")
            self._dependency_identities[record["kind"]] = record["dependency_identity"]
            self._setup_manifests[record["kind"]] = record["manifest_identity"]
            self._restore_dependency_link()
            await self._refresh_dependency_identity()
            return ProcessResult(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"), result.exit_code, result.truncated)

    async def language_probe(self, request):
        async with self._lock:
            self._require_started()
            sdk, tools = _typescript_sdk(self.settings), local_toolchain(self.settings)
            if sdk is None or tools["node"] is None:
                raise RuntimeUnavailable("Configure the local TypeScript 5.9.3 SDK and Node.js to inspect JavaScript/TypeScript.")
            content = json.dumps(request).encode()
            if len(content) > 3 * 1024 * 1024:
                raise ValueError("Language-service input exceeds its bound.")
            for document in request.get("documents", []):
                validate_source_path(document["path"])
            result = await self._run([tools["node"], "--max-old-space-size=192", str(_HERE / "typescript_controller.cjs"), str(sdk)],
                binary=True, controller=True, input_data=content, timeout=7, max_output_bytes=250_000)
            self._require_success(result, "inspect TypeScript source")
            response = json.loads(result.stdout)
            if not isinstance(response, dict) or response.get("protocol") != 1 or response.get("typescript_version") != "5.9.3":
                raise RuntimeUnavailable("The local language service returned invalid evidence.")
            return response

    async def run_preview(self, command, *, timeout, on_output):
        self._require_started()
        return await self._run(["/bin/sh", "-c", command], timeout=timeout,
                               max_output_bytes=self.settings.max_command_output_bytes, on_output=on_output)

    async def preview_revision(self):
        self._require_started()
        self._validate_export()
        return source_revision(self._snapshot(self._exec_repo))

    async def browser_probe(self, *, port, path, selector, expected_text, timeout):
        self._require_started()
        if not self.browser_capable:
            raise RuntimeUnavailable("Install the optional Playwright package and Chromium explicitly before browser checks.")
        await self._verify_listener(port)
        request = json.dumps({"port": port, "path": path, "selector": selector, "expected_text": expected_text, "timeout": timeout})
        result = await self._run([local_toolchain(self.settings)["python"], "-I", str(_HERE / "browser_controller.py"),
            "--local", str(self._private / "tmp"), request], binary=True, controller=True,
            timeout=timeout + 5, max_output_bytes=5 * 1024 * 1024 + 65_540)
        self._require_success(result, "check the owned local preview")
        await self._verify_listener(port)
        return result.stdout

    async def _verify_listener(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("A bounded owned preview port is required.")
        lsof = shutil.which("lsof", path=_TRUSTED_PATH + ":/usr/sbin:/sbin")
        if lsof is None:
            raise RuntimeUnavailable("Local browser checks require lsof to verify listener process ownership.")
        result = await self._supervisor.run([lsof, "-nP", "-a", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            owner_id=self.owner_id + ":ownership", cwd=self._exec_repo, env={"PATH": _TRUSTED_PATH}, timeout=2, max_output_bytes=4096)
        if result.exit_code != 0 or result.truncated:
            raise RuntimeUnavailable("The owned preview listener is unavailable.")
        groups = self._supervisor.process_groups(self.owner_id)
        try:
            fields = result.output.splitlines()
            listeners = [int(value[1:]) for value in fields if value.startswith("p")]
            addresses = [value[1:] for value in fields if value.startswith("n")]
            if not listeners or not addresses or any(address != f"127.0.0.1:{port}" for address in addresses) or any(os.getpgid(value) not in groups for value in listeners):
                raise RuntimeUnavailable("The requested listener belongs to another host process.")
        except (ValueError, ProcessLookupError):
            raise RuntimeUnavailable("The owned preview listener changed during inspection.") from None

    async def cancel(self):
        await self._supervisor.cancel_owner(self.owner_id)

    async def _cleanup(self):
        await self.cancel()
        if self._private is not None and self._private.exists():
            remove_workspace_tree(self.settings.coding_root, self._private)
        self._started = False

    async def close(self):
        async with self._lock:
            if self._closed:
                return
            await _shielded(self._cleanup())
            self._closed = True

    @staticmethod
    def _require_success(result, action):
        if result.exit_code != 0 or result.truncated or result.timed_out or result.cancelled:
            raise RuntimeUnavailable(f"Unable to {action}; operation failed or exceeded its bound.")


def _worker():
    """Watch a real inherited EOF handle; signal only this worker's own group."""
    descriptor, argv = int(sys.argv[2]), json.loads(sys.argv[3])
    if not isinstance(argv, list) or not argv or any(not isinstance(value, str) for value in argv):
        raise ValueError("Invalid application worker arguments.")

    def parent_death():
        while os.read(descriptor, 1):
            pass
        os.killpg(os.getpgrp(), 9)

    threading.Thread(target=parent_death, daemon=True).start()
    process = subprocess.Popen(argv, close_fds=True)
    raise SystemExit(process.wait())


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--worker":
    _worker()
