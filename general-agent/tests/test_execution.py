from __future__ import annotations

import asyncio
import os

import pytest

from general_agent.execution import CancellableLocalShellBackend
from general_agent.workspace import Workspace


def make_backend(settings, *, output_limit: int | None = None):
    return CancellableLocalShellBackend(
        settings.workspace_root,
        package_root=settings.package_root,
        temp_root=settings.temp_root,
        timeout=settings.command_timeout_seconds,
        max_output_bytes=output_limit or settings.max_command_output_bytes,
    )


@pytest.mark.asyncio
async def test_commands_use_workspace_and_strip_secrets(settings, monkeypatch) -> None:
    monkeypatch.setenv("GENERAL_AGENT_TEST_SECRET", "should-not-leak")
    backend = make_backend(settings)
    command = (
        "python -c \"import os; print(os.getcwd()); "
        "print(os.getenv('GENERAL_AGENT_TEST_SECRET', 'missing')); "
        "print(os.getenv('GENERAL_AGENT_NODE_PACKAGE_DIR')); "
        "print(os.getenv('NODE_PATH'))\""
    )
    response = await backend.aexecute(command)
    assert response.exit_code == 0
    assert str(settings.workspace_root) in response.output
    assert "missing" in response.output
    assert "should-not-leak" not in response.output
    assert ".packages/node" in response.output
    assert ".packages/node/node_modules" in response.output


@pytest.mark.asyncio
async def test_run_scope_roots_shell_and_file_tools_in_current_chat(settings) -> None:
    backend = make_backend(settings)
    workspace = Workspace(settings.workspace_root, settings.data_root)
    workspace.ensure_user("A123456")
    (workspace.shared_root("A123456") / "reference.txt").write_text(
        "shared", encoding="utf-8"
    )
    async with backend.run_scope("run-one", "A123456", "chat-one"):
        response = await backend.aexecute(
            "python -c \"from pathlib import Path; Path('result.txt').write_text('ok'); print(Path.cwd())\""
        )
        assert response.exit_code == 0
        assert str(workspace.chat_root("A123456", "chat-one")) in response.output
        assert backend.read("/result.txt").file_data["content"] == "ok"
        assert backend.read("/shared/reference.txt").file_data["content"] == "shared"
    assert (workspace.chat_root("A123456", "chat-one") / "result.txt").exists()


@pytest.mark.asyncio
async def test_output_is_combined_and_capped(settings) -> None:
    backend = make_backend(settings, output_limit=100)
    response = await backend.aexecute(
        "python -c \"import sys; print('o'*100); print('e'*100, file=sys.stderr)\""
    )
    assert response.truncated is True
    assert len(response.output.encode()) <= 100


@pytest.mark.asyncio
async def test_binary_reads_are_rejected_and_text_reads_are_bounded(settings) -> None:
    backend = CancellableLocalShellBackend(
        settings.workspace_root,
        package_root=settings.package_root,
        temp_root=settings.temp_root,
        timeout=settings.command_timeout_seconds,
        max_output_bytes=settings.max_command_output_bytes,
        max_file_read_chars=100,
    )
    workspace = Workspace(settings.workspace_root, settings.data_root)
    chat = workspace.ensure_chat("A123456", "bounded")
    (chat / "input.pdf").write_bytes(b"%PDF-placeholder")
    (chat / "long.txt").write_text("x" * 500, encoding="utf-8")
    async with backend.run_scope("bounded-run", "A123456", "bounded"):
        run_temp = workspace.temp_root("A123456") / "bounded-run"
        run_temp.mkdir(parents=True, exist_ok=True)
        (run_temp / "extracted.txt").write_text("temporary", encoding="utf-8")
        assert backend.read("/tmp/extracted.txt").file_data["content"] == "temporary"
        binary = backend.read("/input.pdf")
        assert "matching pdf" in (binary.error or "")
        text = backend.read("/long.txt")
        assert "Read truncated" in text.file_data["content"]
        assert len(text.file_data["content"]) <= 100


@pytest.mark.asyncio
async def test_timeout_and_run_cancellation_terminate_process_group(settings) -> None:
    backend = make_backend(settings)
    timeout = await backend.aexecute("python -c \"import time; time.sleep(5)\"", timeout=1)
    assert timeout.exit_code == 124

    async def run_command():
        async with backend.run_scope("cancel-me", "A123456"):
            return await backend.aexecute("python -c \"import time; time.sleep(30)\"")

    task = asyncio.create_task(run_command())
    for _ in range(100):
        if backend._processes.get("cancel-me"):
            break
        await asyncio.sleep(0.01)
    await backend.cancel_run("cancel-me")
    result = await asyncio.wait_for(task, timeout=3)
    assert result.exit_code < 0
    assert not backend._processes
