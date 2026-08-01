from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from general_agent.agent import build_agent
from general_agent.config import load_settings
from general_agent.execution import CancellableLocalShellBackend
from general_agent.workspace import Workspace


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_model_smoke() -> None:
    if os.getenv("GENERAL_AGENT_LIVE_TEST") != "1":
        pytest.skip("Set GENERAL_AGENT_LIVE_TEST=1 to make a provider model call.")
    settings = load_settings()
    workspace = Workspace(settings.workspace_root, settings.data_root)
    backend = CancellableLocalShellBackend(
        settings.workspace_root,
        package_root=settings.package_root,
        temp_root=settings.temp_root,
        timeout=settings.command_timeout_seconds,
        max_output_bytes=settings.max_command_output_bytes,
    )
    graph = build_agent(
        settings,
        workspace=workspace,
        backend=backend,
        checkpointer=InMemorySaver(),
    )
    output = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Reply with: live smoke passed"}]},
        config={"configurable": {"thread_id": "live-smoke"}},
    )
    assert output.get("messages")
