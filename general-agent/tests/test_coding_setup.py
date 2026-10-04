from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from general_agent.coding import setup_controller as controller
from general_agent.coding.runtime import DockerRuntime, RuntimeUnavailable
from general_agent.coding.setup import (
    AcquisitionRuntime, SetupBlocked, SetupManager, read_setup_artifact,
    validate_package_archive, validate_requirements,
)
from general_agent.processes import BinaryProcessResult, ProcessResult
from general_agent.workspace import corp_storage_key

CORP, SESSION = "A123456", "a" * 32
IMAGE = "sha256:" + "b" * 64
REQUIREMENTS = b"example==1.0 --hash=sha256:" + b"c" * 64 + b"\n"


def archive(files: dict[str, bytes], link: tuple[str, str] | None = None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as target:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), 0o644
            target.addfile(member, io.BytesIO(content))
        if link:
            member = tarfile.TarInfo(link[0])
            member.type, member.linkname = tarfile.SYMTYPE, link[1]
            target.addfile(member)
    return output.getvalue()


class FakeAcquisition:
    instances = []
    fail = False
    drift = None

    def __init__(self, settings, repo, owner_id):
        self.settings, self.repo, self.owner_id = settings, repo, owner_id
        self.image_id, self._container = IMAGE, "helper"
        self.calls, self.closed = [], False
        self.inputs = sorted(path.name for path in repo.iterdir())
        self.requirements = REQUIREMENTS
        self.instances.append(self)

    async def start(self):
        pass

    async def _package_controller(self, *arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        if arguments[0] == "read-requirements":
            return ProcessResult(self.requirements.decode(), 0, False)
        if self.fail:
            return ProcessResult("unavailable wheel", 1, False)
        return ProcessResult("prepared", 0, False)

    async def _docker_bytes(self, *arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        if "set-requirements" in arguments:
            self.requirements = kwargs["input_data"]
            return BinaryProcessResult(b"", b"", 0, False)
        if self.drift:
            self.drift.write_text("changed==2.0 --hash=sha256:" + "d" * 64)
        kind = arguments[-2]
        files = {"requirements.txt": self.requirements, "wheels/example-1.0-py3-none-any.whl": b"wheel"}
        if kind == "node":
            files = {"node_modules/example/index.js": b"dependency"}
        return BinaryProcessResult(archive(files), b"", 0, False)

    _require_success = staticmethod(DockerRuntime._require_success)

    async def close(self):
        self.closed = True


@pytest.fixture
def repo(settings):
    result = settings.coding_root / corp_storage_key(CORP) / SESSION / "repo"
    result.mkdir(parents=True)
    (result / "requirements.txt").write_bytes(REQUIREMENTS)
    (result / "main.py").write_text("private project source")
    (result / ".env").write_text("private credential")
    FakeAcquisition.instances.clear()
    FakeAcquisition.fail, FakeAcquisition.drift = False, None
    return result


def write_uv(repo):
    (repo / "pyproject.toml").write_text('[project]\nname="project"\nversion="1.0"\nrequires-python=">=3.11"\n')
    (repo / "uv.lock").write_text('''version = 1
[[package]]
name = "project"
version = "1.0"
source = { editable = "." }
[[package]]
name = "example"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.pythonhosted.org/packages/example.whl", hash = "sha256:''' + "c" * 64 + '" }]\n')


def write_node(repo):
    (repo / "package.json").write_text(json.dumps({"name": "project", "dependencies": {"example": "1.0.0"},
                                                  "scripts": {"postinstall": "private-project-hook"}}))
    (repo / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "project"}, "node_modules/example": {
            "version": "1.0.0", "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
            "integrity": "sha512-YWJjZA==",
        },
    }}))


