"""Application-controlled Docker execution and validated session-source transfer."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path

from general_agent.coding.source import (
    ignored_source,
    ignored_source_parts,
    source_file,
    source_revision,
    source_snapshot,
    validate_source_path,
)
from general_agent.config import Settings
from general_agent.processes import BinaryProcessResult, ProcessResult, ProcessSupervisor
from general_agent.workspace import remove_workspace_tree, workspace_file

_CONTROLLER = "/opt/general-agent/controller.py"
_SETUP_CONTROLLER = "/opt/general-agent/setup_controller.py"
_MAX_FILE_BYTES = 5 * 1024 * 1024
_CONTROL_TIMEOUT = 10
_RUNTIME_VERSION = "3"
_NAMESPACE_LABEL = "io.general-agent.coding-namespace"
_OWNER_LABEL = "io.general-agent.coding-owner"


class RuntimeUnavailable(RuntimeError):
    pass


class SourceTransferError(RuntimeError):
    pass


def cleanup_owner_directories(settings: Settings, owner_id: str) -> int:
    """Remove only marked private mirrors/setup inputs for one owned attempt."""
    if not isinstance(owner_id, str) or not re.fullmatch(r"[0-9a-f]{32}", owner_id):
        raise ValueError("An application-generated owner is required.")
    candidates = []
    for prefix in ("local-runtime", "setup-input"):
        for candidate in settings.coding_root.glob(f"*/*/{prefix}-{owner_id}-*"):
            if len(candidates) >= 64:
                raise RuntimeUnavailable("Too many private directories belong to one attempt.")
            with workspace_file(settings.coding_root, candidate / ".owner.json", os.O_RDONLY) as descriptor:
                with os.fdopen(os.dup(descriptor), "rb") as reader:
                    marker = json.loads(reader.read(4097))
            if marker != {"owner": owner_id, "parent": str(candidate.parent)}:
                raise RuntimeUnavailable("An abandoned private directory failed its ownership check.")
            candidates.append(candidate)
    for candidate in candidates:
        remove_workspace_tree(settings.coding_root, candidate)
    return len(candidates)


class DockerRuntime:
    """Mirror only an isolated session copy into a finite, offline container.

    The application owns Docker arguments, image identity, and transfer policy.
    This adapter never executes a model command on the host or pulls an image.
    """

    def __init__(self, settings: Settings, repo: Path, owner_id: str) -> None:
        self.settings = settings
        self.repo = Path(repo)
        if not self.repo.is_absolute() or not self.repo.is_relative_to(settings.coding_root):
            raise ValueError("Coding runtime source must be an application-owned session copy.")
        if not isinstance(owner_id, str) or not re.fullmatch(r"[0-9a-f]{32}", owner_id):
            raise ValueError("Coding runtime requires an application-generated attempt ID.")
        self.owner_id = owner_id
        self._namespace = hashlib.sha256(os.fsencode(settings.project_root.resolve())).hexdigest()
        self.image_id: str | None = None
        self.browser_capable = False
        self.base_image_id: str | None = None
        self._dependency_identities: dict[str, str] = {}
        self._setup_manifests: dict[str, str] = {}
        self._installed_dependency_revision: str | None = None
        self._docker_path = shutil.which("docker")
        sockets = (Path("/var/run/docker.sock"), Path.home() / ".docker" / "run" / "docker.sock")
        self._socket = next((path for path in sockets if path.is_socket()), sockets[0])
        self._container = "general-agent-" + uuid.uuid4().hex
        self._created = False
        self._started = False
        self._primary_pid: int | None = None
        self._closed = False
        self._synced_revision: str | None = None
        self._tracked_paths: set[str] = set()
        self._supervisor = ProcessSupervisor()
        self._lock = asyncio.Lock()
        self._config = tempfile.TemporaryDirectory(prefix="general-agent-docker-")
        self.typescript_version = None

    @property
    def runtime_id(self) -> str | None:
        return self.image_id

    @property
    def _max_bytes(self) -> int:
        return self.settings.max_repository_mb * 1024 * 1024

    @property
    def identity(self) -> str | None:
        if self.image_id is None:
            return None
        parts = [self.image_id]
        if self._dependency_identities:
            parts.append("dependencies=" + ";".join(f"{kind}={value}" for kind, value in sorted(self._dependency_identities.items())))
        if self._installed_dependency_revision is not None:
            parts.append("installed=" + self._installed_dependency_revision)
        return ":".join(parts)

    @property
    def source_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._tracked_paths))

    @property
    def source_revision(self) -> str | None:
        return self._synced_revision

    def track_source(self, paths: tuple[str, ...]) -> None:
        validated = {validate_source_path(relative).as_posix() for relative in paths}
        self._tracked_paths.update(validated)

    @classmethod
    async def check_readiness(cls, settings: Settings) -> dict:
        runtime = cls(settings, settings.coding_root / "readiness", uuid.uuid4().hex)
        try:
            return await runtime.readiness()
        finally:
            await runtime.close()

    @classmethod
    async def cleanup_owner(cls, settings: Settings, owner_id: str) -> int:
        """Remove only containers for one abandoned, application-owned attempt."""
        runtime = cls(settings, settings.coding_root / "recovery", owner_id)
        try:
            result = await runtime._docker(
                "ps", "--all", "--no-trunc",
                "--filter", f"label={_NAMESPACE_LABEL}={runtime._namespace}",
                "--filter", f"label={_OWNER_LABEL}={owner_id}",
                "--format", "{{json .ID}}",
            )
            runtime._require_success(result, "list abandoned coding containers")
            identifiers = result.output.splitlines()
            if len(identifiers) > 64:
                raise RuntimeUnavailable("Too many coding containers for one attempt.")
            validated: list[str] = []
            for line in identifiers:
                container_id = json.loads(line)
                if not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{64}", container_id):
                    raise RuntimeUnavailable("Invalid abandoned coding container identity.")
                validated.append(container_id)
            if validated:
                inspected = await runtime._docker(
                    "container", "inspect", "--format",
                    '{"name":{{json .Name}},"labels":{{json .Config.Labels}}}',
                    "--", *validated, max_output_bytes=131_072,
                )
                runtime._require_success(inspected, "validate an abandoned coding container")
                records = inspected.output.splitlines()
                if len(records) != len(validated):
                    raise RuntimeUnavailable("Incomplete abandoned coding container ownership evidence.")
                for record in records:
                    info = json.loads(record)
                    labels = info.get("labels") or {}
                    if (
                        not re.fullmatch(r"/general-agent-[0-9a-f]{32}", info.get("name", ""))
                        or labels.get(_NAMESPACE_LABEL) != runtime._namespace
                        or labels.get(_OWNER_LABEL) != owner_id
                    ):
                        raise RuntimeUnavailable("An abandoned container failed application ownership validation.")
            # Validate the whole response before deleting any container.
            if validated:
                removed = await runtime._docker("rm", "--force", "--", *validated)
                runtime._require_success(removed, "remove abandoned coding containers")
            return len(validated) + cleanup_owner_directories(settings, owner_id)
        finally:
            await runtime.close()

    @property
    def _archive_limit(self) -> int:
        return self._max_bytes + self.settings.max_repository_files * 4_096 + 10_240

    def _snapshot(self, root: Path | None = None) -> dict:
        return source_snapshot(
            root or self.repo,
            max_files=self.settings.max_repository_files,
            max_bytes=self._max_bytes,
            max_file_bytes=_MAX_FILE_BYTES,
            tracked_paths=tuple(self._tracked_paths),
        )

    def _docker_argv(self, *arguments: str) -> tuple[str, ...]:
        if self._docker_path is None:
            raise RuntimeUnavailable("Docker is unavailable; coding execution cannot use the host.")
        return (
            self._docker_path,
            "--host", "unix://" + str(self._socket),
            "--config", self._config.name,
            *arguments,
        )

    async def _docker(
        self, *arguments: str, timeout: float = _CONTROL_TIMEOUT,
        max_output_bytes: int = 16_384, command: bool = False, on_output=None,
    ) -> ProcessResult:
        return await self._supervisor.run(
            self._docker_argv(*arguments),
            owner_id=self.owner_id + (":command" if command else ":control"),
            cwd=Path(self._config.name),
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            on_output=on_output,
        )

    async def _docker_bytes(
        self, *arguments: str, input_data: bytes | None = None,
        max_output_bytes: int | None = None, timeout: float = _CONTROL_TIMEOUT,
    ) -> BinaryProcessResult:
        return await self._supervisor.run_bytes(
            self._docker_argv(*arguments),
            owner_id=self.owner_id + ":transfer",
            cwd=Path(self._config.name),
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            timeout=timeout,
            max_output_bytes=max_output_bytes or self._archive_limit,
            input_data=input_data,
        )

    async def readiness(self) -> dict:
        errors: list[str] = []
        if self._docker_path is None:
            errors.append("Docker is not installed; coding commands never fall back to the host.")
        if not errors:
            try:
                daemon = await self._docker("info", "--format", "{{json .ServerVersion}}")
                if daemon.exit_code != 0 or daemon.truncated:
                    errors.append("The local Docker daemon is unavailable.")
                else:
                    template = (
                        '{"id":{{json .Id}},"os":{{json .Os}},'
                        '"labels":{{json .Config.Labels}},"volumes":{{json .Config.Volumes}}}'
                    )
                    image = await self._docker(
                        "image", "inspect", "--format", template, "--", self.settings.coding_image
                    )
                    if image.exit_code != 0 or image.truncated:
                        errors.append("The configured coding image is not installed. Build it explicitly.")
                    else:
                        info = json.loads(image.output)
                        if not re.fullmatch(r"sha256:[0-9a-f]{64}", info.get("id", "")):
                            errors.append("The coding image has no valid immutable identity.")
                        elif info.get("os") != "linux":
                            errors.append("The coding runtime requires a Linux image.")
                        elif info.get("volumes"):
                            errors.append("The coding image must not declare writable volumes.")
                        elif (info.get("labels") or {}).get("io.general-agent.coding-runtime") != _RUNTIME_VERSION:
                            errors.append("The coding image does not contain the supported runtime controller.")
                        else:
                            self.image_id = info["id"]
                            self.typescript_version = (info.get("labels") or {}).get("io.general-agent.coding-typescript")
                            self.browser_capable = (info.get("labels") or {}).get("io.general-agent.coding-browser") == "playwright-1.63.0"
                            if self.browser_capable:
                                base = (info.get("labels") or {}).get("io.general-agent.coding-base-image", "")
                                if not re.fullmatch(r"sha256:[0-9a-f]{64}", base):
                                    errors.append("The browser image must identify its exact immutable coding base.")
                                else:
                                    self.base_image_id = base
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"Coding runtime readiness failed: {exc}")
        return {"ready": not errors, "errors": errors, "runtime": "docker", "runtime_id": self.runtime_id,
                "image_id": self.image_id,
                "browser": self.browser_capable, "typescript_version": self.typescript_version}

    def _create_arguments(self) -> tuple[str, ...]:
        if self.image_id is None:
            raise RuntimeUnavailable("The coding image has not passed readiness.")
        memory = f"{self.settings.coding_memory_mb}m"
        scratch = f"/work:rw,size={self.settings.coding_storage_mb}m,uid=1000,gid=1000,mode=0700,nosuid,nodev"
        return (
            "create", "--name", self._container, "--pull=never", "--read-only",
            "--network=none", "--user=1000:1000", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit", str(self.settings.coding_pids),
            "--cpus=1", "--memory", memory, "--memory-swap", memory,
            "--tmpfs", scratch, "--ipc=none", "--ulimit=nofile=256:256",
            "--log-driver=none", "--init", "--entrypoint=/usr/local/bin/python",
            f"--label={_NAMESPACE_LABEL}={self._namespace}", f"--label={_OWNER_LABEL}={self.owner_id}",
            "--env=PATH=/work/deps/python/bin:/work/deps/node/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
            "--env=PYTHONPATH=/work/deps/python", "--env=PYTHONNOUSERSITE=1",
            "--env=PYTHONDONTWRITEBYTECODE=1", "--env=NODE_PATH=/work/deps/node/node_modules",
            "--env=HOME=/work/tmp/home", "--env=TMPDIR=/work/tmp",
            "--env=GOROOT=/usr/local/go", "--env=GOTOOLCHAIN=local", "--env=GOPROXY=off", "--env=GOSUMDB=off",
            "--env=GOPATH=/work/deps/go", "--env=GOCACHE=/work/tmp/go-build",
            "--env=RUSTUP_HOME=/usr/local/rustup", "--env=CARGO_HOME=/work/deps/cargo", "--env=CARGO_NET_OFFLINE=true",
            "--env=JAVA_HOME=/opt/java/openjdk",
            "--env=GENERAL_AGENT_REPO_DIR=/repo", "--env=GENERAL_AGENT_TEMP_DIR=/work/tmp",
            self.image_id, "-I", _CONTROLLER, "idle",
        )

    async def start(self) -> None:
        if self._closed:
            raise RuntimeUnavailable("This coding runtime is closed.")
        async with self._lock:
            if self._started:
                return
            self._snapshot()
            readiness = await self.readiness()
            if not readiness["ready"]:
                raise RuntimeUnavailable(" ".join(readiness["errors"]))
            try:
                # Creation can succeed in the daemon even if its CLI is cancelled.
                # Own the generated name before dispatch, so cleanup still runs.
                self._created = True
                created = await self._docker(*self._create_arguments())
                self._require_success(created, "create the coding container")
                self._require_success(await self._docker("start", self._container), "start the coding container")
                identity = await self._controller("identity")
                self._require_success(identity, "initialize the coding container")
                self._primary_pid = int(identity.output)
                if self._primary_pid <= 1:
                    raise RuntimeUnavailable("Invalid coding container process identity.")
                self._started = True
                await self._sync_to_locked()
                await self._refresh_dependency_identity()
            except BaseException:
                await _shielded(self._remove_container(), suppress_errors=True)
                raise

    def _require_started(self) -> None:
        if not self._started or self._closed:
            raise RuntimeUnavailable("The coding container is not running.")

    async def _controller(self, *arguments: str, **kwargs) -> ProcessResult:
        return await self._docker(
            "exec", "--user=1000:1000", self._container,
            "/usr/local/bin/python", "-I", _CONTROLLER, *arguments, **kwargs,
        )

    async def _package_controller(self, *arguments: str, **kwargs) -> ProcessResult:
        return await self._docker(
            "exec", "--user=1000:1000", self._container,
            "/usr/local/bin/python", "-I", _SETUP_CONTROLLER, *arguments, **kwargs,
        )

    async def _quiesce(self) -> None:
        if self._started and self._primary_pid is not None:
            result = await self._controller("quiesce", str(self._primary_pid))
            self._require_success(result, "stop coding command processes")

    async def _refresh_dependency_identity(self) -> None:
        # Failure must invalidate previous check evidence, even if the current
        # dependency inventory can no longer be read safely.
        self._installed_dependency_revision = "unavailable"
        result = await self._package_controller("dependency-identity", str(self.settings.coding_storage_mb * 1024 * 1024))
        self._require_success(result, "inspect installed dependencies")
        revision = result.output.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise RuntimeUnavailable("Invalid installed dependency identity.")
        self._installed_dependency_revision = revision

    async def sync_to_runtime(self) -> None:
        async with self._lock:
            self._require_started()
            await self._sync_to_locked()

    async def _sync_to_locked(self) -> None:
        await self._quiesce()
        snapshot = self._snapshot()
        archive = _pack_source(snapshot)
        if len(archive) > self._archive_limit:
            raise SourceTransferError("Source archive exceeds the transfer size limit.")
        result = await self._docker_bytes(
            "exec", "--interactive", "--user=1000:1000", self._container,
            "/usr/local/bin/python", "-I", _CONTROLLER, "import",
            str(self.settings.max_repository_files), str(self._max_bytes),
            json.dumps(ignored_source_parts()),
            input_data=archive, max_output_bytes=16_384,
        )
        self._require_success(result, "transfer source into the coding container")
        self._tracked_paths.update(snapshot)
        self._synced_revision = source_revision(snapshot)

    async def sync_from_runtime(self) -> None:
        async with self._lock:
            self._require_started()
            await self._sync_from_locked()

    async def run_preview(self, command: str, *, timeout: float, on_output) -> ProcessResult:
        """Stream a command in a private preview; never merge its source writes."""
        self._require_started()
        return await self._controller(
            "stream-execute", command, str(timeout), str(self.settings.max_command_output_bytes),
            timeout=timeout + 1, max_output_bytes=self.settings.max_command_output_bytes,
            command=True, on_output=on_output,
        )

    async def preview_revision(self) -> str:
        """Observe source drift without stopping a server or merging its writes."""
        self._require_started()
        result = await self._docker_bytes(
            "exec", "--user=1000:1000", self._container, "/usr/local/bin/python", "-I", _CONTROLLER,
            "export", str(self.settings.max_repository_files), str(self._max_bytes), json.dumps(ignored_source_parts()),
        )
        self._require_success(result, "inspect preview source")
        with tempfile.TemporaryDirectory(dir=self.repo.parent, prefix="preview-inspection-") as temporary:
            staged = Path(temporary)
            _unpack_source(result.stdout, staged, max_files=self.settings.max_repository_files, max_bytes=self._max_bytes)
            return source_revision(self._snapshot(staged))

    async def browser_probe(self, *, port: int, path: str, selector: str | None,
                            expected_text: str | None, timeout: float) -> bytes:
        self._require_started()
        if not self.browser_capable:
            raise RuntimeUnavailable("The selected preview image does not include the supported browser runtime.")
        result = await self._docker_bytes(
            "exec", "--user=1000:1000", self._container, "/usr/local/bin/python", "-I",
            "/opt/general-agent/browser_controller.py",
            json.dumps({"port": port, "path": path, "selector": selector, "expected_text": expected_text, "timeout": timeout}),
            timeout=timeout + 5, max_output_bytes=5 * 1024 * 1024 + 65_540,
        )
        self._require_success(result, "run the isolated browser check")
        return result.stdout

    async def language_probe(self, request: dict) -> dict:
        async with self._lock:
            self._require_started()
            if self.typescript_version != "5.9.3":
                raise RuntimeUnavailable("Rebuild the configured coding image with the supported TypeScript SDK.")
            await self._quiesce()
            content = json.dumps(request).encode()
            if len(content) > 3 * 1024 * 1024:
                raise ValueError("Language-service input exceeds its bound.")
            result = await self._docker_bytes(
                "exec", "--interactive", "--user=1000:1000", self._container,
                "/usr/local/bin/python", "-I", _CONTROLLER, "typescript",
                input_data=content, timeout=7, max_output_bytes=250000,
            )
            self._require_success(result, "inspect TypeScript source")
            response = json.loads(result.stdout)
            if not isinstance(response, dict) or response.get("protocol") != 1 or response.get("typescript_version") != self.typescript_version:
                raise RuntimeUnavailable("The language service returned an invalid SDK receipt.")
            return response

    async def install_setup(self, record: dict) -> ProcessResult:
        """Install a previously approved artifact offline, before running checks."""
        from general_agent.coding.setup import read_setup_artifact

        async with self._lock:
            self._require_started()
            await self._quiesce()
            compatible_image = self.image_id
            if self.browser_capable and record["runtime_id"] == self.base_image_id:
                compatible_image = self.base_image_id
            artifact = await asyncio.to_thread(read_setup_artifact, self.settings, self.repo, record, compatible_image)
            result = await self._docker_bytes(
                "exec", "--interactive", "--user=1000:1000", self._container,
                "/usr/local/bin/python", "-I", _SETUP_CONTROLLER, "package-import", record["kind"],
                str(self.settings.coding_storage_mb * 1024 * 1024),
                input_data=artifact, max_output_bytes=self.settings.max_command_output_bytes,
                timeout=self.settings.command_timeout_seconds,
            )
            self._require_success(result, "install the approved dependencies offline")
            self._dependency_identities[record["kind"]] = record["dependency_identity"]
            self._setup_manifests[record["kind"]] = record["manifest_identity"]
            await self._refresh_dependency_identity()
            output = result.stdout.decode("utf-8", errors="replace")
            if result.stderr:
                output += "\n[stderr] " + result.stderr.decode("utf-8", errors="replace")
            return ProcessResult(output, result.exit_code, result.truncated)

    async def _sync_from_locked(self) -> None:
        await self._quiesce()
        if source_revision(self._snapshot()) != self._synced_revision:
            raise SourceTransferError("The session source changed while the coding container was working.")
        result = await self._docker_bytes(
            "exec", "--user=1000:1000", self._container,
            "/usr/local/bin/python", "-I", _CONTROLLER, "export",
            str(self.settings.max_repository_files), str(self._max_bytes),
            json.dumps(ignored_source_parts()),
        )
        self._require_success(result, "export coding source")
        with tempfile.TemporaryDirectory(dir=self.repo.parent, prefix="coding-export-") as temporary:
            staged = Path(temporary) / "source"
            staged.mkdir()
            _unpack_source(
                result.stdout, staged,
                max_files=self.settings.max_repository_files, max_bytes=self._max_bytes,
            )
            snapshot = self._snapshot(staged)
            # Git-ignored new output may be eligible by filename while absent
            # from the source manifest. Do not retain unversioned extra bytes.
            approved = Path(temporary) / "approved"
            approved.mkdir()
            for relative, entry in snapshot.items():
                with source_file(approved, relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL, create_parents=True) as descriptor:
                    with os.fdopen(os.dup(descriptor), "wb") as writer:
                        writer.write(entry["content"])
                    os.fchmod(descriptor, entry["mode"])
            _replace_session_source(self.repo, approved)
        self._tracked_paths.update(snapshot)
        self._synced_revision = source_revision(snapshot)

    async def execute(self, command: str, timeout: float | None = None) -> ProcessResult:
        effective_timeout = timeout if timeout is not None else self.settings.command_timeout_seconds
        if not isinstance(command, str) or not command.strip() or effective_timeout <= 0:
            raise ValueError("A non-empty command and positive timeout are required.")
        async with self._lock:
            self._require_started()
            if self._setup_manifests:
                from general_agent.coding.setup import SetupBlocked, SetupManager

                for kind, identity in self._setup_manifests.items():
                    if SetupManager(self.settings)._inputs(self.repo, kind)[1] != identity:
                        raise SetupBlocked("Dependency manifests changed; explicitly prepare the environment before running commands.")
            try:
                await self._refresh_dependency_identity()
                result = await self._controller(
                    "execute", command, str(effective_timeout),
                    str(self.settings.max_command_output_bytes),
                    timeout=effective_timeout + 1,
                    max_output_bytes=self.settings.max_command_output_bytes * 6 + 4_096,
                    command=True,
                )
                if result.timed_out or result.cancelled:
                    response = ProcessResult(result.output, result.exit_code, result.truncated, result.timed_out, result.cancelled)
                else:
                    self._require_success(result, "run the coding controller")
                    response = _command_result(result.output, self.settings.max_command_output_bytes)
                await self._sync_from_locked()
                await self._refresh_dependency_identity()
                return response
            except asyncio.CancelledError:
                await _shielded(self._sync_from_locked())
                await _shielded(self._refresh_dependency_identity())
                raise
            except BaseException:
                # Capture permitted partial edits before runtime destruction.
                await _shielded(self._sync_from_locked(), suppress_errors=True)
                await _shielded(self._refresh_dependency_identity(), suppress_errors=True)
                raise

    async def cancel(self) -> None:
        await self._quiesce()
        await self._supervisor.cancel_owner(self.owner_id + ":command")

    async def _remove_container(self) -> None:
        if self._created:
            result = await self._docker("rm", "--force", self._container)
            if result.exit_code != 0 and "No such container" not in result.output:
                self._require_success(result, "remove the coding container")
            elif result.truncated:
                self._require_success(result, "remove the coding container")
            self._created = False
            self._started = False

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await _shielded(self._remove_container())
            self._closed = True
            self._config.cleanup()

    @staticmethod
    def _require_success(result: ProcessResult | BinaryProcessResult, action: str) -> None:
        if result.exit_code != 0 or result.truncated:
            raise RuntimeUnavailable(f"Unable to {action}; the operation failed or exceeded its output bound.")


def _pack_source(snapshot: dict) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for relative, entry in sorted(snapshot.items()):
            validate_source_path(relative)
            if entry["mode"] & 0o7000:
                raise SourceTransferError("Source cannot carry privileged permission bits.")
            member = tarfile.TarInfo(relative)
            member.size = len(entry["content"])
            member.mode = entry["mode"]
            member.uid = member.gid = 1000
            archive.addfile(member, io.BytesIO(entry["content"]))
    return output.getvalue()


def _unpack_source(data: bytes, destination: Path, *, max_files: int, max_bytes: int) -> None:
    total = 0
    files = 0
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for index, member in enumerate(archive):
                if index >= max_files * 4:
                    raise SourceTransferError("Export archive contains too many entries.")
                if member.name in {".", "./"} and member.isdir():
                    continue
                if ignored_source(member.name):
                    continue
                relative = validate_source_path(member.name).as_posix()
                if relative in seen:
                    raise SourceTransferError("Export archive contains duplicate source paths.")
                seen.add(relative)
                if member.isdir():
                    continue
                if not member.isfile() or member.sparse is not None or member.mode & 0o7000:
                    raise SourceTransferError("Export source must contain regular files without links or special modes.")
                files += 1
                total += member.size
                if member.size < 0 or member.size > _MAX_FILE_BYTES or files > max_files or total > max_bytes:
                    raise SourceTransferError("Export source exceeds the file or total size limit.")
                reader = archive.extractfile(member)
                if reader is None:
                    raise SourceTransferError("Export source has missing file data.")
                with reader:
                    content = reader.read(member.size + 1)
                if len(content) != member.size:
                    raise SourceTransferError("Export source has incomplete file data.")
                with source_file(destination, relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL, create_parents=True) as descriptor:
                    with os.fdopen(os.dup(descriptor), "wb") as writer:
                        writer.write(content)
                    os.fchmod(descriptor, member.mode & 0o777)
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise SourceTransferError(f"Invalid coding source export: {exc}") from exc


def _replace_session_source(repo: Path, staged: Path) -> None:
    backup = Path(tempfile.mkdtemp(dir=repo.parent, prefix="coding-old-source-"))
    backup.rmdir()
    os.replace(repo, backup)
    try:
        os.replace(staged, repo)
    except BaseException:
        os.replace(backup, repo)
        raise
    shutil.rmtree(backup)


def _command_result(output: str, limit: int) -> ProcessResult:
    try:
        envelope = json.loads(output)
        result = envelope["result"]
        if envelope["protocol"] != 1 or not isinstance(result["output"], str):
            raise ValueError("Invalid controller response")
        if len(result["output"].encode("utf-8")) > limit:
            raise ValueError("Controller output exceeds its bound")
        if type(result["exit_code"]) is not int or any(
            type(result[name]) is not bool for name in ("truncated", "timed_out", "cancelled")
        ):
            raise ValueError("Invalid controller exit metadata")
        return ProcessResult(**result)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeUnavailable("The coding controller returned invalid execution evidence.") from exc


async def _shielded(operation, *, suppress_errors: bool = False):
    """Finish bounded cleanup despite repeated cancellation and return its result."""
    task = asyncio.create_task(operation)
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            if not suppress_errors:
                raise
    if suppress_errors:
        with contextlib.suppress(Exception):
            return task.result()
    else:
        return task.result()
