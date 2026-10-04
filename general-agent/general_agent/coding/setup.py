"""Explicit, manifest-only dependency acquisition and immutable provenance."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from general_agent.coding.runtime import DockerRuntime, _SETUP_CONTROLLER, _shielded
from general_agent.coding.source import source_file, source_manifest, source_revision
from general_agent.coding.store import identifier, now
from general_agent.config import Settings
from general_agent.processes import BinaryProcessResult, ProcessResult, ProcessSupervisor
from general_agent.workspace import corp_storage_key, workspace_directory, workspace_file

MAX_PACKAGE_FILES = 50_000
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})(?=\s|$)")


class SetupBlocked(ValueError):
    pass


def _public_url(value: str, host: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https" and parsed.hostname == host
        and parsed.netloc == host and not parsed.query and not parsed.fragment
    )


def validate_requirements(content: bytes) -> bytes:
    """Parse pip syntax with packaging, allowing only exact, hashed packages."""
    lines = []
    for line in content.decode("utf-8").replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        hashes = _HASH.findall(line)
        package = _HASH.sub("", line).strip()
        if not hashes or package.startswith("-") or "--" in package:
            raise SetupBlocked("Python requirements must be exact versions with SHA256 hashes and no pip directives.")
        requirement = Requirement(package)
        versions = list(requirement.specifier)
        if requirement.url or len(versions) != 1 or versions[0].operator != "==" or "*" in versions[0].version:
            raise SetupBlocked("Python URL, editable, local, and unpinned dependencies are unsupported.")
        lines.append(str(requirement) + " " + " ".join(f"--hash=sha256:{value}" for value in sorted(set(hashes))))
    if not lines:
        raise SetupBlocked("No hash-pinned Python dependencies were selected.")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _validate_uv(project: bytes, lock: bytes) -> None:
    metadata, locked = tomllib.loads(project.decode()), tomllib.loads(lock.decode())
    definition = metadata.get("project", {})
    tool = metadata.get("tool", {})
    if not isinstance(definition, dict) or not isinstance(tool, dict) or not isinstance(tool.get("uv", {}), dict):
        raise SetupBlocked("Invalid Python project metadata.")
    if definition.get("dynamic") or tool.get("uv", {}).get("workspace"):
        raise SetupBlocked("Dynamic Python metadata and workspace layouts require unsupported local setup.")
    # Validate the declaration here; uv's offline lock check uses the runtime's
    # actual patch version rather than assuming that Python 3.11 means 3.11.0.
    requires_python = definition.get("requires-python", ">=3.11")
    if not isinstance(requires_python, str):
        raise SetupBlocked("Invalid Python version declaration.")
    SpecifierSet(requires_python)
    if not isinstance(definition.get("name"), str):
        raise SetupBlocked("Python project metadata requires a package name.")
    root_name = canonicalize_name(definition["name"])
    packages = locked.get("package", [])
    if not isinstance(packages, list):
        raise SetupBlocked("Invalid Python lockfile package inventory.")
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise SetupBlocked("Invalid Python lockfile package metadata.")
        source = package.get("source", {})
        if canonicalize_name(package.get("name", "")) == root_name and source in ({"editable": "."}, {"virtual": "."}):
            continue
        if source != {"registry": "https://pypi.org/simple"}:
            raise SetupBlocked("Only public PyPI registry dependencies are supported; local and private sources are blocked.")
        wheels = package.get("wheels", [])
        if not isinstance(wheels, list) or not wheels or any(
            not isinstance(wheel, dict)
            or not isinstance(wheel.get("hash"), str)
            or not _public_url(wheel.get("url", ""), "files.pythonhosted.org")
            or not urlsplit(wheel["url"]).path.endswith(".whl")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", wheel.get("hash", ""))
            for wheel in wheels
        ):
            raise SetupBlocked("Every selected Python package needs hashed public wheels; source builds are blocked online.")


def _validate_node(project: bytes, lock: bytes) -> None:
    metadata, locked = json.loads(project), json.loads(lock)
    if not isinstance(metadata, dict) or not isinstance(locked, dict):
        raise SetupBlocked("Node manifests must be JSON objects.")
    if metadata.get("workspaces") or locked.get("lockfileVersion") not in {2, 3}:
        raise SetupBlocked("Node setup requires a single project and package-lock version 2 or 3.")
    for field in ("dependencies", "devDependencies", "optionalDependencies"):
        dependencies = metadata.get(field, {})
        if not isinstance(dependencies, dict):
            raise SetupBlocked("Invalid Node dependency declarations.")
        for value in dependencies.values():
            if not isinstance(value, str) or re.search(r"(?:file:|link:|workspace:|git|https?:|[/\\])", value):
                raise SetupBlocked("Local, Git, URL, and workspace Node dependencies are unsupported.")
    packages = locked.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        raise SetupBlocked("The Node lockfile does not include its root package.")
    for name, package in packages.items():
        if not name:
            continue
        if not isinstance(package, dict) or not name.startswith("node_modules/") or ".." in PurePosixPath(name).parts or package.get("link"):
            raise SetupBlocked("The Node lockfile includes unsupported workspace or linked packages.")
        if not isinstance(package.get("integrity"), str) or not _public_url(package.get("resolved", ""), "registry.npmjs.org") or not re.fullmatch(
            r"sha(?:256|384|512)-[A-Za-z0-9+/]+={0,2}", package.get("integrity", "")
        ):
            raise SetupBlocked("Node packages must have integrity hashes and public npm registry URLs.")
    # npm's engine-strict setting enforces the runtime's actual Node version.


def validate_package_archive(data: bytes, kind: str, *, max_bytes: int, requirements: bytes | None = None) -> None:
    """Validate opaque dependency blobs without extracting them onto the host."""
    count, total = 0, 0
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            count += 1
            if (
                path.is_absolute() or not path.parts or ".." in path.parts or "\\" in member.name
                or path.as_posix() in seen or member.mode & 0o7000 or member.sparse is not None
                or count > MAX_PACKAGE_FILES
            ):
                raise SetupBlocked("Invalid dependency archive inventory.")
            seen.add(path.as_posix())
            if kind == "python":
                if path.as_posix() != "requirements.txt" and not (
                    len(path.parts) == 2 and path.parts[0] == "wheels" and path.name.endswith(".whl")
                ):
                    raise SetupBlocked("Python dependency artifacts contain only requirements and wheels.")
                if not member.isfile():
                    raise SetupBlocked("Python dependency artifacts refuse links and directories.")
                if path.as_posix() == "requirements.txt":
                    if member.size > 5 * 1024 * 1024:
                        raise SetupBlocked("Dependency requirements exceed their size limit.")
                    reader = archive.extractfile(member)
                    if reader is None:
                        raise SetupBlocked("Missing dependency requirements.")
                    with reader:
                        locked = validate_requirements(reader.read(member.size + 1))
                    if requirements is not None and locked != requirements:
                        raise SetupBlocked("Acquired dependency requirements differ from the approved lock.")
            elif kind == "node":
                if path.parts[0] != "node_modules":
                    raise SetupBlocked("Node dependency artifacts contain only node_modules.")
                if member.issym():
                    link = PurePosixPath(member.linkname)
                    depth = len(path.parent.parts)
                    if link.is_absolute() or "\\" in member.linkname:
                        raise SetupBlocked("Dependency symlinks must remain inside node_modules.")
                    for part in link.parts:
                        depth += -1 if part == ".." else 1 if part != "." else 0
                        if depth < 1:
                            raise SetupBlocked("Dependency symlinks must remain inside node_modules.")
                elif not (member.isfile() or member.isdir()):
                    raise SetupBlocked("Node dependency artifacts refuse hardlinks and special files.")
            else:
                raise SetupBlocked("Unknown dependency kind.")
            total += member.size
            if member.size < 0 or total > max_bytes:
                raise SetupBlocked("Dependency artifact exceeds its storage limit.")
    if kind == "python" and "requirements.txt" not in seen:
        raise SetupBlocked("Python dependency artifact is missing its locked requirements.")


class AcquisitionRuntime(DockerRuntime):
    """Only SetupManager's fixed acquisition commands use this online helper."""

    def _create_arguments(self) -> tuple[str, ...]:
        return tuple("--network=bridge" if value == "--network=none" else value for value in super()._create_arguments())

    async def package_bytes(self, *arguments: str, **kwargs) -> BinaryProcessResult:
        return await self._docker_bytes(
            "exec", "--interactive", "--user=1000:1000", self._container,
            "/usr/local/bin/python", "-I", _SETUP_CONTROLLER, *arguments, **kwargs,
        )