@pytest.mark.parametrize("requirements", (
    b"example>=1.0", b"-e .", b"-r other.txt", b"--index-url https://private.example",
    b"example @ https://example.org/package.whl", b"example==1.* --hash=sha256:" + b"c" * 64,
    b"example==1.0 --hash=md5:123", b"example==1.0 --hash=sha256:" + b"c" * 64 + b" --extra-index-url=https://private.example",
))
def test_python_directives_unpinned_and_local_dependencies_are_blocked(requirements):
    with pytest.raises(ValueError):
        validate_requirements(requirements)


@pytest.mark.asyncio
async def test_prepare_is_manifest_only_and_artifact_is_owned_immutable_and_hashed(settings, repo):
    manager = SetupManager(settings, runtime_factory=FakeAcquisition)
    record = await manager.prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "ready"
    helper = FakeAcquisition.instances[0]
    assert helper.inputs == ["requirements.txt"] and helper.closed
    assert read_setup_artifact(settings, repo, record, IMAGE)
    artifact = Path(record["artifact_path"])
    assert artifact.stat().st_mode & 0o777 == 0o400
    altered = dict(record, artifact_path=str(repo / "main.py"))
    with pytest.raises(SetupBlocked, match="ownership"):
        read_setup_artifact(settings, repo, altered, IMAGE)
    with pytest.raises(SetupBlocked, match="image"):
        read_setup_artifact(settings, repo, record, "sha256:" + "e" * 64)
    with pytest.raises(SetupBlocked, match="corporation"):
        read_setup_artifact(settings, repo, dict(record, corp_id="OTHER"), IMAGE)
    (repo / "requirements.txt").write_bytes(REQUIREMENTS.replace(b"1.0", b"2.0"))
    with pytest.raises(SetupBlocked, match="changed after"):
        read_setup_artifact(settings, repo, record, IMAGE)


@pytest.mark.asyncio
async def test_uv_export_is_validated_before_acquisition_and_uses_only_manifests(settings, repo):
    write_uv(repo)
    record = await SetupManager(settings, runtime_factory=FakeAcquisition).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "ready"
    helper = FakeAcquisition.instances[0]
    assert helper.inputs == ["pyproject.toml", "uv.lock"]
    actions = [arguments[0] if arguments[0] != "exec" else "set-requirements" if "set-requirements" in arguments else "package-export"
               for arguments, _ in helper.calls]
    assert actions == ["export-python-requirements", "read-requirements", "set-requirements", "acquire-python", "package-export"]


@pytest.mark.asyncio
async def test_node_artifacts_are_acquired_without_project_source(settings, repo):
    write_node(repo)
    record = await SetupManager(settings, runtime_factory=FakeAcquisition).prepare(CORP, SESSION, repo, "node")
    assert record["status"] == "ready"
    assert FakeAcquisition.instances[0].inputs == ["package-lock.json", "package.json"]


@pytest.mark.asyncio
async def test_failed_acquisition_and_manifest_drift_do_not_publish_artifacts(settings, repo):
    manager = SetupManager(settings, runtime_factory=FakeAcquisition)
    FakeAcquisition.fail = True
    failed = await manager.prepare(CORP, SESSION, repo, "python")
    assert failed["status"] == "blocked" and not failed["artifact_path"]
    assert "unavailable wheel" in failed["logs"]
    FakeAcquisition.fail = False
    FakeAcquisition.drift = repo / "requirements.txt"
    stale = await manager.prepare(CORP, SESSION, repo, "python")
    assert stale["status"] == "blocked" and "changed during" in stale["blockers"][0]


def test_workspace_dynamic_and_private_packages_are_visible_blockers(settings, repo):
    manager = SetupManager(settings)
    write_uv(repo)
    (repo / "pyproject.toml").write_text('[project]\nname="project"\ndynamic=["version"]\n')
    assert not manager.describe(CORP, SESSION, repo, "python")["ready"]
    write_uv(repo)
    (repo / "uv.lock").write_text((repo / "uv.lock").read_text().replace("https://pypi.org/simple", "https://private.example/simple"))
    assert not manager.describe(CORP, SESSION, repo, "python")["ready"]
    write_node(repo)
    (repo / "package.json").write_text('{"workspaces":["packages/*"]}')
    assert not manager.describe(CORP, SESSION, repo, "node")["ready"]


