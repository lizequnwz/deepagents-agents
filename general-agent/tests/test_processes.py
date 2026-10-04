from __future__ import annotations

import asyncio
import fcntl
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from general_agent.processes import ProcessSupervisor


def _python(script: str) -> tuple[str, ...]:
    return (sys.executable, "-c", script)


def _arguments(tmp_path: Path, **overrides):
    return {
        "owner_id": "run-one",
        "cwd": tmp_path,
        "env": {"PATH": "/usr/bin:/bin"},
        "timeout": 3,
        "max_output_bytes": 1_024,
        **overrides,
    }


async def _wait_for_file(path: Path) -> None:
    async with asyncio.timeout(2):
        while not path.exists():
            await asyncio.sleep(0.01)


async def _assert_not_running(pid: int) -> None:
    # Give the system time to reap orphaned grandchildren after group teardown.
    async with asyncio.timeout(2):
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.01)


def _child_script(*, hold_pipes: bool, ignore_term: bool = False) -> str:
    child = (
        "import signal,time; from pathlib import Path; "
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "")
        + "Path('child-ready').write_text('ready'); time.sleep(30)"
    )
    redirect = "" if hold_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    return (
        "import subprocess,sys,time; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]{redirect}); "
        "Path('child.pid').write_text(str(child.pid)); "
        "\nwhile not Path('child-ready').exists(): time.sleep(0.005)"
        "\nprint('parent exited', flush=True)"
    )


