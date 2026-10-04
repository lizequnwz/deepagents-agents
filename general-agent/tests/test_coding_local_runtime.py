"""Real trusted-local execution, without Docker, providers, or downloads."""

import asyncio
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from general_agent.coding.local_runtime import LocalRuntime, _WORKER, local_toolchain_identity
from general_agent.coding.runtime import RuntimeUnavailable, SourceTransferError
from general_agent.workspace import corp_storage_key


@pytest.fixture
async def local_runtime(settings):
    repo = settings.coding_root / corp_storage_key("CORP_A") / ("1" * 32) / "repo"
    repo.mkdir(parents=True)
    (repo / "main.py").write_text("value = 1\n")
    runtime = LocalRuntime(settings, repo, "2" * 32)
    await runtime.start()
    yield runtime
    await runtime.close()


def python_command(text):
    return "python -c " + shlex.quote(text)


async def test_private_python_clean_environment_reconciliation_and_output_bound(local_runtime, monkeypatch):
    runtime = local_runtime
    monkeypatch.setenv("APPLICATION_SECRET", "should-never-enter-child")
    monkeypatch.setenv("PYTHONPATH", "/foreign/modules")
    result = await runtime.execute(python_command(
        "import os,sys,json; from pathlib import Path; Path('main.py').write_text('value = 2\\n'); "
        "print(json.dumps({'secret':os.getenv('APPLICATION_SECRET'), 'prefix':sys.prefix, 'home':os.getenv('HOME')}))"))
    assert result.exit_code == 0, result
    evidence = json.loads(result.output)
    assert evidence["secret"] is None
    assert evidence["prefix"] == str(runtime._private / "python")
    assert evidence["home"] == str(runtime._private / "tmp/home")
    assert (runtime.repo / "main.py").read_text() == "value = 2\n"
    assert runtime._exec_repo != runtime.repo
    assert runtime.source_revision and runtime.runtime_id.startswith("local:")
    bounded = await runtime.execute(python_command("print('x' * 5000)"))
    assert bounded.truncated and len(bounded.output.encode()) <= runtime.settings.max_command_output_bytes
    assert runtime._env()["UV_PROJECT_ENVIRONMENT"] == str(runtime._private / "python")
    assert runtime._env()["NPM_CONFIG_PREFIX"] == str(runtime._private / "deps/node-global")


async def test_timeout_and_task_cancel_capture_permitted_partial_source(local_runtime):
    runtime = local_runtime
    timed = await runtime.execute(python_command("from pathlib import Path; import time; Path('partial.py').write_text('value = 3'); time.sleep(10)"), timeout=0.8)
    assert timed.timed_out and timed.exit_code == 124
    assert (runtime.repo / "partial.py").read_text() == "value = 3"
    task = asyncio.create_task(runtime.execute(python_command("from pathlib import Path; import time; Path('cancelled.py').write_text('value = 4'); time.sleep(10)")))
    async with asyncio.timeout(3):
        while not (runtime._exec_repo / "cancelled.py").exists():
            await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (runtime.repo / "cancelled.py").read_text() == "value = 4"
    assert (await runtime.execute("printf ready")).output == "ready"


async def test_hidden_and_alias_exports_fail_before_session_merge(local_runtime, tmp_path):
    runtime = local_runtime
    foreign = tmp_path / "foreign.py"
    foreign.write_text("private")
    for payload in ("from pathlib import Path; Path('.env').write_text('secret')",
                    f"import os; os.symlink({str(foreign)!r}, 'alias.py')",
                    f"import os; os.link({str(foreign)!r}, 'alias.py')"):
        with pytest.raises(SourceTransferError):
            await runtime.execute(python_command(payload))
        assert (runtime.repo / "main.py").read_text() == "value = 1\n"
        assert not (runtime.repo / ".env").exists() and not (runtime.repo / "alias.py").exists()
        await runtime.sync_to_runtime()
    assert foreign.read_text() == "private"


async def test_concurrent_session_change_is_never_overwritten(local_runtime):
    runtime = local_runtime
    task = asyncio.create_task(runtime.execute(python_command("from pathlib import Path; import time; Path('started.py').write_text('started'); time.sleep(.4); Path('main.py').write_text('command')")))
    async with asyncio.timeout(3):
        while not (runtime._exec_repo / "started.py").exists():
            await asyncio.sleep(0.02)
    (runtime.repo / "main.py").write_text("external")
    with pytest.raises(SourceTransferError, match="Session source changed"):
        await task
    assert (runtime.repo / "main.py").read_text() == "external"


async def test_dependencies_fingerprint_and_node_link_survive_source_sync(local_runtime):
    runtime = local_runtime
    initial = runtime.identity
    await runtime.execute(python_command("from pathlib import Path; import site; Path(site.getsitepackages()[0], 'installed_local.py').write_text('value=1')"))
    assert runtime.identity != initial
    node = runtime._private / "deps/node/node_modules/package"
    node.mkdir(parents=True)
    (node / "index.js").write_text("module.exports = 1")
    runtime._restore_dependency_link()
    await runtime.sync_to_runtime()
    assert (runtime._exec_repo / "node_modules").is_symlink()
    assert (runtime._exec_repo / "node_modules/package/index.js").read_text() == "module.exports = 1"
    assert not (runtime.repo / "node_modules").exists()


