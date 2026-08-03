from __future__ import annotations

import io
import shutil
import sqlite3
from pathlib import Path

import pytest

from general_agent.schemas import Artifact, RunStatus, utc_now
from general_agent.store import ActiveRunError, Store
from general_agent.workspace import Workspace, legacy_corp_storage_key


def test_per_user_active_run_and_restart_recovery(settings) -> None:
    store = Store(settings.application_db, settings.data_root)
    first = store.create_conversation("First")
    second = store.create_conversation("Second")
    run_id, _ = store.create_run(first.conversation_id, "hello")
    with pytest.raises(ActiveRunError):
        store.create_run(second.conversation_id, "blocked")
    other = store.create_conversation("Other", corp_id="B654321")
    other_run, _ = store.create_run(
        other.conversation_id, "allowed", corp_id="B654321"
    )
    store.close()

    recovered = Store(settings.application_db, settings.data_root)
    run = recovered.get_run(run_id)
    assert run.status == RunStatus.FAILED
    assert "restarted" in (run.error or "")
    assert recovered.get_run(other_run, corp_id="B654321").status == RunStatus.FAILED
    with pytest.raises(KeyError):
        recovered.get_run(run_id, corp_id="B654321")
    recovered.close()


def test_completed_history_usage_and_conversation_cleanup(settings) -> None:
    store = Store(settings.application_db, settings.data_root)
    workspace = Workspace(settings.data_root)
    conversation = store.create_conversation()
    run_id, _ = store.create_run(conversation.conversation_id, "remember only complete")
    attachment, protected = workspace.upload(
        corp_id="A123456",
        conversation_id=conversation.conversation_id,
        original_name="note.txt",
        content_type="text/plain",
        source=io.BytesIO(b"hello"),
        max_bytes=100,
    )
    store.add_attachment(run_id, attachment, protected)
    store.record_model_call(
        run_id,
        "advisor-match-agent",
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 2},
            "output_token_details": {"reasoning": 1},
        },
    )
    store.finish_run(run_id, RunStatus.COMPLETED, assistant_text="done")
    assert store.completed_history(conversation.conversation_id)[-1]["content"] == "done"
    diagnostics = store.get_run(run_id).diagnostics
    assert diagnostics.tokens.total_tokens == 14
    assert diagnostics.tokens.cached_input_tokens == 2
    assert diagnostics.token_usage_partial is False
    store.delete_conversation(conversation.conversation_id)
    assert not protected.parent.exists()
    store.close()


def test_startup_migrates_hashed_corporation_storage_and_paths(settings) -> None:
    corp_id = "A123456"
    workspace = Workspace(settings.data_root)
    store = Store(settings.application_db, settings.data_root)
    conversation = store.create_conversation(corp_id=corp_id)
    run_id, _ = store.create_run(conversation.conversation_id, "migrate", corp_id=corp_id)
    attachment, attachment_path = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        original_name="advisors.csv",
        content_type="text/csv",
        source=io.BytesIO(b"Name\nAvery Stone\n"),
        max_bytes=100,
    )
    store.add_attachment(run_id, attachment, attachment_path, corp_id=corp_id)

    snapshot_id = "ars_" + "a" * 32
    reference_path = workspace.reference_file(corp_id, snapshot_id)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_text("CRD_NUMBER\n12345\n", encoding="utf-8")
    store.create_advisor_reference_snapshot(
        snapshot_id=snapshot_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        manifest={"reference_snapshot_id": snapshot_id},
        snapshot_path=reference_path,
    )

    artifact_id = "art_" + "b" * 32
    artifact_path = workspace.artifact_file(corp_id, run_id, artifact_id)
    artifact_path.parent.mkdir(parents=True, exist_ok=False)
    artifact_path.write_bytes(b"workbook")
    store.add_artifact(
        Artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            relative_path="advisor_matches.xlsx",
            change_type="created",
            size_bytes=artifact_path.stat().st_size,
            sha256="a" * 64,
            created_at=utc_now(),
        ),
        artifact_path,
        corp_id=corp_id,
    )
    store.close()

    readable_root = settings.data_root / "users" / corp_id
    hashed_root = settings.data_root / "users" / legacy_corp_storage_key(corp_id)
    shutil.move(str(readable_root), str(hashed_root))
    (settings.data_root / "attachments" / attachment.attachment_id).mkdir(
        parents=True
    )
    historical_root = (
        settings.project_root.parent
        / "general-agent"
        / ".data"
        / "users"
        / legacy_corp_storage_key(corp_id)
    )
    _replace_stored_path_prefix(
        settings.application_db, readable_root, historical_root
    )

    migrated = Store(settings.application_db, settings.data_root)

    migrated_attachment, _, _ = migrated.attachment_path(
        attachment.attachment_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    migrated_reference = migrated.get_advisor_reference_snapshot(
        snapshot_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    migrated_artifact, _ = migrated.artifact_path(artifact_id, corp_id=corp_id)
    assert migrated_attachment == attachment_path
    assert Path(migrated_reference["snapshot_path"]) == reference_path
    assert migrated_artifact == artifact_path
    assert migrated_attachment.read_bytes() == b"Name\nAvery Stone\n"
    assert Path(migrated_reference["snapshot_path"]).read_text(encoding="utf-8") == "CRD_NUMBER\n12345\n"
    assert migrated_artifact.read_bytes() == b"workbook"
    assert not hashed_root.exists()
    migrated.close()

    reopened = Store(settings.application_db, settings.data_root)
    reopened_attachment, _, _ = reopened.attachment_path(
        attachment.attachment_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    assert reopened_attachment == attachment_path
    reopened.close()


def _replace_stored_path_prefix(
    database: Path, old_root: Path, new_root: Path
) -> None:
    connection = sqlite3.connect(database)
    try:
        for table, column in (
            ("attachments", "protected_path"),
            ("artifacts", "snapshot_path"),
            ("advisor_reference_snapshots", "snapshot_path"),
        ):
            connection.execute(
                f"UPDATE {table} SET {column}=REPLACE({column}, ?, ?)",
                (str(old_root), str(new_root)),
            )
        connection.commit()
    finally:
        connection.close()
