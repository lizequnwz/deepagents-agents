from __future__ import annotations

import io
from pathlib import Path

import pytest

from general_agent.workspace import (
    Workspace,
    WorkspacePathError,
    agent_physical_path,
    agent_virtual_path,
    corp_storage_key,
    reset_current_workspace,
    set_current_workspace,
)


def test_paths_are_virtual_rooted_and_protected(settings, tmp_path: Path) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    assert workspace.resolve("/notes.txt") == settings.workspace_root / "notes.txt"
    for unsafe in ("../secret", "a/../../secret", ".packages/secret", ".tmp/x"):
        with pytest.raises(WorkspacePathError):
            workspace.resolve(unsafe, visible_only=True)

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = settings.workspace_root / "escape"
    link.symlink_to(outside)
    with pytest.raises(WorkspacePathError):
        workspace.resolve("escape", must_exist=True)
    assert all(
        entry.name != "escape" for entry in workspace.list_entries("A123456")
    )


def test_upload_collisions_and_immutable_snapshots(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    first, protected_first = workspace.upload(
        corp_id="A123456",
        conversation_id="chat",
        original_name="report.csv",
        content_type="text/csv",
        source=io.BytesIO(b"a\n1\n"),
        max_bytes=100,
    )
    second, protected_second = workspace.upload(
        corp_id="A123456",
        conversation_id="chat",
        original_name="report.csv",
        content_type="text/csv",
        source=io.BytesIO(b"a\n2\n"),
        max_bytes=100,
    )
    assert first.relative_path != second.relative_path
    assert first.relative_path.startswith("chats/chat/uploads/")
    assert first.original_name == second.original_name == "report.csv"
    assert protected_first.read_bytes() == b"a\n1\n"
    assert protected_second.read_bytes() == b"a\n2\n"

    target = workspace.ensure_chat("A123456", "chat") / "answer.txt"
    target.write_text("version one", encoding="utf-8")
    before, baseline = workspace.stage_baseline("A123456", "run-one")
    target.write_text("version two", encoding="utf-8")
    artifacts = workspace.snapshot_changes(
        corp_id="A123456", run_id="run-one", before=before, baseline=baseline
    )
    artifact, snapshot = artifacts[0]
    assert artifact.change_type == "modified"
    assert snapshot.read_text(encoding="utf-8") == "version two"
    target.write_text("version three", encoding="utf-8")
    assert snapshot.read_text(encoding="utf-8") == "version two"


def test_deleted_file_snapshot_preserves_pre_run_bytes(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    target = workspace.shared_root("A123456") / "old.txt"
    target.write_bytes(b"old bytes")
    before, baseline = workspace.stage_baseline("A123456", "delete-run")
    target.unlink()
    artifacts = workspace.snapshot_changes(
        corp_id="A123456", run_id="delete-run", before=before, baseline=baseline
    )
    artifact, snapshot = artifacts[0]
    assert artifact.change_type == "deleted"
    assert snapshot.read_bytes() == b"old bytes"


def test_chat_scope_shared_promotion_metadata_and_cleanup(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    uploaded = workspace.manual_upload(
        corp_id="A123456",
        original_name="notes.txt",
        source=io.BytesIO(b"keep me"),
        max_bytes=100,
        scope="chat",
        conversation_id="chat-one",
    )
    assert uploaded.path == "chats/chat-one/uploads/notes.txt"
    assert uploaded.origin == "upload"
    assert uploaded.retention == "chat"
    assert uploaded.can_promote is True

    kept = workspace.promote("A123456", uploaded.path, "chat-one")
    assert kept.path == "shared/notes.txt"
    assert kept.retention == "shared"
    assert kept.origin == "upload"
    assert not (workspace.user_root("A123456") / uploaded.path).exists()

    transient = workspace.chat_root("A123456", "chat-one") / "answer.txt"
    transient.write_text("temporary chat output", encoding="utf-8")
    workspace.cleanup_chat("A123456", "chat-one")
    assert workspace.chat_root("A123456", "chat-one").is_dir()
    assert list(workspace.chat_root("A123456", "chat-one").iterdir()) == []
    assert (workspace.user_root("A123456") / kept.path).read_bytes() == b"keep me"


def test_agent_paths_are_chat_rooted_with_stable_shared_routes(settings) -> None:
    tokens = set_current_workspace("A123456", "chat-two")
    try:
        prefix = f"users/{corp_storage_key('A123456')}"
        assert agent_physical_path("/report.docx") == f"{prefix}/chats/chat-two/report.docx"
        assert agent_physical_path("/shared/reference.csv") == f"{prefix}/shared/reference.csv"
        assert agent_physical_path("/skills/pdf/SKILL.md") == ".app/skills/pdf/SKILL.md"
        assert agent_virtual_path(f"{prefix}/chats/chat-two/report.docx") == "/report.docx"
        assert agent_virtual_path(f"{prefix}/shared/reference.csv") == "/shared/reference.csv"
    finally:
        reset_current_workspace(tokens)


def test_legacy_root_files_migrate_once_without_losing_bytes(settings) -> None:
    legacy = settings.workspace_root / "legacy.txt"
    legacy.write_bytes(b"legacy bytes")
    workspace = Workspace(settings.workspace_root, settings.data_root)
    migrated = workspace.shared_root("A123456") / "legacy" / "legacy.txt"
    assert migrated.read_bytes() == b"legacy bytes"
    entry = next(
        item
        for item in workspace.list_scope(
            corp_id="A123456", scope="shared", relative_path="legacy"
        )
        if item.name == "legacy.txt"
    )
    assert entry.origin == "migration"
    assert entry.retention == "shared"
