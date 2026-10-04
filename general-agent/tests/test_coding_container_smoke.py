"""Opt-in real-container gates; fixed fixtures only and no model/provider calls."""

import asyncio
import json
import os
import shlex

import pytest

from general_agent.coding.process_sessions import ProcessSessions
from general_agent.coding.runtime import DockerRuntime
from general_agent.coding.source import source_revision, source_snapshot
from general_agent.workspace import corp_storage_key

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.getenv("GENERAL_AGENT_DOCKER_TEST") != "1",
    reason="Set GENERAL_AGENT_DOCKER_TEST=1 only after building the selected local images.",
)]


@pytest.fixture
async def container(settings):
    repo = settings.coding_root / corp_storage_key("A123456") / ("a" * 32) / "repo"
    repo.mkdir(parents=True)
    (repo / "app.ts").write_text("export const count: number = 1;\n")
    (repo / "index.html").write_text("<h1>Hello container</h1>")
    runtime = DockerRuntime(settings, repo, "b" * 32)
    try:
        await runtime.start()
        yield runtime
    finally:
        await runtime.close()
        await DockerRuntime.cleanup_owner(settings, runtime.owner_id)


async def test_real_container_source_environment_and_compiler(container):
    program = '''import json, os, socket
from pathlib import Path
assert os.getuid() == 1000
assert "OPENAI_API_KEY" not in os.environ
assert "GITHUB_TOKENS_JSON" not in os.environ
assert os.environ["GOPROXY"] == "off"
assert not Path("/var/run/docker.sock").exists()
connection = socket.socket()
connection.settimeout(1)
assert connection.connect_ex(("198.51.100.1", 443)) != 0
connection.close()
try:
    Path("/opt/general-agent/forbidden.txt").write_text("no")
except OSError:
    pass
else:
    raise AssertionError("Container root must be read-only")
Path("result.txt").write_text("isolated output")
print(json.dumps({"uid": os.getuid(), "offline": True}))
'''
    result = await container.execute(shlex.join(["python", "-I", "-c", program]), timeout=10)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["offline"]
    assert (container.repo / "result.txt").read_text() == "isolated output"
    response = await container.language_probe({"operation": "symbols", "documents": [
        {"path": "app.ts", "text": (container.repo / "app.ts").read_text()}]})
    assert any(item["name"] == "count" for item in response["symbols"])


async def test_real_stop_captures_partial_source_and_removes_owned_processes(container):
    task = asyncio.create_task(container.execute(shlex.join(["python", "-I", "-c",
        "from pathlib import Path; import time; Path('partial.txt').write_text('kept'); time.sleep(60)"]), timeout=60))
    # Observe the container fixture, rather than relying on a startup sleep.
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        response = await container._docker("exec", "--user=1000:1000", container._container,
            "test", "-f", "/work/repo/partial.txt", timeout=2)
        if response.exit_code == 0:
            break
        await asyncio.sleep(0.05)
    else:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.fail("Container fixture did not reach the partial-change boundary.")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (container.repo / "partial.txt").read_text() == "kept"
    await container.close()
    assert await DockerRuntime.cleanup_owner(container.settings, container.owner_id) == 0


@pytest.mark.skipif(os.getenv("GENERAL_AGENT_BROWSER_TEST") != "1",
                   reason="Build the matching browser image and set GENERAL_AGENT_BROWSER_TEST=1.")
async def test_real_browser_preview_freezes_source_and_cleans_up(container):
    revision = source_revision(source_snapshot(container.repo))
    manager = ProcessSessions(container.settings, container)
    try:
        process = await manager.start("python -I -m http.server 8080 --bind 127.0.0.1", port=8080, browser=True, timeout=30)
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            result = await manager.browser_check(process["id"], selector="h1", expected_text="Hello container", timeout=3)
            if result["metadata"]["status"] == "passed":
                break
            await asyncio.sleep(0.1)
        assert result["metadata"]["status"] == "passed", result["metadata"]
        assert result["png"].startswith(b"\x89PNG")
        assert result["metadata"]["source_revision"] == revision
    finally:
        await manager.close()
    assert all(record["state"] not in {"starting", "running", "stopping"} for record in manager.records())
