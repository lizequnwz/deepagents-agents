from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource
from general_agent.advisor_matching.workbook import verify_match_workbook
from general_agent.advisor_tools import build_advisor_tools
from general_agent.store import Store
from general_agent.workspace import Workspace


@pytest.mark.asyncio
async def test_persisted_review_session_can_be_listed_and_regenerated(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.workspace_root, settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    workspace.upload(
        corp_id=corp_id, conversation_id=conversation_id,
        original_name="advisors.csv", content_type="text/csv",
        source=BytesIO(b"Advisor Name,Firm,City,State\nJohn Smith,Northstar Wealth Partners,Boston,MA\n"),
        max_bytes=settings.max_upload_mb * 1024 * 1024,
    )
    backend = AdvisorWorkspaceBackend(settings.workspace_root)
    source = SyntheticAdvisorReferenceSource(
        Path(__file__).parents[1] / "general_agent" / "advisor_matching" / "data" / "master_advisors.csv"
    )
    tools = {item.name: item for item in build_advisor_tools(
        settings=settings, workspace=workspace, backend=backend, store=store,
        advisor_source=source,
    )}
    mapping = {
        "full_name": {"columns": [{"index": 0, "header": "Advisor Name"}]},
        "firm_name": {"columns": [{"index": 1, "header": "Firm"}]},
        "city": {"columns": [{"index": 2, "header": "City"}]},
        "state": {"columns": [{"index": 3, "header": "State"}]},
    }
    async with backend.run_scope("run-test", corp_id, conversation_id):
        profile = await tools["profile_advisor_file"].ainvoke({"input_virtual_path": "/uploads/advisors.csv"})
        assert profile["sheets"][0]["columns"][0]["header"] == "Advisor Name"
        manifest = await tools["find_all_advisors_in_database"].ainvoke({})
        assert manifest["row_count"] == 40
        result = await tools["start_advisor_match"].ainvoke({
            "input_virtual_path": "/uploads/advisors.csv",
            "snapshot_virtual_path": manifest["snapshot_virtual_path"],
            "mapping": mapping,
        })
        assert result["counts"]["ambiguous_match"] == 1
        page = await tools["list_advisor_match_items"].ainvoke({
            "match_session_id": result["match_session_id"], "status": "Ambiguous Match",
        })
        item = page["items"][0]
        assert "internal_score" not in item["candidates"][0]
        selected_crd = item["candidates"][0]["crd_number"]
        updated = await tools["apply_advisor_review_decisions"].ainvoke({
            "match_session_id": result["match_session_id"],
            "decisions": [{"review_item_id": item["review_item_id"], "action": "confirm_candidate", "crd_number": selected_crd}],
            "approve_session": True,
        })
        assert updated["counts"] == {"matched": 1, "ambiguous_match": 0, "no_match": 0}

    session = store.get_advisor_match_session(result["match_session_id"], corp_id=corp_id)
    assert session["status"] == "Approved"
    with pytest.raises(KeyError):
        store.get_advisor_match_session(result["match_session_id"], corp_id="B654321")
    output = workspace.chat_root(corp_id, conversation_id) / "advisor_matches.xlsx"
    assert verify_match_workbook(output, expected_rows=1)["matched"] == 1
    store.close()


@pytest.mark.asyncio
async def test_unlisted_crd_requires_proposal_then_confirmation(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.workspace_root, settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    workspace.upload(
        corp_id=corp_id, conversation_id=conversation_id,
        original_name="unknown.csv", content_type="text/csv",
        source=BytesIO(b"Name\nUnknown Person\n"), max_bytes=1024,
    )
    backend = AdvisorWorkspaceBackend(settings.workspace_root)
    source = SyntheticAdvisorReferenceSource(
        Path(__file__).parents[1] / "general_agent" / "advisor_matching" / "data" / "master_advisors.csv"
    )
    tools = {item.name: item for item in build_advisor_tools(
        settings=settings, workspace=workspace, backend=backend, store=store,
        advisor_source=source,
    )}
    async with backend.run_scope("run-manual", corp_id, conversation_id):
        manifest = await tools["find_all_advisors_in_database"].ainvoke({})
        result = await tools["start_advisor_match"].ainvoke({
            "input_virtual_path": "/uploads/unknown.csv",
            "snapshot_virtual_path": manifest["snapshot_virtual_path"],
            "mapping": {"full_name": {"columns": [{"index": 0, "header": "Name"}]}},
        })
        page = await tools["list_advisor_match_items"].ainvoke({"match_session_id": result["match_session_id"]})
        proposal = await tools["propose_manual_crd_override"].ainvoke({
            "match_session_id": result["match_session_id"],
            "review_item_id": page["items"][0]["review_item_id"],
            "crd_number": "99000001", "snapshot_virtual_path": manifest["snapshot_virtual_path"],
        })
        assert proposal["requires_explicit_confirmation"] is True
        session = store.get_advisor_match_session(result["match_session_id"], corp_id=corp_id)
        assert session["counts"]["matched"] == 0
        with pytest.raises(ValueError, match="later user turn"):
            await tools["apply_advisor_review_decisions"].ainvoke({
                "match_session_id": result["match_session_id"],
                "decisions": [{
                    "review_item_id": page["items"][0]["review_item_id"],
                    "action": "confirm_manual_crd", "proposal_id": proposal["proposal_id"],
                }],
            })
    async with backend.run_scope("run-manual-confirm", corp_id, conversation_id):
        confirmed = await tools["apply_advisor_review_decisions"].ainvoke({
            "match_session_id": result["match_session_id"],
            "decisions": [{
                "review_item_id": page["items"][0]["review_item_id"],
                "action": "confirm_manual_crd", "proposal_id": proposal["proposal_id"],
            }],
        })
        assert confirmed["counts"]["matched"] == 1
    store.close()
