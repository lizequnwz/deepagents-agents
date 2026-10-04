"""Opt-in real compiler/browser gates; fixed fixtures and no model calls."""

import asyncio
import os
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from general_agent.coding.local_runtime import LocalRuntime
from general_agent.coding.process_sessions import ProcessSessions, ProcessSessionError
from general_agent.coding.source import source_snapshot
from general_agent.workspace import corp_storage_key

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.getenv("GENERAL_AGENT_LOCAL_TOOLS_TEST") != "1",
    reason="Set GENERAL_AGENT_LOCAL_TOOLS_TEST=1 after installing the local optional tools.")]


@pytest.fixture
async def runtime(settings):
    sdk = Path(__file__).resolve().parents[1] / "tooling/coding/node_modules/typescript/lib/typescript.js"
    if not sdk.is_file():
        pytest.skip("Install the pinned SDK with npm ci --prefix tooling/coding --ignore-scripts.")
    configured = replace(settings, coding_typescript_sdk=sdk, run_timeout_seconds=40, command_timeout_seconds=10)
    repo = configured.coding_root / corp_storage_key("A123456") / ("a" * 32) / "repo"
    repo.mkdir(parents=True)
    (repo / "index.html").write_text("<h1>Hello local workbench</h1>")
    (repo / "math.ts").write_text("export function add(x:number) { return x + 1; }\n")
    (repo / "app.ts").write_text('import {add} from "./math";\nconst value: string = add(2);\n')
    instance = LocalRuntime(configured, repo, "b" * 32)
    instance.track_source(tuple(source_snapshot(repo)))
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()
        assert await LocalRuntime.cleanup_owner(configured, instance.owner_id) == 0


async def test_real_local_compiler_definitions_and_diagnostics(runtime):
    documents = [{"path": path, "text": (runtime.repo / path).read_text()}
                 for path in ("math.ts", "app.ts")]
    result = await runtime.language_probe({"operation": "definition", "documents": documents,
                                           "path": "app.ts", "line": 2, "column": 22})
    assert result["typescript_version"] == "5.9.3"
    assert result["definitions"][0]["path"] == "math.ts"
    result = await runtime.language_probe({"operation": "diagnostics", "documents": documents, "path": "app.ts"})
    assert any(item["code"] == 2322 for item in result["diagnostics"])


async def test_real_local_preview_screenshot_ownership_and_cleanup(runtime):
    if not runtime.browser_capable:
        pytest.skip("Install the browser extra, Chromium and lsof before this gate.")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    manager = ProcessSessions(runtime.settings, runtime, runtime_factory=LocalRuntime)
    try:
        record = await manager.start(f"python -u -m http.server {port} --bind 127.0.0.1",
                                     port=port, timeout=30, browser=True)
        async with asyncio.timeout(10):
            while "Serving HTTP" not in manager.read_output(record["id"])["output"]:
                assert manager.read_output(record["id"])["state"] == "running"
                await asyncio.sleep(0.05)
        result = await manager.browser_check(record["id"], selector="h1", expected_text="Hello local workbench", timeout=5)
        assert result["metadata"]["status"] == "passed", result["metadata"]
        assert result["metadata"]["main_runtime_identity"] == runtime.identity
        assert result["png"].startswith(b"\x89PNG")
        preview = manager._sessions[record["id"]].runtime
        (preview._exec_repo / "temporary.txt").write_text("Preview writes are discarded")
        assert not (runtime.repo / "temporary.txt").exists()
        result = await manager.browser_check(record["id"])
        assert result["metadata"]["status"] == "stale" and not result["png"]
        assert (await manager.stop(record["id"]))["state"] == "stopped"
    finally:
        await manager.close()
    with socket.socket() as listener:
        listener.settimeout(0.5)
        assert listener.connect_ex(("127.0.0.1", port)) != 0


async def test_local_preview_rejects_existing_host_listener(runtime):
    manager = ProcessSessions(runtime.settings, runtime, runtime_factory=LocalRuntime)
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with pytest.raises(ProcessSessionError, match="already in use"):
                await manager.start("python -m http.server", port=listener.getsockname()[1])
            assert not manager.records()
    finally:
        await manager.close()