@pytest.mark.asyncio
async def test_explicit_environment_cwd_stdin_and_closed_descriptors(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESS_TEST_SECRET", "ambient-secret")
    descriptor = os.open(tmp_path / "descriptor.txt", os.O_CREAT | os.O_RDONLY, 0o600)
    inherited = fcntl.fcntl(descriptor, fcntl.F_DUPFD, 100)
    os.set_inheritable(inherited, True)
    try:
        result = await ProcessSupervisor().run(
            _python(
                "import os,sys; print(os.getcwd()); "
                "print(os.getenv('PROCESS_TEST_SECRET','missing')); "
                "print(repr(sys.stdin.read())); "
                f"\ntry: os.fstat({inherited}); print('inherited descriptor')"
                "\nexcept OSError: print('descriptor closed')"
            ),
            **_arguments(tmp_path),
        )
    finally:
        os.close(inherited)
        os.close(descriptor)
    assert result.exit_code == 0
    assert str(tmp_path) in result.output
    assert "missing" in result.output
    assert "ambient-secret" not in result.output
    assert "''" in result.output
    assert "descriptor closed" in result.output


@pytest.mark.asyncio
async def test_explicit_descriptor_pins_directory_across_path_replacement(tmp_path):
    original = tmp_path / "source"
    original.mkdir()
    descriptor = os.open(original, os.O_RDONLY | os.O_DIRECTORY)
    pinned = tmp_path / "pinned"
    original.rename(pinned)
    original.mkdir()
    try:
        result = await ProcessSupervisor().run(
            _python(f"import os; from pathlib import Path; os.fchdir({descriptor}); Path('result').write_text('pinned')"),
            **_arguments(tmp_path), pass_fds=(descriptor,),
        )
    finally:
        os.close(descriptor)
    assert result.exit_code == 0
    assert (pinned / "result").read_text() == "pinned"
    assert not (original / "result").exists()


@pytest.mark.asyncio
async def test_shell_exit_status_stderr_and_shared_output_cap(tmp_path):
    supervisor = ProcessSupervisor()
    result = await supervisor.run_shell(
        "printf 'stdout'; printf 'stderr' >&2; exit 7", **_arguments(tmp_path)
    )
    assert result.exit_code == 7
    assert result.output == "stdout\n[stderr] stderr"
    assert not result.truncated

    result = await supervisor.run(
        _python("import sys; sys.stdout.write('o'*200); sys.stderr.write('e'*200)"),
        **_arguments(tmp_path, max_output_bytes=100),
    )
    assert result.exit_code == 0
    assert result.truncated
    assert len(result.output.encode()) <= 100


@pytest.mark.asyncio
async def test_binary_transfer_preserves_bytes_and_bounds_stalled_input(tmp_path):
    supervisor = ProcessSupervisor()
    content = bytes(range(256)) * 1_024
    result = await supervisor.run_bytes(
        _python("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
        **_arguments(tmp_path, max_output_bytes=len(content)),
        input_data=content,
    )
    assert result.exit_code == 0
    assert result.stdout == content
    assert not result.truncated

    result = await supervisor.run_bytes(
        _python("import time; time.sleep(30)"),
        **_arguments(tmp_path, timeout=0.1),
        input_data=content,
    )
    assert result.exit_code == 124
    assert result.timed_out


@pytest.mark.asyncio
async def test_deadline_includes_child_pipes_after_parent_exit(tmp_path):
    supervisor = ProcessSupervisor()
    started = time.monotonic()
    result = await supervisor.run(
        _python(_child_script(hold_pipes=True)),
        **_arguments(tmp_path, timeout=0.3),
    )
    assert time.monotonic() - started < 1
    assert result.exit_code == 124
    assert result.timed_out
    assert "timed out" in result.output
    await _assert_not_running(int((tmp_path / "child.pid").read_text()))


@pytest.mark.asyncio
async def test_completed_parent_does_not_leave_background_group(tmp_path):
    result = await ProcessSupervisor().run(
        _python(_child_script(hold_pipes=False, ignore_term=True)),
        **_arguments(tmp_path),
    )
    assert result.exit_code == 0
    assert not result.timed_out
    await _assert_not_running(int((tmp_path / "child.pid").read_text()))


@pytest.mark.asyncio
async def test_owner_cancel_kills_children_after_parent_exit_and_is_scoped(tmp_path):
    supervisor = ProcessSupervisor()
    first = asyncio.create_task(
        supervisor.run_shell(
            shlex.join(_python(_child_script(hold_pipes=True, ignore_term=True))),
            **_arguments(tmp_path),
        )
    )
    other = asyncio.create_task(
        supervisor.run(
            _python("import time; time.sleep(0.5); print('other finished')"),
            **_arguments(tmp_path, owner_id="other-run"),
        )
    )
    await _wait_for_file(tmp_path / "child-ready")
    assert supervisor.process_groups("run-one")
    assert supervisor.process_groups("another-owner") == ()
    await supervisor.cancel_owner("run-one")
    result = await asyncio.wait_for(first, 1)
    assert supervisor.process_groups("run-one") == ()
    assert result.cancelled
    assert result.exit_code < 0
    await _assert_not_running(int((tmp_path / "child.pid").read_text()))
    other_result = await asyncio.wait_for(other, 1)
    assert other_result.exit_code == 0
    assert other_result.output == "other finished"
    await supervisor.cancel_owner("run-one")
    assert not supervisor._owners


@pytest.mark.asyncio
async def test_repeated_task_cancellation_cannot_interrupt_cleanup(tmp_path):
    supervisor = ProcessSupervisor()
    task = asyncio.create_task(
        supervisor.run(
            _python(_child_script(hold_pipes=True, ignore_term=True)),
            **_arguments(tmp_path),
        )
    )
    await _wait_for_file(tmp_path / "child-ready")
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await _assert_not_running(int((tmp_path / "child.pid").read_text()))
    assert not supervisor._owners


@pytest.mark.asyncio
async def test_cancellation_before_startup_completes_owns_late_process(tmp_path, monkeypatch):
    loop = asyncio.get_running_loop()
    original_spawn = loop.subprocess_exec
    startup_entered = asyncio.Event()
    release_startup = asyncio.Event()
    transports = []

    async def delayed_spawn(*args, **kwargs):
        startup_entered.set()
        await release_startup.wait()
        transport, protocol = await original_spawn(*args, **kwargs)
        transports.append(transport)
        return transport, protocol

    monkeypatch.setattr(loop, "subprocess_exec", delayed_spawn)
    supervisor = ProcessSupervisor()
    inherited, writer = os.pipe()
    task = asyncio.create_task(
        supervisor.run(_python("import time; time.sleep(30)"),
                       **_arguments(tmp_path, pass_fds=(inherited,)))
    )
    await asyncio.wait_for(startup_entered.wait(), 1)
    await asyncio.wait_for(supervisor.cancel_owner("run-one"), 1)
    result = await asyncio.wait_for(task, 1)
    assert result.cancelled
    os.close(writer)
    supervisor.release_descriptors((inherited,))
    os.fstat(inherited)  # Still held until the uncertain startup settles.
    release_startup.set()
    await asyncio.wait_for(asyncio.gather(*supervisor._spawns), 1)
    async with asyncio.timeout(1):
        while transports[0].get_returncode() is None:
            await asyncio.sleep(0.01)
    assert transports[0].get_returncode() < 0
    assert not supervisor._spawns
    with pytest.raises(OSError):
        os.fstat(inherited)


@pytest.mark.asyncio
async def test_deadline_also_covers_pending_startup(tmp_path, monkeypatch):
    loop = asyncio.get_running_loop()
    original_spawn = loop.subprocess_exec
    release_startup = asyncio.Event()
    transports = []

    async def delayed_spawn(*args, **kwargs):
        await release_startup.wait()
        transport, protocol = await original_spawn(*args, **kwargs)
        transports.append(transport)
        return transport, protocol

    monkeypatch.setattr(loop, "subprocess_exec", delayed_spawn)
    supervisor = ProcessSupervisor()
    started = time.monotonic()
    result = await supervisor.run(
        _python("import time; time.sleep(30)"),
        **_arguments(tmp_path, timeout=0.05),
    )
    assert time.monotonic() - started < 0.5
    assert result.timed_out
    release_startup.set()
    await asyncio.wait_for(asyncio.gather(*supervisor._spawns), 1)
    async with asyncio.timeout(1):
        while transports[0].get_returncode() is None:
            await asyncio.sleep(0.01)
    assert transports[0].get_returncode() < 0


@pytest.mark.asyncio
async def test_direct_cancellation_during_owner_cleanup_is_propagated(tmp_path):
    supervisor = ProcessSupervisor()
    task = asyncio.create_task(
        supervisor.run(
            _python(_child_script(hold_pipes=True, ignore_term=True)),
            **_arguments(tmp_path),
        )
    )
    await _wait_for_file(tmp_path / "child-ready")
    stopping = asyncio.create_task(supervisor.cancel_owner("run-one"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await asyncio.wait_for(stopping, 1)
    await _assert_not_running(int((tmp_path / "child.pid").read_text()))


@pytest.mark.asyncio
async def test_startup_failure_releases_owner_and_is_not_reported_as_success(tmp_path):
    supervisor = ProcessSupervisor()
    with pytest.raises(FileNotFoundError):
        await supervisor.run((str(tmp_path / "missing-program"),), **_arguments(tmp_path))
    assert not supervisor._owners


@pytest.mark.asyncio
async def test_timeout_caps_diagnostic_and_rejects_invalid_inputs(tmp_path):
    supervisor = ProcessSupervisor()
    result = await supervisor.run(
        _python("import time; print('x'*100, flush=True); time.sleep(30)"),
        **_arguments(tmp_path, timeout=0.1, max_output_bytes=20),
    )
    assert result.exit_code == 124
    assert result.truncated
    assert len(result.output.encode()) <= 20
    with pytest.raises(ValueError, match="timeout"):
        await supervisor.run(_python("pass"), **_arguments(tmp_path, timeout=float("inf")))
    with pytest.raises(ValueError, match="absolute"):
        await supervisor.run(_python("pass"), **_arguments(Path("relative")))
    assert not supervisor._owners


async def test_incremental_output_continues_after_completed_capture_is_full(tmp_path):
    chunks = []
    result = await ProcessSupervisor().run(
        _python("import sys,time; print('x'*5000, flush=True); time.sleep(0.05); print('tail-marker', flush=True)"),
        **_arguments(tmp_path, max_output_bytes=100), on_output=lambda descriptor, content: chunks.append((descriptor, content)),
    )
    assert result.truncated and len(result.output.encode()) <= 100
    assert b"tail-marker" in b"".join(content for descriptor, content in chunks if descriptor == 1)
