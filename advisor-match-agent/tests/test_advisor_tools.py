from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

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


def _upload(
    workspace: Workspace,
    store: Store,
    *,
    corp_id: str,
    conversation_id: str,
    run_id: str,
    name: str,
    content: bytes,
) -> str:
    attachment, protected = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation_id,
        original_name=name,
        content_type="text/csv",
        source=BytesIO(content),
        max_bytes=1024 * 1024,
    )
    store.add_attachment(run_id, attachment, protected, corp_id=corp_id)
    return attachment.attachment_id


@pytest.mark.asyncio
async def test_three_stage_match_review_and_regeneration(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    first_run_id, _ = store.create_run(
        conversation_id, "match", corp_id=corp_id
    )
    attachment_id = _upload(
        workspace,
        store,
        corp_id=corp_id,
        conversation_id=conversation_id,
        run_id=first_run_id,
        name="advisors.csv",
        content=(
            b"Advisor Name,Firm,City,State\n"
            b"John Smith,Northstar Wealth Partners,Boston,MA\n"
        ),
    )
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {
        "full_name": {"columns": [{"index": 0, "header": "Advisor Name"}]},
        "firm_name": {"columns": [{"index": 1, "header": "Firm"}]},
        "city": {"columns": [{"index": 2, "header": "City"}]},
        "state": {"columns": [{"index": 3, "header": "State"}]},
    }

    async with backend.run_scope(first_run_id, corp_id, conversation_id):
        profile = await tools["inspect_advisor_upload"].ainvoke(
            {"attachment_id": attachment_id}
        )
        candidate = profile["sheets"][0]["header_candidates"][0]
        assert candidate["row_number"] == 1
        assert candidate["columns"][0]["header"] == "Advisor Name"

        validation = await tools["validate_advisor_input"].ainvoke(
            {
                "attachment_id": attachment_id,
                "mapping": mapping,
            }
        )
        assert validation["input_summary"]["data_row_count"] == 1
        assert validation["input_summary"]["missing_firm_confirmation_required"] is False

        manifest = await tools["find_all_advisors"].ainvoke({})
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

        result = await tools["create_advisor_match"].ainvoke(
            {
                "attachment_id": attachment_id,
                "reference_snapshot_id": manifest["reference_snapshot_id"],
                "mapping": mapping,
                "mapping_fingerprint": validation["mapping_fingerprint"],
            }
        )
        assert result["counts"]["ambiguous_match"] == 1
        assert result["interpreted_mapping"] == validation["mapping"]
        with pytest.raises(ValueError, match="Retrieve a fresh snapshot"):
            await tools["create_advisor_match"].ainvoke(
                {
                    "attachment_id": attachment_id,
                    "reference_snapshot_id": manifest["reference_snapshot_id"],
                    "mapping": mapping,
                    "mapping_fingerprint": validation["mapping_fingerprint"],
                }
            )
        current = await tools["get_current_advisor_match"].ainvoke({})
        assert current["match_session_id"] == result["match_session_id"]
        assert current["counts"] == result["counts"]
        assert current["interpreted_mapping"] == result["interpreted_mapping"]

        page = await tools["list_advisor_match_results"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "status": "Ambiguous Match",
            }
        )
        item = page["items"][0]
        assert "internal_score" not in item["candidates"][0]
        assert item["candidates"][0]["supporting_evidence"]
        selected_crd = item["candidates"][0]["crd_number"]
        updated = await tools["apply_advisor_match_decisions"].ainvoke(
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
    output, _ = store.artifact_path(updated["output_artifact_id"], corp_id=corp_id)
    assert verify_match_workbook(output, expected_rows=1)["matched"] == 1
    artifacts = store.get_conversation(conversation_id, corp_id=corp_id).turns[0].artifacts
    assert [artifact.revision for artifact in artifacts] == [1, 2]
    store.close()


@pytest.mark.asyncio
async def test_missing_firm_requires_explicit_continue_and_fingerprint(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    first_run_id, _ = store.create_run(
        conversation_id, "match", corp_id=corp_id
    )
    attachment_id = _upload(
        workspace,
        store,
        corp_id=corp_id,
        conversation_id=conversation_id,
        run_id=first_run_id,
        name="name-only.csv",
        content=b"Name\nRobert Mercer\n",
    )
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {"full_name": {"columns": [{"index": 0, "header": "Name"}]}}
    async with backend.run_scope(first_run_id, corp_id, conversation_id):
        validation = await tools["validate_advisor_input"].ainvoke(
            {"attachment_id": attachment_id, "mapping": mapping}
        )
        assert validation["input_summary"]["missing_firm_row_count"] == 1
        with pytest.raises(ValueError, match="later user turn"):
            await tools["apply_firm_to_advisor_upload"].ainvoke(
                {"firm_name": "Cedar Grove Advisory"}
            )

    store.finish_run(first_run_id, "completed", corp_id=corp_id)
    second_run_id, _ = store.create_run(
        conversation_id, "No firm is available; continue", corp_id=corp_id
    )
    async with backend.run_scope(second_run_id, corp_id, conversation_id):
        checkpoint = await tools["get_current_advisor_input"].ainvoke({})
        assert checkpoint["mapping_fingerprint"] == validation["mapping_fingerprint"]
        manifest = await tools["find_all_advisors"].ainvoke({})
        base = {
            "attachment_id": attachment_id,
            "reference_snapshot_id": manifest["reference_snapshot_id"],
            "mapping": mapping,
        }
        with pytest.raises(ValueError, match="validate it again"):
            await tools["create_advisor_match"].ainvoke(
                {**base, "mapping_fingerprint": "0" * 64}
            )
        with pytest.raises(ValueError, match="explicit permission"):
            await tools["create_advisor_match"].ainvoke(
                {**base, "mapping_fingerprint": validation["mapping_fingerprint"]}
            )
        result = await tools["create_advisor_match"].ainvoke(
            {
                **base,
                "mapping_fingerprint": validation["mapping_fingerprint"],
                "allow_missing_firm": True,
            }
        )
        assert result["counts"]["ambiguous_match"] == 1
    store.close()


@pytest.mark.asyncio
async def test_user_confirmed_firm_creates_derived_input_and_audited_match(
    settings,
) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    first_run_id, _ = store.create_run(
        conversation_id, "match this file", corp_id=corp_id
    )
    original = b"Name,City,State\nRobert Mercer,Richmond,VA\n"
    attachment_id = _upload(
        workspace,
        store,
        corp_id=corp_id,
        conversation_id=conversation_id,
        run_id=first_run_id,
        name="name-and-location.csv",
        content=original,
    )
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {
        "full_name": {"columns": [{"index": 0, "header": "Name"}]},
        "city": {"columns": [{"index": 1, "header": "City"}]},
        "state": {"columns": [{"index": 2, "header": "State"}]},
    }

    async with backend.run_scope(first_run_id, corp_id, conversation_id):
        initial = await tools["validate_advisor_input"].ainvoke(
            {"attachment_id": attachment_id, "mapping": mapping}
        )
        assert initial["input_summary"]["missing_firm_confirmation_required"] is True

    store.finish_run(first_run_id, "completed", corp_id=corp_id)
    second_run_id, _ = store.create_run(
        conversation_id,
        "all advisors are with Cedar Grove Advisory",
        corp_id=corp_id,
    )
    async with backend.run_scope(second_run_id, corp_id, conversation_id):
        checkpoint = await tools["get_current_advisor_input"].ainvoke({})
        assert checkpoint["attachment_id"] == attachment_id
        assert checkpoint["mapping"] == initial["mapping"]

        augmented = await tools["apply_firm_to_advisor_upload"].ainvoke(
            {
                "firm_name": "Cedar Grove Advisory",
            }
        )
        assert augmented["source_attachment_id"] == attachment_id
        assert augmented["rows_updated"] == 1
        assert augmented["mapping"]["firm_name"]["columns"] == [
            {"index": 3, "header": "Firm Name"}
        ]

        derived_id = augmented["attachment_id"]
        derived_path, derived_name, derived_sha256 = store.attachment_path(
            derived_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
        assert derived_name == "name-and-location_with_firm.csv"
        assert derived_sha256 == augmented["derived_sha256"]
        assert "Cedar Grove Advisory" in derived_path.read_text(encoding="utf-8-sig")
        original_path, _, _ = store.attachment_path(
            attachment_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
        assert original_path.read_bytes() == original

        validation = await tools["validate_advisor_input"].ainvoke(
            {
                "attachment_id": derived_id,
                "mapping": augmented["mapping"],
            }
        )
        assert validation["input_summary"]["missing_firm_row_count"] == 0
        assert validation["source_transformation"]["firm_name"] == (
            "Cedar Grove Advisory"
        )
        manifest = await tools["find_all_advisors"].ainvoke({})
        result = await tools["create_advisor_match"].ainvoke(
            {
                "attachment_id": derived_id,
                "reference_snapshot_id": manifest["reference_snapshot_id"],
                "mapping": augmented["mapping"],
                "mapping_fingerprint": validation["mapping_fingerprint"],
            }
        )
        assert result["counts"] == {
            "matched": 1,
            "ambiguous_match": 0,
            "no_match": 0,
        }
        assert result["source_transformation"]["rows_updated"] == 1

    session = store.get_advisor_match_session(result["match_session_id"], corp_id=corp_id)
    assert session["source_attachment_id"] == derived_id
    assert session["source_transformation"]["source_attachment_id"] == attachment_id
    workbook_path, _ = store.artifact_path(result["output_artifact_id"], corp_id=corp_id)
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        summary = dict(workbook["Run Summary"].iter_rows(min_row=2, values_only=True))
        assert summary["Input Transformation"] == (
            "User-confirmed bulk firm augmentation"
        )
        assert summary["User-Supplied Firm"] == "Cedar Grove Advisory"
        assert summary["Rows Augmented With Firm"] == 1
    finally:
        workbook.close()
    turn_attachments = store.get_conversation(
        conversation_id, corp_id=corp_id
    ).turns[1].attachments
    derived_attachment = next(
        item for item in turn_attachments if item.attachment_id == derived_id
    )
    assert derived_attachment.derived_from_attachment_id == attachment_id
    assert derived_attachment.transformation["type"] == "bulk_firm_augmentation"
    store.close()


@pytest.mark.asyncio
async def test_attachment_id_cannot_cross_conversations(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    first = store.create_conversation(corp_id=corp_id)
    first_run_id, _ = store.create_run(
        first.conversation_id, "upload", corp_id=corp_id
    )
    attachment_id = _upload(
        workspace,
        store,
        corp_id=corp_id,
        conversation_id=first.conversation_id,
        run_id=first_run_id,
        name="private.csv",
        content=b"Name\nPrivate Person\n",
    )
    store.finish_run(first_run_id, "completed", corp_id=corp_id)

    second = store.create_conversation(corp_id=corp_id)
    second_run_id, _ = store.create_run(
        second.conversation_id, "inspect", corp_id=corp_id
    )
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    tools = _tools(settings, workspace, backend, store)
    async with backend.run_scope(second_run_id, corp_id, second.conversation_id):
        with pytest.raises(ValueError, match="No validated advisor input"):
            await tools["get_current_advisor_input"].ainvoke({})
        with pytest.raises(ValueError, match="unknown in the current chat"):
            await tools["inspect_advisor_upload"].ainvoke(
                {"attachment_id": attachment_id}
            )
        with pytest.raises(ValueError, match="Validate an advisor input"):
            await tools["apply_firm_to_advisor_upload"].ainvoke(
                {
                    "attachment_id": attachment_id,
                    "mapping": {
                        "full_name": {
                            "columns": [{"index": 0, "header": "Name"}]
                        }
                    },
                    "firm_name": "Private Firm",
                }
            )
    store.close()


@pytest.mark.asyncio
async def test_unlisted_crd_requires_proposal_then_later_turn_confirmation(
    settings,
) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation_id = store.create_conversation(corp_id=corp_id).conversation_id
    first_run_id, _ = store.create_run(
        conversation_id, "match", corp_id=corp_id
    )
    attachment_id = _upload(
        workspace,
        store,
        corp_id=corp_id,
        conversation_id=conversation_id,
        run_id=first_run_id,
        name="unknown.csv",
        content=b"Name\nUnknown Person\n",
    )
    backend = AdvisorWorkspaceBackend(settings.runtime_root)
    tools = _tools(settings, workspace, backend, store)
    mapping = {"full_name": {"columns": [{"index": 0, "header": "Name"}]}}
    async with backend.run_scope(first_run_id, corp_id, conversation_id):
        validation = await tools["validate_advisor_input"].ainvoke(
            {"attachment_id": attachment_id, "mapping": mapping}
        )
        manifest = await tools["find_all_advisors"].ainvoke({})
        result = await tools["create_advisor_match"].ainvoke(
            {
                "attachment_id": attachment_id,
                "reference_snapshot_id": manifest["reference_snapshot_id"],
                "mapping": mapping,
                "mapping_fingerprint": validation["mapping_fingerprint"],
                "allow_missing_firm": True,
            }
        )
        page = await tools["list_advisor_match_results"].ainvoke(
            {"match_session_id": result["match_session_id"], "status": "no_match"}
        )
        assert page["total"] == 1
        unmatched = await tools["list_advisor_match_results"].ainvoke(
            {"match_session_id": result["match_session_id"], "status": "unmatched"}
        )
        assert unmatched["items"] == page["items"]
        proposal = await tools["propose_crd_match"].ainvoke(
            {
                "match_session_id": result["match_session_id"],
                "review_item_id": page["items"][0]["review_item_id"],
                "crd_number": "99000001",
            }
        )
        assert proposal["requires_explicit_confirmation"] is True
        with pytest.raises(ValueError, match="later user turn"):
            await tools["apply_advisor_match_decisions"].ainvoke(
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
    store.finish_run(first_run_id, "completed", corp_id=corp_id)
    confirm_run_id, _ = store.create_run(
        conversation_id, "confirm", corp_id=corp_id
    )
    async with backend.run_scope(confirm_run_id, corp_id, conversation_id):
        confirmed = await tools["apply_advisor_match_decisions"].ainvoke(
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