class LocalAcquisition:
    """Fixed package-manager commands over a private manifest-only host copy."""

    def __init__(self, settings: Settings, repo: Path, owner_id: str):
        self.settings, self.repo, self.owner_id = settings, repo, owner_id
        if not repo.is_absolute() or not repo.is_relative_to(settings.coding_root):
            raise SetupBlocked("Local dependency acquisition requires a private coding session directory.")
        if not re.fullmatch(r"[0-9a-f]{32}", owner_id):
            raise SetupBlocked("Invalid local dependency setup ID.")
        with workspace_directory(settings.coding_root, repo):
            pass
        self.runtime_id: str | None = None
        self._supervisor = ProcessSupervisor()
        self._tools: dict = {}
        self._config: Path | None = None

    async def start(self):
        from general_agent.coding.local_runtime import local_toolchain, local_toolchain_identity

        self._tools = await asyncio.to_thread(local_toolchain, self.settings)
        if not self._tools.get("python"):
            raise SetupBlocked("Local dependency setup requires an available Python interpreter.")
        if (self.repo / "uv.lock").exists() and not self._tools.get("uv"):
            raise SetupBlocked("Preparing uv.lock requires uv in the trusted local toolchain.")
        if (self.repo / "package-lock.json").exists() and not all(self._tools.get(name) for name in ("node", "npm")):
            raise SetupBlocked("Preparing Node dependencies requires Node and npm in the trusted local toolchain.")
        self.runtime_id = await asyncio.to_thread(local_toolchain_identity, self.settings)
        if not isinstance(self.runtime_id, str) or not self.runtime_id:
            raise SetupBlocked("Local dependency toolchain has no valid immutable identity.")
        root = self.repo.parent
        config = {"repo": str(self.repo), "acquired": str(root / "acquired"), "deps": str(root / "deps"),
                  "tmp": str(root / "tmp"), **{name: self._tools.get(name) for name in ("python", "uv", "node", "npm")}}
        for name in ("acquired", "deps", "tmp"):
            Path(config[name]).mkdir(mode=0o700)
        (Path(config["tmp"]) / "home").mkdir(mode=0o700)
        self._config = root / "controller.json"
        with self._config.open("x", encoding="utf-8") as stream:
            json.dump(config, stream)
        self._config.chmod(0o400)

    async def package_bytes(self, *arguments: str, **kwargs) -> BinaryProcessResult:
        from general_agent.coding.local_runtime import local_toolchain_identity, parent_death_command

        current_identity = await asyncio.to_thread(local_toolchain_identity, self.settings)
        if self._config is None or self.runtime_id != current_identity:
            raise SetupBlocked("Local dependency toolchain changed during preparation.")
        paths = [str(Path(value).parent) for value in self._tools.values() if value]
        env = {"PATH": os.pathsep.join(dict.fromkeys(paths + ["/usr/local/bin", "/usr/bin", "/bin"])),
               "HOME": str(self.repo.parent / "tmp/home"), "TMPDIR": str(self.repo.parent / "tmp"),
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        await asyncio.to_thread(self._storage_quota)
        command = [self._tools["python"], "-I", str(Path(__file__).with_name("setup_controller.py")),
                   "--local", str(self._config), *arguments]
        with parent_death_command(self._tools["python"], command, self._supervisor) as (argv, descriptors):
            process = asyncio.create_task(self._supervisor.run_bytes(
                argv, pass_fds=descriptors, owner_id=self.owner_id, cwd=self.repo, env=env,
                timeout=kwargs.pop("timeout", self.settings.command_timeout_seconds),
                max_output_bytes=kwargs.pop("max_output_bytes", self.settings.max_command_output_bytes), **kwargs,
            ))
            monitor = asyncio.create_task(self._watch_storage())
            try:
                done, _ = await asyncio.wait((process, monitor), return_when=asyncio.FIRST_COMPLETED)
                if monitor in done:
                    await monitor
                result = await process
                await asyncio.to_thread(self._storage_quota)
                return result
            finally:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
                if not process.done():
                    process.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await process

    def _storage_quota(self):
        """Bound intermediate package/cache writes without following symlinks."""
        total, visited = 0, 0
        pending = [self.repo.parent]
        while pending:
            directory = pending.pop()
            try:
                entries = os.scandir(directory)
            except FileNotFoundError:
                continue
            with entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_PACKAGE_FILES:
                        raise SetupBlocked("Local dependency preparation exceeds its inventory limit.")
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # package managers atomically rotate private cache entries
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                    elif not stat.S_ISLNK(info.st_mode):
                        raise SetupBlocked("Local dependency preparation refuses special files.")
                    if total > self.settings.coding_storage_mb * 1024 * 1024:
                        raise SetupBlocked("Local dependency preparation exceeds its storage limit.")

    async def _watch_storage(self):
        while True:
            await asyncio.sleep(0.1)
            await asyncio.to_thread(self._storage_quota)

    async def _package_controller(self, *arguments: str, **kwargs) -> ProcessResult:
        result = await self.package_bytes(*arguments, **kwargs)
        output = result.stdout.decode("utf-8", errors="replace")
        if result.stderr:
            output += "\n[stderr] " + result.stderr.decode("utf-8", errors="replace")
        return ProcessResult(output, result.exit_code, result.truncated, result.timed_out, result.cancelled)

    @staticmethod
    def _require_success(result: ProcessResult | BinaryProcessResult, action: str):
        if result.exit_code != 0 or result.truncated or result.timed_out or result.cancelled:
            raise SetupBlocked(f"Unable to {action}; the operation failed or exceeded its bound.")

    async def close(self):
        await self._supervisor.cancel_owner(self.owner_id)


class SetupManager:
    def __init__(self, settings: Settings, *, runtime_factory=None):
        self.settings = settings
        self.runtime_factory = runtime_factory or (LocalAcquisition if settings.coding_runtime == "local" else AcquisitionRuntime)

    def _session(self, corp_id: str, session_id: str, repo: Path) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise SetupBlocked("Invalid setup session ID.")
        directory = self.settings.coding_root / corp_storage_key(corp_id) / session_id
        if repo != directory / "repo":
            raise SetupBlocked("Dependency setup requires the selected corporation's isolated session source.")
        with workspace_directory(self.settings.coding_root, repo):
            pass
        return directory

    def _inputs(self, repo: Path, kind: str) -> tuple[dict, str]:
        def read(name: str) -> bytes:
            with source_file(repo, name) as descriptor:
                with os.fdopen(os.dup(descriptor), "rb") as stream:
                    data = stream.read(5 * 1024 * 1024 + 1)
            if len(data) > 5 * 1024 * 1024:
                raise SetupBlocked("A dependency manifest exceeds its size limit.")
            return data

        if kind == "python":
            try:
                lock = read("uv.lock")
            except FileNotFoundError:
                requirements = read("requirements.txt")
                validate_requirements(requirements)
                contents = {"requirements.txt": requirements}
            else:
                project = read("pyproject.toml")
                _validate_uv(project, lock)
                contents = {"pyproject.toml": project, "uv.lock": lock}
        elif kind == "node":
            project, lock = read("package.json"), read("package-lock.json")
            _validate_node(project, lock)
            contents = {"package.json": project, "package-lock.json": lock}
        else:
            raise SetupBlocked("Choose Python or Node dependency setup.")
        snapshot = {name: {"content": data, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": 0o644}
                    for name, data in contents.items()}
        return snapshot, source_revision(snapshot)

    def describe(self, corp_id: str, session_id: str, repo: Path, kind: str) -> dict:
        self._session(corp_id, session_id, repo)
        try:
            inputs, identity = self._inputs(repo, kind)
            return {"kind": kind, "ready": True, "files": sorted(inputs), "manifest_identity": identity,
                    "blockers": [], "network": (
                        "Public package acquisition in a private local manifest directory; installed packages stay in the selected session."
                        if self.settings.coding_runtime == "local" else
                        "Public package acquisition in a separate container; project commands stay offline."
                    )}
        except (OSError, ValueError) as exc:
            return {"kind": kind, "ready": False, "files": [], "manifest_identity": None, "blockers": [str(exc)]}

    async def prepare(self, corp_id: str, session_id: str, repo: Path, kind: str, *, setup_id: str | None = None) -> dict:
        directory = self._session(corp_id, session_id, repo)
        setup_id = identifier() if setup_id is None else setup_id
        if not re.fullmatch(r"[0-9a-f]{32}", setup_id):
            raise SetupBlocked("Invalid dependency setup ID.")
        record = {"id": setup_id, "corp_id": corp_id, "session_id": session_id, "kind": kind,
                  "created": now(), "status": "blocked", "manifest_identity": None, "runtime_id": None,
                  "dependency_identity": None, "artifact_path": None, "artifact_sha256": None,
                  "source_before": None, "source_after": None, "logs": "", "blockers": []}
        runtime = None
        try:
            inputs, identity = self._inputs(repo, kind)
            canonical = validate_requirements(inputs["requirements.txt"]["content"]) if "requirements.txt" in inputs else None
            record["manifest_identity"] = identity
            before = source_manifest(repo, max_files=self.settings.max_repository_files,
                                     max_bytes=self.settings.max_repository_mb * 1024 * 1024)
            record["source_before"] = source_revision(before)
            with tempfile.TemporaryDirectory(dir=directory, prefix=f"setup-input-{setup_id}-") as temporary:
                with workspace_file(self.settings.coding_root, Path(temporary) / ".owner.json",
                                    os.O_WRONLY | os.O_CREAT | os.O_EXCL) as descriptor:
                    os.write(descriptor, json.dumps({"owner": setup_id, "parent": str(directory)}).encode())
                manifests = Path(temporary) / "repo"
                manifests.mkdir()
                for name, entry in inputs.items():
                    with source_file(manifests, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as descriptor:
                        with os.fdopen(os.dup(descriptor), "wb") as stream:
                            stream.write(canonical if name == "requirements.txt" else entry["content"])
                runtime = self.runtime_factory(self.settings, manifests, setup_id)
                await runtime.start()
                record["runtime_id"] = runtime.runtime_id
                if "uv.lock" in inputs:
                    exported_requirements = await runtime._package_controller(
                        "export-python-requirements", timeout=self.settings.command_timeout_seconds,
                        max_output_bytes=self.settings.max_command_output_bytes,
                    )
                    record["logs"] = exported_requirements.output
                    runtime._require_success(exported_requirements, "check the Python lock and export requirements offline")
                    requirements = await runtime._package_controller("read-requirements", max_output_bytes=5 * 1024 * 1024)
                    runtime._require_success(requirements, "read the exported Python requirements")
                    canonical = validate_requirements(requirements.output.encode())
                    accepted = await runtime.package_bytes(
                        "set-requirements",
                        input_data=canonical, max_output_bytes=16_384,
                    )
                    runtime._require_success(accepted, "accept the validated Python requirements")
                action = "acquire-python" if kind == "python" else "acquire-node"
                result = await runtime._package_controller(action, timeout=self.settings.command_timeout_seconds,
                                                   max_output_bytes=self.settings.max_command_output_bytes)
                record["logs"] = (record["logs"] + "\n" + result.output).encode()[:self.settings.max_command_output_bytes].decode("utf-8", errors="ignore")
                runtime._require_success(result, "prepare locked dependencies")
                exported = await runtime.package_bytes(
                    "package-export", kind, str(self.settings.coding_storage_mb * 1024 * 1024),
                    max_output_bytes=self.settings.coding_storage_mb * 1024 * 1024 + MAX_PACKAGE_FILES * 1024,
                )
                runtime._require_success(exported, "export dependency artifacts")
                validate_package_archive(exported.stdout, kind, max_bytes=self.settings.coding_storage_mb * 1024 * 1024,
                                         requirements=canonical)
                if self._inputs(repo, kind)[1] != identity:
                    raise SetupBlocked("Dependency manifests changed during preparation; retry on the current files.")
                after = source_manifest(repo, tracked_paths=tuple(before), max_files=self.settings.max_repository_files,
                                        max_bytes=self.settings.max_repository_mb * 1024 * 1024)
                record["source_after"] = source_revision(after)
                if record["source_before"] != record["source_after"]:
                    raise SetupBlocked("Repository source changed during dependency preparation; retry on the current files.")
                artifact = directory / "setups" / setup_id / "packages.tar"
                with workspace_file(self.settings.coding_root, artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                    create_parents=True) as descriptor:
                    with os.fdopen(os.dup(descriptor), "wb") as stream:
                        stream.write(exported.stdout)
                        stream.flush()
                    os.fsync(descriptor)
                    os.fchmod(descriptor, 0o400)
                artifact_hash = hashlib.sha256(exported.stdout).hexdigest()
                provenance = f"{kind}:{identity}:{runtime.runtime_id}:{artifact_hash}"
                record.update(status="ready", artifact_path=str(artifact), artifact_sha256=artifact_hash,
                              dependency_identity="sha256:" + hashlib.sha256(provenance.encode()).hexdigest())
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, tarfile.TarError) as exc:
            record["blockers"] = [str(exc)]
        finally:
            if runtime is not None:
                await _shielded(runtime.close())
        return record


def read_setup_artifact(settings: Settings, repo: Path, record: dict, runtime_id: str) -> bytes:
    manager = SetupManager(settings)
    directory = manager._session(record["corp_id"], record["session_id"], repo)
    if record["status"] != "ready" or record["runtime_id"] != runtime_id:
        raise SetupBlocked("Dependency setup is unavailable or belongs to another runtime.")
    if manager._inputs(repo, record["kind"])[1] != record["manifest_identity"]:
        raise SetupBlocked("Dependency manifests changed after setup; prepare the selected environment again.")
    expected = directory / "setups" / record["id"] / "packages.tar"
    if not re.fullmatch(r"[0-9a-f]{32}", record["id"]) or record["artifact_path"] != str(expected):
        raise SetupBlocked("Invalid dependency artifact ownership.")
    limit = settings.coding_storage_mb * 1024 * 1024 + MAX_PACKAGE_FILES * 1024
    with workspace_file(settings.coding_root, expected, os.O_RDONLY) as descriptor:
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != record["artifact_sha256"]:
        raise SetupBlocked("Dependency artifact content changed or exceeded its bound.")
    provenance = f"{record['kind']}:{record['manifest_identity']}:{runtime_id}:{record['artifact_sha256']}"
    if record["dependency_identity"] != "sha256:" + hashlib.sha256(provenance.encode()).hexdigest():
        raise SetupBlocked("Invalid dependency artifact provenance.")
    validate_package_archive(data, record["kind"], max_bytes=settings.coding_storage_mb * 1024 * 1024)
    return data
