from __future__ import annotations

import asyncio
from contextlib import nullcontext
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from general_agent.coding import setup, setup_controller as controller
from general_agent.coding.setup import LocalAcquisition, SetupBlocked, SetupManager, read_setup_artifact
from general_agent.processes import BinaryProcessResult
from general_agent.processes import ProcessSupervisor
from general_agent.workspace import corp_storage_key
from tests.test_coding_setup import REQUIREMENTS, archive, write_node, write_uv


CORP, SESSION = "A123456", "a" * 32
RUNTIME = "local:sha256:" + "d" * 64


@pytest.fixture
def repo(settings):
    result = settings.coding_root / corp_storage_key(CORP) / SESSION / "repo"
    result.mkdir(parents=True)
    (result / "requirements.txt").write_bytes(REQUIREMENTS)
    (result / "main.py").write_text("private source")
    (result / ".env").write_text("private credential")
    return result


@pytest.fixture
def acquisition(monkeypatch):
    tools = {"python": "/trusted/python/bin/python", "uv": "/trusted/uv/bin/uv",
             "node": "/trusted/node/bin/node", "npm": "/trusted/npm/bin/npm"}
    state = {"identity": RUNTIME, "calls": [], "copied": [], "cancelled": [], "failure": False,
             "truncated": False, "drift": None, "block": None, "started": asyncio.Event()}
    module = SimpleNamespace(local_toolchain=lambda _settings: dict(tools),
                             local_toolchain_identity=lambda _settings: state["identity"],
                             parent_death_command=lambda python, argv, supervisor: nullcontext((argv, ())))
    monkeypatch.setitem(sys.modules, "general_agent.coding.local_runtime", module)

    class Supervisor:
        async def run_bytes(self, argv, **kwargs):
            config = json.loads(Path(argv[4]).read_text())
            action = argv[5]
            state["calls"].append((argv, kwargs, config))
            copied = Path(config["repo"])
            acquired = Path(config["acquired"])
            state["copied"].append(sorted(path.name for path in copied.iterdir()))
            if state["block"] is not None:
                state["started"].set()
                await state["block"].wait()
            if state["failure"]:
                return BinaryProcessResult(b"", b"unavailable wheel", 1, False)
            if state["truncated"]:
                return BinaryProcessResult(b"too much output", b"", 0, True)
            output = b"prepared"
            if action == "export-python-requirements":
                (acquired / "requirements.txt").write_bytes(REQUIREMENTS)
            elif action == "read-requirements":
                output = (acquired / "requirements.txt").read_bytes()
            elif action == "set-requirements":
                (acquired / "requirements.txt").write_bytes(kwargs["input_data"])
                output = b""
            elif action == "acquire-python":
                if not (acquired / "requirements.txt").exists():
                    (acquired / "requirements.txt").write_bytes((copied / "requirements.txt").read_bytes())
                (acquired / "wheels").mkdir()
                (acquired / "wheels/example-1.0-py3-none-any.whl").write_bytes(b"wheel")
            elif action == "acquire-node":
                target = copied / "node_modules/example"
                target.mkdir(parents=True)
                (target / "index.js").write_bytes(b"dependency")
            elif action == "package-export":
                kind = argv[6]
                root = acquired if kind == "python" else copied
                files = {path.relative_to(root).as_posix(): path.read_bytes()
                         for path in root.rglob("*") if path.is_file()
                         and (kind == "python" or path.is_relative_to(root / "node_modules"))}
                output = archive(files)
                if state["drift"] is not None:
                    state["drift"]()
            else:
                raise AssertionError(f"Unexpected package action: {action}")
            return BinaryProcessResult(output, b"", 0, False)

        async def cancel_owner(self, owner):
            state["cancelled"].append(owner)

    monkeypatch.setattr(setup, "ProcessSupervisor", Supervisor)
    return state, tools


