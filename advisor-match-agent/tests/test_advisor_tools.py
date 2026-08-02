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


def _tools(settings, workspace, backend, store):
    source = SyntheticAdvisorReferenceSource(
        Path(__file__).parents[1]
        / "general_agent"
        / "advisor_matching"
        / "data"
        / "master_advisors.csv"
    )
    return {
        item.name: item
        for item in build_advisor_tools(
            settings=settings,
            workspace=workspace,
            backend=backend,
            store=store,
            advisor_source=source,
        )
    }


@pytest.mark.asyncio
async def test_three_stage_match_review_and_regeneration(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.workspace_root, settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation_id,
        original_name="advisors.csv",
        content_type="text/csv",
        source=BytesIO(
            b"Advisor Name,Firm,City,State\n"
            b"John Smith,Northstar Wealth Partners,Boston,MA\n"
        ),
        max_bytes=settings.max_upload_mb * 1024 * 1024,
    )
    backend = AdvisorWorkspaceBackend(settings.workspace_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {
        "full_name": {"columns": [{"index": 0, "header": "Advisor Name"}]},
        "firm_name": {"columns": [{"index": 1, "header": "Firm"}]},
        "city": {"columns": [{"index": 2, "header": "City"}]},
        "state": {"columns": [{"index": 3, "header": "State"}]},
    }

    async with backend.run_scope("run-test", corp_id, conversation_id):
        profile = await tools["profile_advisor_file"].ainvoke(
            {"input_virtual_path": "/uploads/advisors.csv"}
        )
        candidate = profile["sheets"][0]["header_candidates"][0]
        assert candidate["row_number"] == 1
        assert candidate["columns"][0]["header"] == "Advisor Name"

        validation = await tools["validate_advisor_mapping"].ainvoke(
            {
                "input_virtual_path": "/uploads/advisors.csv",
                "mapping": mapping,
            }
        )
        assert validation["input_summary"]["data_row_count"] == 1
        assert validation["input_summary"]["missing_firm_confirmation_required"] is False

        manifest = await tools["find_all_advisors_in_database"].ainvoke({})
        assert manifest["row_count"] == 40
        assert manifest["reference_snapshot_id"].startswith("ars_")
        assert "snapshot_path" not in manifest
        assert "STREET_ADDRESS" not in manifest["columns"]
        stored_reference = store.get_advisor_reference_snapshot(
            manifest["reference_snapshot_id"],
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
        assert Path(stored_reference["snapshot_path"]).is_file()
        with pytest.raises(KeyError):
            store.get_advisor_reference_snapshot(
                manifest["reference_snapshot_id"], corp_id="B654321"
            )

        result = await tools["start_advisor_match"].ainvoke(
            {
                "input_virtual_path": "/uploads/advisors.csv",
                "reference_snapshot_id": manifest["reference_snapshot_id"],
                "mapping": mapping,
                "mapping_fingerprint": validation["mapping_fingerprint"],
            }
        )
        assert result["counts"]["ambiguous_match"] == 1
        assert result["interpreted_mapping"] == validation["mapping"]
        with pytest.raises(ValueError, match="Retrieve a fresh snapshot"):
            await tools["start_advisor_match"].ainvoke(
                {
                    "input_virtual_path": "/uploads/advisors.csv",
                    "reference_snapshot_id": manifest["reference_snapshot_id"],
                    "mapping": mapping,
                    "mapping_fingerprint": validation["mapping_fingerprint"],
                }
            )
        current = await tools["get_current_advisor_match_session"].ainvoke({})
        assert current["match_session_id"] == result["match_session_id"]
        assert current["counts"] == result["counts"]
        assert current["interpreted_mapping"] == result["interpreted_mapping"]

        page = await tools["list_advisor_match_items"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "status": "Ambiguous Match",
            }
        )
        item = page["items"][0]
        assert "internal_score" not in item["candidates"][0]
        assert item["candidates"][0]["supporting_evidence"]
        selected_crd = item["candidates"][0]["crd_number"]
        updated = await tools["apply_advisor_review_decisions"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "decisions": [
                    {
                        "review_item_id": item["review_item_id"],
                        "action": "confirm_candidate",
                        "crd_number": selected_crd,
                    }
                ],
                "approve_session": True,
            }
        )
        assert updated["counts"] == {
            "matched": 1,
            "ambiguous_match": 0,
            "no_match": 0,
        }

    session = store.get_advisor_match_session(
        result["match_session_id"], corp_id=corp_id
    )
    assert session["status"] == "Approved"
    assert session["decisions"][0]["automated_status"] == "Ambiguous Match"
    audit = store._connection.execute(
        "SELECT prior_decision_json, new_decision_json "
        "FROM advisor_match_review_decisions WHERE session_id=?",
        (result["match_session_id"],),
    ).fetchone()
    assert audit is not None
    with pytest.raises(KeyError):
        store.get_advisor_match_session(
            result["match_session_id"], corp_id="B654321"
        )
    output = workspace.chat_root(corp_id, conversation_id) / "advisor_matches.xlsx"
    assert verify_match_workbook(output, expected_rows=1)["matched"] == 1
    store.close()


