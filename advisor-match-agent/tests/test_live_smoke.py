from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from general_agent.agent import build_agent
from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource
from general_agent.config import load_settings
from general_agent.store import Store
from general_agent.workspace import Workspace


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_model_smoke() -> None:
    if os.getenv("GENERAL_AGENT_LIVE_TEST") != "1":
        pytest.skip("Set GENERAL_AGENT_LIVE_TEST=1 to make a provider model call.")
    settings = load_settings()
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    advisor_source = SyntheticAdvisorReferenceSource(
        settings.project_root / "general_agent" / "advisor_matching" / "data" / "master_advisors.csv"
    )
    graph = build_agent(
        settings,
        workspace=workspace,
        backend=backend,
        store=store,
        advisor_source=advisor_source,
        checkpointer=InMemorySaver(),
    )
    corp_id = "A123456"
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    async with backend.run_scope("live-smoke", corp_id, conversation_id):
        output = await graph.ainvoke(
            {"messages": [{"role": "user", "content": "Explain your sole supported purpose in one sentence."}]},
            config={"configurable": {"thread_id": "live-smoke"}},
        )
    assert output.get("messages")
    store.close()