async def test_local_python_preparation_copies_only_manifests_and_persists_immutable_artifact(settings, repo, acquisition, monkeypatch):
    state, _ = acquisition
    monkeypatch.setenv("OPENAI_API_KEY", "private-provider-key")
    monkeypatch.setenv("HTTP_PROXY", "http://secret:secret@localhost")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://private-packages.example/")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/private/injected.js")
    manager = SetupManager(settings)
    assert manager.runtime_factory is LocalAcquisition
    record = await manager.prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "ready" and not record["blockers"]
    assert record["runtime_id"] == RUNTIME and "image_id" not in record
    assert record["source_before"] == record["source_after"]
    assert record["dependency_identity"].startswith("sha256:")
    artifact = Path(record["artifact_path"])
    assert artifact.stat().st_mode & 0o777 == 0o400
    assert read_setup_artifact(settings, repo, record, RUNTIME)
    assert all(files == ["requirements.txt"] for files in state["copied"])
    assert (repo / "main.py").read_text() == "private source" and (repo / ".env").read_text() == "private credential"
    assert not (repo / "node_modules").exists() and not (repo / ".venv").exists()
    for argv, kwargs, config in state["calls"]:
        assert tuple(argv[:2]) == ("/trusted/python/bin/python", "-I")
        assert argv[3] == "--local" and kwargs["owner_id"] == record["id"]
        assert kwargs["cwd"] == Path(config["repo"])
        assert not any(name in kwargs["env"] for name in ("OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS", "PIP_EXTRA_INDEX_URL"))
        assert Path(config["repo"]).parent != repo.parent
        assert config["python"] == "/trusted/python/bin/python"
    assert state["cancelled"] == [record["id"]]
    assert not list(repo.parent.glob("setup-input-*"))


async def test_local_uv_exports_offline_before_hash_validated_wheel_acquisition(settings, repo, acquisition):
    state, _ = acquisition
    write_uv(repo)
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "ready"
    assert [argv[5] for argv, _, _ in state["calls"]] == [
        "export-python-requirements", "read-requirements", "set-requirements", "acquire-python", "package-export",
    ]
    assert all(files == ["pyproject.toml", "uv.lock"] for files in state["copied"])
    assert state["calls"][2][1]["input_data"] == REQUIREMENTS


async def test_local_node_preparation_packages_only_node_modules(settings, repo, acquisition):
    state, _ = acquisition
    write_node(repo)
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "node")
    assert record["status"] == "ready"
    assert state["copied"][0] == ["package-lock.json", "package.json"]
    with tarfile.open(fileobj=io.BytesIO(read_setup_artifact(settings, repo, record, RUNTIME))) as packages:
        assert packages.getnames() == ["node_modules/example/index.js"]
    assert not (repo / "node_modules").exists()


@pytest.mark.parametrize("kind,missing,writer", [("python", "python", None), ("python", "uv", write_uv),
                                              ("node", "node", write_node), ("node", "npm", write_node)])
async def test_missing_required_local_tool_blocks_before_acquisition(settings, repo, acquisition, kind, missing, writer):
    state, tools = acquisition
    tools[missing] = None
    if writer:
        writer(repo)
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, kind)
    assert record["status"] == "blocked" and record["blockers"]
    assert not state["calls"] and not list(repo.parent.glob("setup-input-*"))


async def test_requirements_only_local_setup_does_not_require_uv_node_or_npm(settings, repo, acquisition):
    state, tools = acquisition
    tools.update(uv=None, node=None, npm=None)
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "ready" and state["calls"]


@pytest.mark.parametrize("failure", ["failure", "truncated"])
async def test_local_acquisition_failure_leaves_no_accepted_artifact(settings, repo, acquisition, failure):
    state, _ = acquisition
    state[failure] = True
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "blocked" and record["artifact_path"] is None
    assert state["cancelled"] == [record["id"]]
    assert not list(repo.parent.glob("setup-input-*"))


async def test_local_preparation_blocks_if_source_or_lock_drifts(settings, repo, acquisition):
    state, _ = acquisition
    state["drift"] = lambda: (repo / "main.py").write_text("newer user edit")
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "blocked" and "source changed" in record["blockers"][0]
    assert record["source_before"] != record["source_after"]
    assert (repo / "main.py").read_text() == "newer user edit"
    state["drift"] = lambda: (repo / "requirements.txt").write_bytes(REQUIREMENTS.replace(b"1.0", b"2.0"))
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "blocked" and "manifests changed" in record["blockers"][0]


