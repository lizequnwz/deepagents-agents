from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import os
import signal
import stat
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from general_agent.coding.runtime import (
    DockerRuntime,
    RuntimeUnavailable,
    SourceTransferError,
    _command_result,
)
from general_agent.processes import BinaryProcessResult, ProcessResult
from general_agent.coding import runtime_controller as controller

IMAGE_ID = "sha256:" + "a" * 64


def _archive(files: dict[str, bytes], *, link: tuple[str, bytes] | None = None) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
        if link:
            member = tarfile.TarInfo(link[0])
            member.type = tarfile.SYMTYPE
            member.linkname = link[1].decode()
            archive.addfile(member)
    return data.getvalue()


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.archive = _archive({})
        self.export_override = None
        self.block_execute = False
        self.execute_started = asyncio.Event()
        self.image_volumes = None
        self.fail_remove = False
        self.fail_create = False
        self.dependency_revision = "f" * 64
        self.revision_after_execute = None
        self.fail_fingerprint = False
        self.typescript_version = "5.9.3"

    async def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        arguments = argv[5:]
        if arguments[0] == "info":
            return ProcessResult('"29.0"', 0, False)
        if arguments[:2] == ("image", "inspect"):
            return ProcessResult(json.dumps({
                "id": IMAGE_ID, "os": "linux",
                "labels": {"io.general-agent.coding-runtime": "3", "io.general-agent.coding-typescript": self.typescript_version},
                "volumes": self.image_volumes,
            }), 0, False)
        if arguments[0] == "create" and self.fail_create:
            return ProcessResult("interrupted create", 124, False, timed_out=True)
        if arguments[0] == "rm" and self.fail_remove:
            return ProcessResult("daemon unavailable", 1, False)
        if "identity" in arguments:
            return ProcessResult("7", 0, False)
        if "dependency-identity" in arguments:
            return ProcessResult("unreadable", 1, False) if self.fail_fingerprint else ProcessResult(self.dependency_revision, 0, False)
        if "execute" in arguments:
            self.execute_started.set()
            if self.block_execute:
                await asyncio.Event().wait()
            if self.revision_after_execute:
                self.dependency_revision = self.revision_after_execute
            return ProcessResult(json.dumps({
                "protocol": 1,
                "result": dataclasses.asdict(ProcessResult("command output", 0, False)),
            }), 0, False)
        return ProcessResult("ok", 0, False)

    async def run_bytes(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        arguments = argv[5:]
        if "import" in arguments:
            self.archive = kwargs["input_data"]
            return BinaryProcessResult(b"", b"", 0, False)
        if "export" in arguments:
            content = self.export_override if self.export_override is not None else self.archive
            return BinaryProcessResult(content, b"", 0, False)
        if "typescript" in arguments:
            return BinaryProcessResult(json.dumps({"protocol": 1, "typescript_version": self.typescript_version,
                "symbols": [], "truncated": False}).encode(), b"", 0, False)
        raise AssertionError("Unexpected Docker transfer command")

    async def cancel_owner(self, owner_id):
        self.calls.append((("cancel", owner_id), {}))


@pytest.fixture
def runtime(settings, monkeypatch):
    monkeypatch.setattr("general_agent.coding.runtime.shutil.which", lambda name: "/usr/bin/docker")
    repo = settings.coding_root / "sessions" / "session-one" / "repo"
    repo.mkdir(parents=True)
    (repo / "main.py").write_text("original", encoding="utf-8")
    instance = DockerRuntime(settings, repo, "b" * 32)
    fake = FakeDocker()
    instance._supervisor = fake
    return instance, fake


@pytest.mark.asyncio
async def test_start_pins_image_and_applies_all_runtime_boundaries(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        created = next(argv[5:] for argv, _ in fake.calls if len(argv) > 5 and argv[5] == "create")
        assert IMAGE_ID in created
        assert instance.identity == IMAGE_ID + ":installed=" + "f" * 64
        for flag in (
            "--read-only", "--pull=never", "--network=none", "--user=1000:1000",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory",
            "--memory-swap", "--pids-limit", "--cpus=1", "--log-driver=none",
            "--init", "--ipc=none",
        ):
            assert flag in created
        assert "--mount" not in created and "--volume" not in created
        assert f"--label=io.general-agent.coding-owner={instance.owner_id}" in created
        assert f"--label=io.general-agent.coding-namespace={instance._namespace}" in created
        assert str(instance.repo) not in created
        scratch = created[created.index("--tmpfs") + 1]
        assert f"size={instance.settings.coding_storage_mb}m" in scratch
        assert "uid=1000,gid=1000" in scratch
        assert all("HOME" not in kwargs.get("env", {}) for _, kwargs in fake.calls)
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_missing_docker_is_a_blocker_before_any_host_command(settings, monkeypatch):
    monkeypatch.setattr("general_agent.coding.runtime.shutil.which", lambda name: None)
    result = await DockerRuntime.check_readiness(settings)
    assert not result["ready"]
    assert "never fall back" in " ".join(result["errors"])


@pytest.mark.asyncio
async def test_execution_exports_edits_and_deletions_before_return(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        fake.export_override = _archive({"replacement.py": b"changed", ".gitignore": b"dist/\n"})
        result = await instance.execute("printf 'model command'")
        assert result.exit_code == 0
        assert (instance.repo / "replacement.py").read_bytes() == b"changed"
        assert not (instance.repo / "main.py").exists()
        assert (instance.repo / ".gitignore").read_bytes() == b"dist/\n"
    finally:
        await instance.close()


@pytest.mark.parametrize("name", ("../escape.py", "/escape.py", ".env", ".git/config", ".unknown/config"))
@pytest.mark.asyncio
async def test_forbidden_export_preserves_the_entire_durable_source(runtime, name):
    instance, fake = runtime
    try:
        await instance.start()
        fake.export_override = _archive({"main.py": b"changed", name: b"untrusted"})
        with pytest.raises(SourceTransferError):
            await instance.sync_from_container()
        assert (instance.repo / "main.py").read_bytes() == b"original"
        assert sorted(path.name for path in instance.repo.iterdir()) == ["main.py"]
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_symlink_export_and_oversized_source_fail_before_replacement(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        fake.export_override = _archive({"main.py": b"changed"}, link=("alias", b"/etc/passwd"))
        with pytest.raises(SourceTransferError):
            await instance.sync_from_container()
        assert (instance.repo / "main.py").read_bytes() == b"original"
        fake.export_override = _archive({"large.py": b"x" * (5 * 1024 * 1024 + 1)})
        with pytest.raises(SourceTransferError):
            await instance.sync_from_container()
        assert (instance.repo / "main.py").read_bytes() == b"original"
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_export_conflicts_with_an_intervening_host_edit(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        (instance.repo / "main.py").write_text("user edit", encoding="utf-8")
        fake.export_override = _archive({"main.py": b"container edit"})
        with pytest.raises(SourceTransferError, match="changed while"):
            await instance.sync_from_container()
        assert (instance.repo / "main.py").read_bytes() == b"user edit"
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_cancel_captures_partial_source_then_cleanup_removes_runtime(runtime):
    instance, fake = runtime
    await instance.start()
    fake.export_override = _archive({"main.py": b"partial change"})
    fake.block_execute = True
    task = asyncio.create_task(instance.execute("sleep 30"))
    await asyncio.wait_for(fake.execute_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert (instance.repo / "main.py").read_bytes() == b"partial change"
    await instance.close()
    assert any("quiesce" in argv for argv, _ in fake.calls)
    assert any("rm" in argv and "--force" in argv for argv, _ in fake.calls)
    with pytest.raises(RuntimeUnavailable):
        await instance.execute("echo closed")


def test_controller_evidence_is_typed_and_output_bounded():
    with pytest.raises(RuntimeUnavailable):
        _command_result('{"protocol":1,"result":{"exit_code":0}}', 100)
    with pytest.raises(RuntimeUnavailable):
        _command_result(json.dumps({
            "protocol": 1,
            "result": dataclasses.asdict(ProcessResult("x" * 101, 0, False)),
        }), 100)


def test_original_repository_is_rejected_as_runtime_source(settings, tmp_path):
    with pytest.raises(ValueError, match="session copy"):
        DockerRuntime(settings, tmp_path, "b" * 32)


@pytest.mark.asyncio
async def test_images_with_writable_volumes_are_blocked(runtime):
    instance, fake = runtime
    fake.image_volumes = {"/unbounded": {}}
    try:
        result = await instance.readiness()
        assert not result["ready"]
        assert "writable volumes" in " ".join(result["errors"])
        assert not any("create" in argv for argv, _ in fake.calls)
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_failed_start_still_removes_the_owned_container(runtime):
    instance, fake = runtime
    fake.fail_create = True
    with pytest.raises(RuntimeUnavailable, match="create"):
        await instance.start()
    assert any("rm" in argv for argv, _ in fake.calls)
    assert not instance._created
    await instance.close()


@pytest.mark.asyncio
async def test_cleanup_failure_remains_retryable(runtime):
    instance, fake = runtime
    await instance.start()
    fake.fail_remove = True
    with pytest.raises(RuntimeUnavailable, match="remove"):
        await instance.close()
    assert not instance._closed and instance._created
    fake.fail_remove = False
    await instance.close()
    assert instance._closed and not instance._created


@pytest.mark.asyncio
async def test_new_ignored_output_is_not_retained_but_tracked_source_is(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        fake.export_override = _archive({
            "main.py": b"tracked change", "scratch.log": b"new generated output",
            ".gitignore": b"*.py\n*.log\n",
        })
        await instance.sync_from_container()
        assert (instance.repo / "main.py").read_bytes() == b"tracked change"
        assert not (instance.repo / "scratch.log").exists()
        assert (instance.repo / ".gitignore").exists()
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_recovery_requires_exact_application_and_attempt_ownership(settings, monkeypatch):
    monkeypatch.setattr("general_agent.coding.runtime.shutil.which", lambda _name: "/usr/bin/docker")
    calls = []
    wrong_labels = False
    malformed_id = False

    class RecoveryDocker:
        async def run(self, argv, **kwargs):
            calls.append(argv[5:])
            arguments = argv[5:]
            if arguments[0] == "ps":
                return ProcessResult(json.dumps("bad" if malformed_id else "c" * 64), 0, False)
            if arguments[:2] == ("container", "inspect"):
                return ProcessResult(json.dumps({
                    "name": "/general-agent-" + "d" * 32,
                    "labels": {
                        "io.general-agent.coding-namespace": "other" if wrong_labels else expected_namespace,
                        "io.general-agent.coding-owner": "b" * 32,
                    },
                }), 0, False)
            return ProcessResult("removed", 0, False)

    monkeypatch.setattr("general_agent.coding.runtime.ProcessSupervisor", RecoveryDocker)
    instance = DockerRuntime(settings, settings.coding_root / "readiness", "b" * 32)
    expected_namespace = instance._namespace
    await instance.close()
    assert await DockerRuntime.cleanup_owner(settings, "b" * 32) == 1
    query = next(call for call in calls if call[0] == "ps")
    assert f"label=io.general-agent.coding-namespace={expected_namespace}" in query
    assert "label=io.general-agent.coding-owner=" + "b" * 32 in query
    assert next(call for call in calls if call[0] == "rm") == ("rm", "--force", "--", "c" * 64)
    calls.clear()
    wrong_labels = True
    with pytest.raises(RuntimeUnavailable, match="ownership"):
        await DockerRuntime.cleanup_owner(settings, "b" * 32)
    assert not any(call[0] == "rm" for call in calls)
    calls.clear()
    malformed_id = True
    with pytest.raises(RuntimeUnavailable, match="identity"):
        await DockerRuntime.cleanup_owner(settings, "b" * 32)
    assert not any(call[0] == "rm" for call in calls)
    with pytest.raises(ValueError, match="attempt ID"):
        await DockerRuntime.cleanup_owner(settings, "label=other")


def test_container_source_transfer_and_cache_exclusion(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "obsolete.py").write_text("old")
    cached = repo / "node_modules"
    cached.mkdir()
    (cached / "package.js").write_text("dependency")
    monkeypatch.setattr(controller, "REPO", repo)
    output = io.BytesIO()
    monkeypatch.setattr(controller, "sys", SimpleNamespace(
        stdin=SimpleNamespace(buffer=io.BytesIO(_archive({"nested/source.py": b"new"}))),
        stdout=SimpleNamespace(buffer=output),
    ))
    controller._import(10, 100, {"node_modules"})
    assert not (repo / "obsolete.py").exists()
    assert (cached / "package.js").read_text() == "dependency"
    controller._export(10, 100, {"node_modules"})
    with tarfile.open(fileobj=io.BytesIO(output.getvalue())) as archive:
        assert archive.getnames() == ["nested/source.py"]
        assert archive.extractfile("nested/source.py").read() == b"new"


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "special_mode", "inventory", "size"))
def test_container_export_rejects_links_modes_and_resource_overflow(tmp_path, monkeypatch, kind):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(controller, "REPO", repo)
    monkeypatch.setattr(controller, "sys", SimpleNamespace(stdout=SimpleNamespace(buffer=io.BytesIO())))
    if kind == "symlink":
        (repo / "link").symlink_to(tmp_path)
    elif kind == "hardlink":
        (repo / "file.py").write_text("source")
        os.link(repo / "file.py", repo / "alias.py")
    elif kind == "special_mode":
        (repo / "file.py").write_text("source")
        # Some host sandbox filesystems strip setuid bits. Exercise the Linux
        # controller's privilege-mode check without depending on host mounts.
        monkeypatch.setattr(controller, "stat", SimpleNamespace(
            S_ISREG=stat.S_ISREG, S_IMODE=lambda _mode: 0o4644,
        ))
    elif kind == "inventory":
        for index in range(5):
            (repo / str(index)).mkdir()
    else:
        (repo / "file.py").write_text("x" * 101)
    with pytest.raises(ValueError):
        controller._export(1 if kind == "inventory" else 10, 100, set())


def test_container_quiesce_protects_only_application_primary_and_helper(monkeypatch):
    inventories = iter([
        [(1, "S"), (7, "S"), (42, "R"), (99, "S"), (100, "Z")],
        [(1, "S"), (7, "S"), (42, "R"), (100, "Z")],
    ])
    killed = []
    monkeypatch.setattr(controller, "_processes", lambda: next(inventories))
    monkeypatch.setattr(controller, "os", SimpleNamespace(getpid=lambda: 42, kill=lambda pid, sig: killed.append((pid, sig))))
    controller._quiesce(7)
    assert killed == [(99, signal.SIGKILL)]


def test_controller_descriptor_protection_is_required_and_fails_closed(monkeypatch):
    calls = []
    return_code = 0

    def prctl(*arguments):
        calls.append(arguments)
        return return_code

    monkeypatch.setattr(controller.ctypes, "CDLL", lambda *_args, **_kwargs: SimpleNamespace(prctl=prctl))
    controller._protect_controller()
    assert calls == [(4, 0, 0, 0, 0)]
    return_code = -1
    with pytest.raises(OSError, match="protect coding controller"):
        controller._protect_controller()


@pytest.mark.asyncio
async def test_offline_dependency_builds_change_environment_identity(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        before = instance.identity
        fake.revision_after_execute = "e" * 64
        await instance.execute("offline build")
        assert instance.identity != before
        assert instance.identity.endswith(":installed=" + "e" * 64)
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_unreadable_dependency_inventory_invalidates_previous_evidence(runtime):
    instance, fake = runtime
    try:
        await instance.start()
        before = instance.identity
        fake.fail_fingerprint = True
        with pytest.raises(RuntimeUnavailable, match="inspect installed"):
            await instance.execute("must not run")
        assert instance.identity != before and instance.identity.endswith(":installed=unavailable")
        assert not any("execute" in argv for argv, _ in fake.calls)
    finally:
        await instance.close()


async def test_language_probe_uses_fixed_offline_controller_and_sdk(runtime):
    instance, fake = runtime
    await instance.start()
    try:
        result = await instance.language_probe({"operation": "symbols", "documents": [
            {"path": "app.ts", "text": "export const count = 1;"}]})
        assert result["typescript_version"] == "5.9.3"
        argv, options = next((argv, options) for argv, options in fake.calls if "typescript" in argv)
        assert "/opt/general-agent/controller.py" in argv and "--user=1000:1000" in argv
        assert options["timeout"] == 7 and options["max_output_bytes"] == 250000
        assert json.loads(options["input_data"])["documents"][0]["path"] == "app.ts"
        created = next(argv for argv, _ in fake.calls if "create" in argv)
        assert "--network=none" in created
        for setting in ("--env=GOTOOLCHAIN=local", "--env=GOPROXY=off", "--env=CARGO_NET_OFFLINE=true",
                        "--env=GOCACHE=/work/tmp/go-build", "--env=JAVA_HOME=/opt/java/openjdk"):
            assert setting in created
        with pytest.raises(ValueError, match="bound"):
            await instance.language_probe({"oversized": "x" * (3 * 1024 * 1024)})
        instance.typescript_version = None
        with pytest.raises(RuntimeUnavailable, match="Rebuild"):
            await instance.language_probe({"operation": "symbols", "documents": []})
    finally:
        await instance.close()


async def test_repeated_cancellation_cannot_interrupt_cleanup_result():
    from general_agent.coding.runtime import _shielded

    entered, finished = asyncio.Event(), asyncio.Event()
    async def cleanup():
        entered.set()
        await finished.wait()
        return "immutable history ready"
    task = asyncio.create_task(_shielded(cleanup()))
    await entered.wait()
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    finished.set()
    assert await task == "immutable history ready"
