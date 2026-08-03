from __future__ import annotations

import io
from pathlib import Path

import pytest

from general_agent.workspace import Workspace, WorkspacePathError, corp_storage_key


def test_corp_storage_directory_uses_the_readable_validated_id(settings) -> None:
    workspace = Workspace(settings.data_root)

    assert corp_storage_key("A123456") == "A123456"
    assert workspace.ensure_user("A123456") == settings.data_root / "users" / "A123456"


def test_case_only_corporation_directories_are_rejected(settings) -> None:
    workspace = Workspace(settings.data_root)
    workspace.ensure_user("A123456")

    with pytest.raises(WorkspacePathError, match="differs only by letter case"):
        workspace.ensure_user("a123456")


def test_upload_is_single_immutable_corporation_scoped_copy(settings) -> None:
    workspace = Workspace(settings.data_root)
    attachment, protected = workspace.upload(
        corp_id="A123456",
        conversation_id="chat-one",
        original_name="../advisor list.csv",
        content_type="text/csv",
        source=io.BytesIO(b"Name\nAvery Stone\n"),
        max_bytes=100,
    )

    assert protected.read_bytes() == b"Name\nAvery Stone\n"
    assert protected == (
        settings.data_root
        / "users"
        / corp_storage_key("A123456")
        / "attachments"
        / attachment.attachment_id
        / "advisor list.csv"
    )
    assert attachment.sha256
    assert not (settings.project_root / "workspace" / "users").exists()


def test_protected_paths_reject_cross_corporation_and_symlink_files(
    settings, tmp_path: Path
) -> None:
    workspace = Workspace(settings.data_root)
    attachment, protected = workspace.upload(
        corp_id="A123456",
        conversation_id="chat-one",
        original_name="advisors.csv",
        content_type="text/csv",
        source=io.BytesIO(b"Name\nAvery\n"),
        max_bytes=100,
    )
    assert workspace.validate_file("A123456", "attachments", protected) == protected
    with pytest.raises(WorkspacePathError):
        workspace.validate_file("B654321", "attachments", protected)

    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"secret")
    link = protected.with_name("link.csv")
    link.symlink_to(outside)
    with pytest.raises(WorkspacePathError):
        workspace.validate_file("A123456", "attachments", link)
    assert attachment.attachment_id in protected.parts


def test_reference_and_artifact_paths_are_narrow_and_stable(settings) -> None:
    workspace = Workspace(settings.data_root)
    reference = workspace.reference_file("A123456", "ars_" + "a" * 32)
    artifact = workspace.artifact_file(
        "A123456", "run-one", "art_" + "b" * 32
    )

    assert reference.name == "advisor_reference.csv"
    assert "advisor_references" in reference.parts
    assert artifact.name == "advisor_matches.xlsx"
    assert "artifacts" in artifact.parts
    with pytest.raises(WorkspacePathError):
        workspace.reference_file("A123456", "../escape")


def test_upload_limit_cleans_partial_directory(settings) -> None:
    workspace = Workspace(settings.data_root)
    with pytest.raises(ValueError, match="exceeds"):
        workspace.upload(
            corp_id="A123456",
            conversation_id="chat-one",
            original_name="large.csv",
            content_type="text/csv",
            source=io.BytesIO(b"too large"),
            max_bytes=2,
        )
    assert list(workspace.category_root("A123456", "attachments").iterdir()) == []