async def test_local_toolchain_changes_block_export_and_other_runtime_cannot_use_artifact(settings, repo, acquisition):
    state, _ = acquisition
    original = setup.LocalAcquisition._package_controller

    async def changed(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        state["identity"] = "local:changed"
        return result

    from unittest.mock import patch
    with patch.object(setup.LocalAcquisition, "_package_controller", changed):
        record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "blocked" and "toolchain changed" in record["blockers"][0]
    state["identity"] = RUNTIME
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    with pytest.raises(SetupBlocked, match="another runtime"):
        read_setup_artifact(settings, repo, record, "local:other")


async def test_local_preparation_cancellation_stops_owned_processes_and_cleans_private_inputs(settings, repo, acquisition):
    state, _ = acquisition
    state["block"] = asyncio.Event()
    task = asyncio.create_task(SetupManager(settings).prepare(CORP, SESSION, repo, "python", setup_id="b" * 32))
    await asyncio.wait_for(state["started"].wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["cancelled"] == ["b" * 32]
    assert not list(repo.parent.glob("setup-input-*"))


@pytest.mark.parametrize("flags", [{"timed_out": True}, {"cancelled": True}, {"truncated": True}])
def test_cancelled_timed_out_or_truncated_local_preparation_is_not_success(flags):
    with pytest.raises(SetupBlocked):
        LocalAcquisition._require_success(BinaryProcessResult(b"", b"", 0, flags.pop("truncated", False), **flags), "prepare dependencies")


def local_config(tmp_path, monkeypatch, **overrides):
    for name in ("REPO", "ACQUIRED", "DEPS", "TMP", "PYTHON", "UV", "NODE", "NPM", "LOCAL"):
        monkeypatch.setattr(controller, name, getattr(controller, name))
    config = {name: str(tmp_path / name) for name in ("repo", "acquired", "deps", "tmp")}
    config.update(python=sys.executable, uv="/trusted/uv/bin/uv", node="/trusted/node/bin/node", npm="/trusted/npm/bin/npm")
    config.update(overrides)
    Path(config["repo"]).mkdir(exist_ok=True)
    Path(config["deps"]).mkdir(exist_ok=True)
    path = tmp_path / "controller.json"
    path.write_text(json.dumps(config))
    return config, path


def test_local_controller_has_explicit_clean_env_and_fixed_no_build_lifecycle_commands(tmp_path, monkeypatch):
    config, path = local_config(tmp_path, monkeypatch)
    controller.configure_local(path)
    (controller.REPO / "requirements.txt").write_bytes(REQUIREMENTS)
    calls = []
    monkeypatch.setattr(controller, "_package_command", calls.append)
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", "/private/npmrc")
    monkeypatch.setenv("UV_INDEX_URL", "https://private-registry.example")
    controller._export_python_requirements()
    controller._acquire_python()
    controller._acquire_node()
    assert calls[0][0] == config["uv"] and calls[0][calls[0].index("--python") + 1] == config["python"]
    assert "--offline" in calls[0] and "--no-build" in calls[0] and "--no-python-downloads" in calls[0]
    assert "--frozen" in calls[1] and "--no-emit-project" in calls[1]
    assert calls[2][0] == config["python"] and "--only-binary=:all:" in calls[2]
    assert "--require-hashes" in calls[2] and "--no-deps" in calls[2] and "download" in calls[2]
    assert "--keyring-provider=disabled" in calls[2] and "--no-input" in calls[2]
    assert calls[3][0] == config["npm"] and "--ignore-scripts" in calls[3]
    assert "--engine-strict" in calls[3] and "--no-audit" in calls[3]
    env = controller._package_environment()
    assert env["HOME"] == str(Path(config["tmp"]) / "home")
    assert env["PATH"].startswith("/trusted/node/bin:")
    assert env["PIP_CONFIG_FILE"] == os.devnull and env["UV_NO_CONFIG"] == "1"
    assert "UV_INDEX_URL" not in env and "NPM_CONFIG_USERCONFIG" not in env
    assert not list(tmp_path.glob("**/.venv"))


def test_local_controller_imports_python_offline_only_into_private_target(tmp_path, monkeypatch):
    config, path = local_config(tmp_path, monkeypatch, uv=None, node=None, npm=None)
    controller.configure_local(path)
    contents = archive({"requirements.txt": REQUIREMENTS, "wheels/example-1.0-py3-none-any.whl": b"wheel"})
    monkeypatch.setattr(controller.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(contents)))
    calls = []
    monkeypatch.setattr(controller, "_package_command", calls.append)
    controller._package_import("python", 1024)
    assert len(calls) == 1
    command = calls[0]
    assert command[0] == config["python"] and "--no-index" in command and "--no-compile" in command
    assert "--only-binary=:all:" in command and "--require-hashes" in command
    assert "--keyring-provider=disabled" in command and "--no-input" in command
    assert command[command.index("--target") + 1] == str(Path(config["deps"]) / "python")
    assert not Path(config["acquired"]).exists()


def test_local_controller_imports_node_under_session_deps_without_lifecycle_execution(tmp_path, monkeypatch):
    config, path = local_config(tmp_path, monkeypatch)
    controller.configure_local(path)
    contents = archive({"node_modules/example/index.js": b"dependency"})
    monkeypatch.setattr(controller.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(contents)))
    monkeypatch.setattr(controller, "_package_command", lambda _argv: pytest.fail("Node import must not run npm"))
    controller._package_import("node", 1024)
    assert (Path(config["deps"]) / "node/node_modules/example/index.js").read_bytes() == b"dependency"
    assert (Path(config["repo"]) / "node_modules").is_symlink()
    assert (Path(config["repo"]) / "node_modules").resolve() == Path(config["deps"]) / "node/node_modules"