async def test_local_toolchain_drift_updates_environment_evidence(local_runtime, monkeypatch):
    runtime = local_runtime
    before = runtime.identity
    monkeypatch.setattr("general_agent.coding.local_runtime.local_toolchain_identity", lambda settings: "local:changed-operator-tools")
    result = await runtime.execute("true")
    assert result.exit_code == 0
    assert runtime.runtime_id == "local:changed-operator-tools"
    assert runtime.identity != before


async def test_operator_installed_tools_are_available_without_inheriting_secrets(local_runtime, tmp_path, monkeypatch):
    tools = tmp_path / "operator-bin"
    tools.mkdir()
    executable = tools / "workbench-fixture-tool"
    executable.write_text("#!/bin/sh\nprintf operator-tool")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + ".")
    monkeypatch.setenv("OPERATOR_PRIVATE_TOKEN", "must-not-be-inherited")
    result = await local_runtime.execute("workbench-fixture-tool")
    assert result.exit_code == 0 and result.output == "operator-tool"
    assert "." not in local_runtime._env()["PATH"].split(os.pathsep)
    assert "OPERATOR_PRIVATE_TOKEN" not in local_runtime._env()


async def test_preview_writes_stay_private_and_cleanup_retires_descriptors(local_runtime):
    runtime = local_runtime
    for _ in range(8):
        assert (await runtime.execute("true")).exit_code == 0
    assert not runtime._supervisor._spawns
    seen = []
    preview = await runtime.run_preview(python_command("from pathlib import Path; Path('preview.py').write_text('private'); print('preview')"),
                                        timeout=2, on_output=lambda fd, data: seen.append(data))
    assert preview.exit_code == 0 and b"preview" in b"".join(seen)
    assert (runtime._exec_repo / "preview.py").exists() and not (runtime.repo / "preview.py").exists()
    private = runtime._private
    await runtime.close()
    assert not private.exists()


async def test_invalid_optional_sdk_readiness_has_complete_shape(settings, tmp_path):
    readiness = await LocalRuntime.check_readiness(replace(settings, coding_typescript_sdk=tmp_path / "missing/lib/typescript.js"))
    assert readiness["ready"] is False
    assert readiness["browser"] is False and readiness["typescript_version"] is None
    assert readiness["runtime_id"] is None
    assert (await LocalRuntime.check_readiness(settings))["ready"]
    assert local_toolchain_identity(settings).startswith("local:")


async def test_abandoned_runtime_and_setup_cleanup_requires_owned_markers(settings):
    parent = settings.coding_root / corp_storage_key("CORP_A") / ("1" * 32)
    parent.mkdir(parents=True)
    owner = "2" * 32
    candidates = []
    for prefix in ("local-runtime", "setup-input"):
        candidate = parent / f"{prefix}-{owner}-fixture"
        candidate.mkdir()
        (candidate / ".owner.json").write_text(json.dumps({"owner": owner, "parent": str(parent)}))
        (candidate / "private.txt").write_text("Disposable attempt resource")
        candidates.append(candidate)
    foreign = parent / f"setup-input-{'3' * 32}-fixture"
    foreign.mkdir()
    (candidates[1] / ".owner.json").write_text(json.dumps({"owner": owner, "parent": "another directory"}))
    with pytest.raises(RuntimeUnavailable, match="ownership"):
        await LocalRuntime.cleanup_owner(settings, owner)
    assert all(candidate.exists() for candidate in candidates)
    (candidates[1] / ".owner.json").write_text(json.dumps({"owner": owner, "parent": str(parent)}))
    assert await LocalRuntime.cleanup_owner(settings, owner) == 2
    assert foreign.exists() and all(not candidate.exists() for candidate in candidates)


def test_eof_worker_kills_its_group_when_the_real_parent_exits(tmp_path):
    started, finished = tmp_path / "started", tmp_path / "finished"
    child = ["/bin/sh", "-c", f"touch {shlex.quote(str(started))}; sleep 1; touch {shlex.quote(str(finished))}"]
    script = (
        "import os,subprocess,sys,time,json\n"
        "r,w=os.pipe()\n"
        f"p=subprocess.Popen([sys.executable,'-I',{str(_WORKER)!r},'--worker',str(r),json.dumps({child!r})],pass_fds=(r,),start_new_session=True)\n"
        "os.close(r)\n"
        f"deadline=time.monotonic()+3\nwhile not os.path.exists({str(started)!r}):\n"
        " if time.monotonic()>deadline: raise RuntimeError('worker did not start')\n time.sleep(.01)\n"
        "print(p.pid,flush=True)\nos._exit(0)\n")
    parent = subprocess.Popen([sys.executable, "-I", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    output, errors = parent.communicate(timeout=5)
    assert parent.returncode == 0, errors.decode()
    assert int(output.strip()) > 0 and started.exists()
    time.sleep(1.1)
    assert not finished.exists()
