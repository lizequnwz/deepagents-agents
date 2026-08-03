from __future__ import annotations

import os
from io import BytesIO

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


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_model_completes_same_turn_firm_match() -> None:
    if os.getenv("GENERAL_AGENT_LIVE_TEST") != "1":
        pytest.skip("Set GENERAL_AGENT_LIVE_TEST=1 to make a provider model call.")
    settings = load_settings()
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    advisor_source = SyntheticAdvisorReferenceSource(
        settings.project_root
        / "general_agent"
        / "advisor_matching"
        / "data"
        / "master_advisors.csv"
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
    question = "Help me match this file; all advisors are from Cedar Grove Advisory."
    run_id, _ = store.create_run(conversation_id, question, corp_id=corp_id)
    attachment, protected = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation_id,
        original_name="same-turn-firm.csv",
        content_type="text/csv",
        source=BytesIO(b"Name,City,State\nRobert Mercer,Richmond,VA\n"),
        max_bytes=1024 * 1024,
    )
    store.add_attachment(run_id, attachment, protected, corp_id=corp_id)
    message = f"{question}\nAttachment ID: {attachment.attachment_id}"
    async with backend.run_scope(run_id, corp_id, conversation_id):
        output = await graph.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": conversation_id}},
        )
    session = store.get_latest_advisor_match_session(
        conversation_id, corp_id=corp_id
    )
    assert output.get("messages")
    assert session["source_transformation"]["type"] == "session_firm_override"
    assert session["counts"]["matched"] == 1
    store.close()