@pytest.mark.parametrize("change", [{"repo": "relative"}, {"python": None}, {"npm": "npm"}, {"extra": "value"}])
def test_local_controller_configuration_rejects_implicit_paths(tmp_path, monkeypatch, change):
    config, path = local_config(tmp_path, monkeypatch)
    config.update(change)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        controller.configure_local(path)


async def test_local_setup_corporation_and_symlink_boundaries(settings, repo, acquisition):
    with pytest.raises(SetupBlocked):
        await SetupManager(settings).prepare("B654321", SESSION, repo, "python")
    original = repo / "requirements.txt"
    original.unlink()
    original.symlink_to(repo / "main.py")
    record = await SetupManager(settings).prepare(CORP, SESSION, repo, "python")
    assert record["status"] == "blocked" and record["artifact_path"] is None
    assert not acquisition[0]["calls"]


async def test_actual_local_controller_reads_and_exports_private_fixture_bytes_without_packages_or_network(settings, repo, acquisition, monkeypatch):
    _, tools = acquisition
    tools.update(python=sys.executable, uv=None, node=None, npm=None)
    monkeypatch.setattr(setup, "ProcessSupervisor", ProcessSupervisor)
    private = repo.parent / "standard-library-acquisition"
    manifests = private / "repo"
    manifests.mkdir(parents=True)
    helper = LocalAcquisition(settings, manifests, "b" * 32)
    await helper.start()
    try:
        accepted = await helper.package_bytes("set-requirements", input_data=REQUIREMENTS)
        assert accepted.exit_code == 0 and not accepted.truncated
        result = await helper.package_bytes("read-requirements")
        assert result.stdout == REQUIREMENTS and not result.stderr
        wheels = private / "acquired/wheels"
        wheels.mkdir()
        (wheels / "example-1.0-py3-none-any.whl").write_bytes(b"fixture wheel")
        exported = await helper.package_bytes("package-export", "python", "1024", max_output_bytes=16384)
        assert exported.exit_code == 0 and not exported.truncated
        with tarfile.open(fileobj=io.BytesIO(exported.stdout)) as packages:
            assert set(packages.getnames()) == {"requirements.txt", "wheels/example-1.0-py3-none-any.whl"}
        # Node installation needs no package-manager command: it only restores
        # the already validated immutable package tree into the session target.
        node = archive({"node_modules/example/index.js": b"fixture dependency"})
        imported = await helper.package_bytes("package-import", "node", "1024", input_data=node)
        assert imported.exit_code == 0 and not imported.stderr
        assert (private / "deps/node/node_modules/example/index.js").read_bytes() == b"fixture dependency"
        assert (manifests / "node_modules").resolve() == private / "deps/node/node_modules"
        fingerprint = await helper.package_bytes("dependency-identity", "1024")
        assert fingerprint.exit_code == 0 and len(fingerprint.stdout.strip()) == 64
    finally:
        await helper.close()
