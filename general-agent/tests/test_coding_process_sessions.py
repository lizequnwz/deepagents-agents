"""Preview ownership, bounded logs and evidence without Docker or a browser."""

import asyncio
import io
import json
import struct

import pytest
from PIL import Image

from general_agent.coding.process_sessions import CursorLog, ProcessSessions, ProcessSessionError, decode_browser_result, validate_browser_request
from general_agent.coding.source import source_revision, source_snapshot
from general_agent.coding.verification import browser_summary
from general_agent.processes import ProcessResult


class PreviewRuntime:
    instances = []
    image_id = "sha256:base"
    base_image_id = "sha256:base"
    identity = "base:deps"
    browser_capable = True

    def __init__(self, settings, repo, owner_id):
        self.settings, self.repo, self.owner_id = settings, repo, owner_id
        self.source_paths = ()
        self.closed = 0
        self.finished = asyncio.Event()
        self.instances.append(self)

    def track_source(self, paths):
        self.source_paths = tuple(paths)

    async def start(self):
        self.source_revision = source_revision(source_snapshot(self.repo, tracked_paths=self.source_paths))

    async def close(self):
        self.closed += 1

    async def install_setup(self, setup):
        pass

    async def run_preview(self, command, *, timeout, on_output):
        on_output(1, b"ready\n")
        await self.finished.wait()
        return ProcessResult("done", 0, False)

    async def preview_revision(self):
        return self.source_revision

    async def _refresh_dependency_identity(self):
        pass

    async def browser_probe(self, **kwargs):
        picture = io.BytesIO()
        Image.new("RGB", (1280, 720), "white").save(picture, format="PNG")
        metadata = json.dumps({"protocol": 1, "status": "passed", "width": 1280, "height": 720}).encode()
        return struct.pack(">I", len(metadata)) + metadata + picture.getvalue()


async def preview_manager(settings):
    root = settings.project_root / "preview-source"
    root.mkdir()
    (root / "app.py").write_text("print('hello')\n")
    main = PreviewRuntime(settings, root, "a" * 32)
    main.track_source(["app.py"])
    await main.start()
    return main, ProcessSessions(settings, main, runtime_factory=PreviewRuntime)


def test_cursor_tail_and_bounds():
    log = CursorLog(8)
    log.append(1, b"0123456789")
    assert log.read(0, 4) == {"output": "2345", "cursor": 6, "base_cursor": 2, "gap": True, "truncated": True}
    log.append(2, b"x")
    assert log.read(log.cursor, 10)["output"] == ""
    for cursor, limit in [(-1, 10), (True, 10), (100, 10), (0, 0), (0, 12001)]:
        with pytest.raises(ProcessSessionError):
            log.read(cursor, limit)
    with pytest.raises(ProcessSessionError):
        CursorLog(0)


async def test_preview_cap_cleanup_and_pre_entry_cancel(settings):
    main, manager = await preview_manager(settings)
    first = await manager.start("server", port=8080, browser=True)
    runtime = manager._sessions[first["id"]].runtime
    await manager.stop(first["id"])  # Cancel before _drive's first instruction.
    assert runtime.closed > 0
    assert manager.read_output(first["id"])["state"] == "stopped"
    await manager.start("one")
    await manager.start("two")
    with pytest.raises(ProcessSessionError, match="two"):
        await manager.start("three")
    with pytest.raises(ProcessSessionError):
        manager.read_output("b" * 32)
    await manager.close()
    assert all(item.closed for item in manager._sessions.values() for item in [item.runtime])
    with pytest.raises(ProcessSessionError, match="closed"):
        await manager.start("late")


async def test_browser_evidence_pinned_to_source_and_environment(settings):
    main, manager = await preview_manager(settings)
    try:
        record = await manager.start("server", port=8080, browser=True)
        await asyncio.sleep(0)
        result = await manager.browser_check(record["id"], selector="h1", expected_text="Hello")
        assert result["metadata"]["status"] == "passed"
        assert result["metadata"]["main_runtime_identity"] == main.identity
        assert result["png"].startswith(b"\x89PNG")
        assert manager.read_output(record["id"])["output"] == "ready\n"
        (main.repo / "app.py").write_text("print('changed')\n")
        result = await manager.browser_check(record["id"])
        assert result["metadata"]["status"] == "stale"
        assert not result["png"]
    finally:
        await manager.close()


@pytest.mark.parametrize("path", ["https://example.com", "//example.com", "/\\example.com", "/x\n", "data:text/html,x"])
def test_browser_origin_validation(path):
    with pytest.raises(ProcessSessionError):
        validate_browser_request(path, None, None, 15)


@pytest.mark.parametrize("timeout", [True, "1", 0, float("inf"), 31])
def test_browser_deadline_validation(timeout):
    with pytest.raises(ProcessSessionError):
        validate_browser_request("/", None, None, timeout)


def test_malformed_screenshot_fails_closed():
    for payload in [b"", b"\0\0\0\0", struct.pack(">I", 2) + b"{}", struct.pack(">I", 999999)]:
        with pytest.raises(RuntimeError):
            decode_browser_result(payload)


def test_browser_failures_and_staleness_cannot_be_verified():
    record = {"target": "home", "status": "failed", "source_revision": "source", "main_runtime_identity": "runtime"}
    assert browser_summary([record], revision="source", runtime_identity="runtime", outcome="verified")["outcome"] == "checks_failed"
    assert browser_summary([record], revision="new", runtime_identity="runtime", outcome="verified")["outcome"] == "not_verified"
    assert record["status"] == "failed"
    passed = {**record, "status": "passed"}
    assert browser_summary([passed], revision="source", runtime_identity="runtime", outcome="not_verified")["outcome"] == "not_verified"