@pytest.mark.asyncio
async def test_missing_firm_requires_explicit_continue_and_fingerprint(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.workspace_root, settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation_id,
        original_name="name-only.csv",
        content_type="text/csv",
        source=BytesIO(b"Name\nRobert Mercer\n"),
        max_bytes=1024,
    )
    backend = AdvisorWorkspaceBackend(settings.workspace_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {"full_name": {"columns": [{"index": 0, "header": "Name"}]}}
    async with backend.run_scope("run-preflight", corp_id, conversation_id):
        validation = await tools["validate_advisor_mapping"].ainvoke(
            {"input_virtual_path": "/uploads/name-only.csv", "mapping": mapping}
        )
        assert validation["input_summary"]["missing_firm_row_count"] == 1
        manifest = await tools["find_all_advisors_in_database"].ainvoke({})
        base = {
            "input_virtual_path": "/uploads/name-only.csv",
            "reference_snapshot_id": manifest["reference_snapshot_id"],
            "mapping": mapping,
        }
        with pytest.raises(ValueError, match="validate it again"):
            await tools["start_advisor_match"].ainvoke(
                {**base, "mapping_fingerprint": "0" * 64}
            )
        with pytest.raises(ValueError, match="explicitly wants to continue"):
            await tools["start_advisor_match"].ainvoke(
                {**base, "mapping_fingerprint": validation["mapping_fingerprint"]}
            )
        result = await tools["start_advisor_match"].ainvoke(
            {
                **base,
                "mapping_fingerprint": validation["mapping_fingerprint"],
                "allow_missing_firm": True,
            }
        )
        assert result["counts"]["ambiguous_match"] == 1
    store.close()


@pytest.mark.asyncio
async def test_unlisted_crd_requires_proposal_then_later_turn_confirmation(
    settings,
) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.workspace_root, settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation_id,
        original_name="unknown.csv",
        content_type="text/csv",
        source=BytesIO(b"Name\nUnknown Person\n"),
        max_bytes=1024,
    )
    backend = AdvisorWorkspaceBackend(settings.workspace_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {"full_name": {"columns": [{"index": 0, "header": "Name"}]}}
    async with backend.run_scope("run-manual", corp_id, conversation_id):
        validation = await tools["validate_advisor_mapping"].ainvoke(
            {"input_virtual_path": "/uploads/unknown.csv", "mapping": mapping}
        )
        manifest = await tools["find_all_advisors_in_database"].ainvoke({})
        result = await tools["start_advisor_match"].ainvoke(
            {
                "input_virtual_path": "/uploads/unknown.csv",
                "reference_snapshot_id": manifest["reference_snapshot_id"],
                "mapping": mapping,
                "mapping_fingerprint": validation["mapping_fingerprint"],
                "allow_missing_firm": True,
            }
        )
        page = await tools["list_advisor_match_items"].ainvoke(
            {"match_session_id": result["match_session_id"], "status": "no_match"}
        )
        assert page["total"] == 1
        unmatched = await tools["list_advisor_match_items"].ainvoke(
            {"match_session_id": result["match_session_id"], "status": "unmatched"}
        )
        assert unmatched["items"] == page["items"]
        proposal = await tools["propose_manual_crd_override"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "review_item_id": page["items"][0]["review_item_id"],
                "crd_number": "99000001",
            }
        )
        assert proposal["requires_explicit_confirmation"] is True
        with pytest.raises(ValueError, match="later user turn"):
            await tools["apply_advisor_review_decisions"].ainvoke(
                {
                    "match_session_id": result["match_session_id"],
                    "decisions": [
                        {
                            "review_item_id": page["items"][0]["review_item_id"],
                            "action": "confirm_manual_crd",
                            "proposal_id": proposal["proposal_id"],
                        }
                    ],
                }
            )
    async with backend.run_scope(
        "run-manual-confirm", corp_id, conversation_id
    ):
        confirmed = await tools["apply_advisor_review_decisions"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "decisions": [
                    {
                        "review_item_id": page["items"][0]["review_item_id"],
                        "action": "confirm_manual_crd",
                        "proposal_id": proposal["proposal_id"],
                    }
                ],
            }
        )
        assert confirmed["counts"]["matched"] == 1
    store.close()