@pytest.mark.parametrize("name", ("/absolute", "../escape", "node_modules/../../escape", "other/file"))
def test_dependency_archive_rejects_escapes_and_unexpected_roots(name):
    with pytest.raises(SetupBlocked):
        validate_package_archive(archive({name: b"data"}), "node", max_bytes=100)


def test_node_symlinks_stay_inside_dependency_root_and_python_requirements_match():
    valid = archive({"node_modules/package/bin.js": b"code"}, ("node_modules/.bin/command", "../package/bin.js"))
    validate_package_archive(valid, "node", max_bytes=100)
    invalid = archive({}, ("node_modules/.bin/command", "../../outside"))
    with pytest.raises(SetupBlocked, match="symlinks"):
        validate_package_archive(invalid, "node", max_bytes=100)
    with pytest.raises(SetupBlocked, match="differ"):
        validate_package_archive(archive({"requirements.txt": REQUIREMENTS}), "python", max_bytes=1024,
                                 requirements=REQUIREMENTS.replace(b"1.0", b"2.0"))


def test_only_acquisition_helper_enables_network(settings, repo):
    helper = AcquisitionRuntime(settings, repo, "f" * 32)
    offline = DockerRuntime(settings, repo, "e" * 32)
    helper.image_id = offline.image_id = IMAGE
    try:
        assert "--network=bridge" in helper._create_arguments()
        assert "--network=none" in offline._create_arguments()
        assert "--read-only" in helper._create_arguments()
    finally:
        helper._config.cleanup()
        offline._config.cleanup()


def test_container_acquisition_commands_are_fixed_no_builds_and_no_lifecycle_scripts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "REPO", tmp_path)
    monkeypatch.setattr(controller, "ACQUIRED", tmp_path / "acquired")
    (tmp_path / "requirements.txt").write_bytes(REQUIREMENTS)
    monkeypatch.setattr(controller, "_package_command", calls.append)
    controller._export_python_requirements()
    assert "--check" in calls[0] and "--offline" in calls[0] and "--no-build" in calls[0]
    assert "--frozen" in calls[1] and "--all-groups" in calls[1] and "--no-emit-local" in calls[1]
    controller._acquire_python()
    assert "--only-binary=:all:" in calls[2] and "--no-deps" in calls[2] and "--require-hashes" in calls[2]
    monkeypatch.setattr(controller.Path, "write_text", lambda *_args, **_kwargs: None)
    controller._acquire_node()
    assert "--ignore-scripts" in calls[3] and "--no-audit" in calls[3] and "--engine-strict" in calls[3]
    assert controller._package_environment()["PIP_CONFIG_FILE"] == "/dev/null"


@pytest.mark.asyncio
async def test_install_setup_is_offline_and_stale_manifests_block_commands(settings, repo, monkeypatch):
    record = await SetupManager(settings, runtime_factory=FakeAcquisition).prepare(CORP, SESSION, repo, "python")
    monkeypatch.setattr("general_agent.coding.runtime.shutil.which", lambda _name: "/usr/bin/docker")
    runtime = DockerRuntime(settings, repo, "e" * 32)
    runtime.image_id, runtime._started = IMAGE, True
    transfers = []

    async def transfer(*arguments, **kwargs):
        transfers.append((arguments, kwargs))
        return BinaryProcessResult(b"installed offline", b"", 0, False)

    async def command(*_args, **_kwargs):
        raise AssertionError("Stale dependencies must block before command execution")

    async def fingerprint(*_args, **_kwargs):
        return ProcessResult("f" * 64, 0, False)

    runtime._docker_bytes, runtime._controller, runtime._package_controller = transfer, command, fingerprint
    try:
        result = await runtime.install_setup(record)
        assert result.output == "installed offline"
        assert runtime.identity == IMAGE + ":dependencies=python=" + record["dependency_identity"] + ":installed=" + "f" * 64
        assert "package-import" in transfers[0][0]
        assert "--network=none" in runtime._create_arguments()
        (repo / "requirements.txt").write_bytes(REQUIREMENTS.replace(b"1.0", b"2.0"))
        with pytest.raises(SetupBlocked, match="manifests changed"):
            await runtime.execute("python -m pytest")
    finally:
        runtime._created = False
        await runtime.close()


@pytest.mark.asyncio
async def test_artifact_hash_and_provenance_are_revalidated(settings, repo):
    record = await SetupManager(settings, runtime_factory=FakeAcquisition).prepare(CORP, SESSION, repo, "python")
    with pytest.raises(SetupBlocked, match="provenance"):
        read_setup_artifact(settings, repo, dict(record, dependency_identity="sha256:" + "0" * 64), IMAGE)
    artifact = Path(record["artifact_path"])
    artifact.chmod(0o600)
    artifact.write_bytes(b"tampered")
    with pytest.raises(SetupBlocked, match="content changed"):
        read_setup_artifact(settings, repo, record, IMAGE)


@pytest.mark.asyncio
async def test_cancellation_always_closes_network_helper(settings, repo):
    entered = asyncio.Event()

    class Blocking(FakeAcquisition):
        async def _package_controller(self, *_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(SetupManager(settings, runtime_factory=Blocking).prepare(CORP, SESSION, repo, "python"))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert FakeAcquisition.instances[0].closed


async def test_repeated_stop_waits_for_network_helper_cleanup(settings, repo):
    acquired, closing, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Blocking(FakeAcquisition):
        async def _package_controller(self, *_args, **_kwargs):
            acquired.set()
            await asyncio.Event().wait()
        async def close(self):
            closing.set()
            await closed.wait()
            self.closed = True
    task = asyncio.create_task(SetupManager(settings, runtime_factory=Blocking).prepare(CORP, SESSION, repo, "python"))
    await acquired.wait()
    task.cancel()
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    closed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert FakeAcquisition.instances[0].closed


def test_node_dependency_restore_retains_relative_binary_symlinks_offline(tmp_path, monkeypatch):
    # Exercise the stdlib data filter on a real temporary directory, without
    # invoking any package installer or touching application state.
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(controller, "REPO", repo)
    original_path = controller.Path

    def mapped_path(value, *parts):
        raw = str(value)
        return original_path(tmp_path / "deps/node" if raw == "/work/deps/node" else value, *parts)

    monkeypatch.setattr(controller, "Path", mapped_path)
    package = archive({"node_modules/example/bin.js": b"source"}, ("node_modules/.bin/example", "../example/bin.js"))
    monkeypatch.setattr(controller, "sys", SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(package))))
    controller._package_import("node", 1024)
    assert (repo / "node_modules" / "example" / "bin.js").read_bytes() == b"source"
    assert (repo / "node_modules" / ".bin" / "example").read_bytes() == b"source"


def test_installed_environment_fingerprint_captures_builds_and_blocks_escapes(tmp_path, monkeypatch):
    deps = tmp_path / "deps"
    deps.mkdir()
    node = deps / "node"
    node.mkdir()
    (node / "module.js").write_text("before build")
    monkeypatch.setattr(controller, "DEPS", deps)
    before = controller._dependency_identity(100)
    (node / "module.js").write_text("after build")
    assert controller._dependency_identity(100) != before
    (node / "alias").symlink_to("module.js")
    assert controller._dependency_identity(100)
    with pytest.raises(ValueError, match="storage"):
        controller._dependency_identity(1)
    (node / "outside").symlink_to(tmp_path / "secret")
    with pytest.raises(ValueError, match="escape"):
        controller._dependency_identity(100)
