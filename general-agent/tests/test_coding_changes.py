from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import general_agent.coding.changes as changes_module

from general_agent.coding.changes import ChangeManager
from general_agent.coding.store import CodingConflict, identifier
from general_agent.workspace import corp_storage_key


@pytest.fixture
def proposal(settings, tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "a.py").write_text("print('user-edited baseline')\n")
    (original / "delete.txt").write_text("preserve deleted bytes\n")
    (original / "script.sh").write_text("echo hello\n")
    (original / "script.sh").chmod(0o644)
    (original / ".env").write_text("a synthetic excluded secret")
    work = tmp_path / "working"
    shutil.copytree(original, work)
    manager = ChangeManager(settings)
    session = identifier()
    before = manager.capture("alpha", session, original)
    (work / "a.py").write_text("print('agent change')\n")
    (work / "delete.txt").unlink()
    (work / "script.sh").chmod(0o755)
    (work / "asset.bin").write_bytes(b"\0\xffasset")
    (work / "nested").mkdir()
    (work / "nested" / "new.py").write_text("new = True\n")
    change = manager.finalize("alpha", session, before, work, identifier())
    return manager, session, original, work, before, change


def apply(proposal, paths=None):
    manager, session, original, work, _, change = proposal
    return manager.apply("alpha", session, change["id"], original, work,
                         change["revision"], paths,
                         expected_root_identity=manager._root_identity(original))


def test_complete_immutable_versions_and_bounded_review(proposal):
    manager, session, original, work, before, change = proposal
    assert ".env" not in before["files"]
    kinds = {entry["path"]: entry["kind"] for entry in change["files"]}
    assert kinds == {"a.py": "modified", "asset.bin": "created", "delete.txt": "deleted",
                     "nested/new.py": "created", "script.sh": "modified"}
    (work / "a.py").write_text("later draft")
    (original / "delete.txt").write_text("later original")
    diff = manager.diff("alpha", session, change["id"])
    assert "user-edited baseline" in diff["text"]
    assert "agent change" in diff["text"]
    assert "preserve deleted bytes" in diff["text"]
    assert "later draft" not in diff["text"]
    assert "Mode 0644 -> 0755" in diff["text"]
    assert any(entry["binary"] for entry in diff["files"])
    bounded = manager.diff("alpha", session, change["id"], max_chars=40)
    assert bounded["truncated"] and len(bounded["text"]) == 40


def test_apply_and_revert_preserve_bytes_modes_and_unrelated_user_edits(proposal):
    manager, session, original, work, before, _ = proposal
    (original / "unrelated.txt").write_text("external work")
    journal = apply(proposal)
    assert journal["status"] == "applied"
    assert (original / "a.py").read_text() == (work / "a.py").read_text()
    assert not (original / "delete.txt").exists()
    assert (original / "asset.bin").read_bytes() == b"\0\xffasset"
    assert (original / "script.sh").stat().st_mode & 0o777 == 0o755
    assert (original / "unrelated.txt").read_text() == "external work"
    assert set(journal["selected_paths"]) <= journal["applied_manifest"]["files"].keys() | {"delete.txt"}
    reverted = manager.revert("alpha", session, journal["id"], original,
                              expected_root_identity=journal["source_root_identity"])
    assert reverted["status"] == "reverted"
    assert (original / "delete.txt").read_text() == "preserve deleted bytes\n"
    assert not (original / "asset.bin").exists()
    assert not (original / "nested" / "new.py").exists()
    assert (original / "script.sh").stat().st_mode & 0o777 == 0o644
    assert (original / "unrelated.txt").read_text() == "external work"
    assert reverted["reverted_manifest"]["files"]["a.py"] == before["files"]["a.py"]


def test_partial_apply_only_touches_selected_paths(proposal):
    _, _, original, _, _, _ = proposal
    journal = apply(proposal, ["a.py"])
    assert journal["selected_paths"] == ["a.py"]
    assert (original / "a.py").read_text() == "print('agent change')\n"
    assert (original / "delete.txt").exists()
    assert not (original / "asset.bin").exists()
    assert (original / "script.sh").stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("drift", ["source", "work", "revision", "mode"])
def test_stale_review_conflicts_before_any_source_mutation(proposal, drift):
    manager, session, original, work, _, change = proposal
    revision = change["revision"]
    if drift == "source":
        (original / "delete.txt").write_text("external edit")
    elif drift == "work":
        (work / "a.py").write_text("new draft")
    elif drift == "mode":
        (original / "delete.txt").chmod(0o600)
    else:
        revision = "old revision"
    with pytest.raises(CodingConflict):
        manager.apply("alpha", session, change["id"], original, work, revision,
                      expected_root_identity=manager._root_identity(original))
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
    assert not (original / "asset.bin").exists()


def test_revert_refuses_later_edits_before_touching_other_files(proposal):
    manager, session, original, _, _, _ = proposal
    journal = apply(proposal)
    (original / "a.py").write_text("new external work")
    with pytest.raises(CodingConflict):
        manager.revert("alpha", session, journal["id"], original,
                       expected_root_identity=journal["source_root_identity"])
    assert (original / "a.py").read_text() == "new external work"
    assert (original / "asset.bin").exists()
    assert not (original / "delete.txt").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_all_targets_preflight_rejects_symlink_and_alias_before_write(proposal, kind):
    _, _, original, _, _, _ = proposal
    external = original.parent / "external"
    external.write_text("outside")
    if kind == "symlink":
        (original / "nested").symlink_to(external.parent, target_is_directory=True)
    else:
        external.unlink()
        external.hardlink_to(original / "delete.txt")
    with pytest.raises((CodingConflict, OSError, ValueError)):
        apply(proposal)
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
    assert external.read_text() == ("outside" if kind == "symlink" else "preserve deleted bytes\n")


def test_partial_failure_compensates_and_retains_journal(proposal, monkeypatch):
    manager, session, original, _, _, _ = proposal
    replace = manager._replace

    def fail_second(root, path, expected, desired, data, **kwargs):
        if path == "asset.bin" and desired is not None:
            raise OSError("synthetic write failure")
        return replace(root, path, expected, desired, data, **kwargs)

    monkeypatch.setattr(manager, "_replace", fail_second)
    with pytest.raises(OSError, match="synthetic"):
        apply(proposal)
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
    journals = manager._session("alpha", session) / "journals"
    record = manager.journal("alpha", session, next(journals.glob("*.json")).stem)
    assert record["status"] == "rolled_back"
    assert record["error"] == "synthetic write failure"


def test_compensation_preserves_external_edit_and_blocks_next_apply(proposal, monkeypatch):
    manager, session, original, _, _, _ = proposal
    replace = manager._replace

    def edit_then_fail(root, path, expected, desired, data, **kwargs):
        if path == "asset.bin" and desired is not None:
            (original / "a.py").write_text("new external work during apply")
            raise OSError("synthetic failure")
        return replace(root, path, expected, desired, data, **kwargs)

    monkeypatch.setattr(manager, "_replace", edit_then_fail)
    with pytest.raises(OSError):
        apply(proposal)
    assert (original / "a.py").read_text() == "new external work during apply"
    journals = manager._session("alpha", session) / "journals"
    record = manager.journal("alpha", session, next(journals.glob("*.json")).stem)
    assert record["status"] == "conflicted"
    assert record["conflicts"][0]["path"] == "a.py"
    with pytest.raises(CodingConflict, match="unresolved"):
        apply(proposal)


def test_restart_recovers_interrupted_partial_apply_from_original_versions(proposal):
    manager, session, original, _, _, change = proposal
    entry = next(row for row in change["files"] if row["path"] == "a.py")
    journal = {"id": identifier(), "change_id": change["id"], "source_root": str(original),
               "source_root_identity": manager._root_identity(original), "created": "2026-10-03",
               "selected_paths": ["a.py"], "files": [entry], "status": "applying", "error": None}
    manager._save_json(manager._record_path("alpha", session, "journals", journal["id"]),
                       journal, immutable=True)
    manager._replace(original, "a.py", entry["before"], entry["after"],
                     manager.blob("alpha", session, entry["after"]["sha256"]),
                     root_identity=journal["source_root_identity"], operation_id=journal["id"])
    restarted = ChangeManager(manager.settings)
    recovered = restarted.recover("alpha", session, original,
                                  expected_root_identity=journal["source_root_identity"])
    assert recovered[0]["status"] == "rolled_back"
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"


def test_immutable_blobs_and_change_records_are_scoped(proposal):
    manager, session, _, _, before, change = proposal
    sha = before["files"]["a.py"]["sha256"]
    for corp, owning_session in (("beta", session), ("alpha", identifier())):
        with pytest.raises(FileNotFoundError):
            manager.blob(corp, owning_session, sha)
        with pytest.raises(FileNotFoundError):
            manager.get(corp, owning_session, change["id"])
    with pytest.raises(ValueError):
        manager.get("alpha", "../escape", change["id"])
    with pytest.raises(ValueError):
        manager.blob("alpha", session, "../escape")
    blob = manager._session("alpha", session) / "blobs" / sha
    blob.chmod(0o600)
    blob.write_text("tampered")
    with pytest.raises(CodingConflict, match="integrity"):
        manager.blob("alpha", session, sha)


def test_changed_review_metadata_is_rejected_before_application(proposal):
    manager, session, original, _, _, change = proposal
    stored = manager._record_path("alpha", session, "changes", change["id"])
    record = manager.get("alpha", session, change["id"])
    record["files"][0]["path"] = "other.py"
    stored.chmod(0o600)
    stored.write_text(json.dumps(record))
    with pytest.raises(CodingConflict, match="metadata.*integrity"):
        apply(proposal)
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"


def test_concurrent_apply_admits_one_writer_and_preserves_complete_result(proposal):
    manager, session, original, _, _, _ = proposal

    def try_apply(_):
        try:
            return apply(proposal)["status"]
        except CodingConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(try_apply, range(4)))
    assert outcomes.count("applied") == 1
    assert outcomes.count("conflict") == 3
    assert (original / "a.py").read_text() == "print('agent change')\n"
    assert not (original / "delete.txt").exists()
    assert len(manager.journals("alpha", session)) == 1


def test_snapshot_retains_baseline_source_when_gitignore_changes(settings, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("keep me")
    manager, session = ChangeManager(settings), identifier()
    before = manager.capture("alpha", session, repo)
    (repo / ".gitignore").write_text("a.py\n")
    change = manager.finalize("alpha", session, before, repo, identifier())
    assert change["after"]["files"]["a.py"] == before["files"]["a.py"]
    assert [entry["path"] for entry in change["files"]] == [".gitignore"]


def test_quota_admission_rejects_before_writing_new_versions(settings, tmp_path):
    settings = replace(settings, coding_storage_mb=1)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "large.bin").write_bytes(b"a" * (600 * 1024))
    manager, session = ChangeManager(settings), identifier()
    manager.capture("alpha", session, repo)
    changed = b"b" * (600 * 1024)
    (repo / "large.bin").write_bytes(changed)
    with pytest.raises(ValueError, match="storage limit"):
        manager.capture("alpha", session, repo)
    candidate = manager.root / corp_storage_key("alpha") / session / "blobs" / hashlib.sha256(changed).hexdigest()
    assert not candidate.exists()


def test_recovery_refuses_replaced_original_root(proposal):
    manager, session, original, _, _, _ = proposal
    journal = apply(proposal, ["a.py"])
    journal["status"] = "applying"
    manager._save_json(manager._record_path("alpha", session, "journals", journal["id"]), journal)
    moved = original.with_name("moved-original")
    original.rename(moved)
    shutil.copytree(moved, original)
    with pytest.raises(CodingConflict, match="repository root was replaced"):
        manager.recover("alpha", session, original,
                        expected_root_identity=journal["source_root_identity"])
    assert (original / "a.py").read_text() == "print('agent change')\n"
    assert (moved / "a.py").read_text() == "print('agent change')\n"


def test_restart_recovers_interrupted_revert_to_applied_state(proposal):
    manager, session, original, _, _, _ = proposal
    journal = apply(proposal)
    journal["status"] = "reverting"
    manager._save_json(manager._record_path("alpha", session, "journals", journal["id"]), journal)
    entry = next(row for row in journal["files"] if row["path"] == "a.py")
    manager._replace(original, "a.py", entry["after"], entry["before"],
                     manager.blob("alpha", session, entry["before"]["sha256"]),
                     root_identity=journal["source_root_identity"], operation_id=journal["id"])
    recovered = ChangeManager(manager.settings).recover("alpha", session, original,
                        expected_root_identity=journal["source_root_identity"])
    assert recovered[0]["status"] == "applied"
    assert (original / "a.py").read_text() == "print('agent change')\n"


def test_original_application_workspace_is_excluded_but_session_repo_is_retained(settings):
    manager, session = ChangeManager(settings), identifier()
    (settings.workspace_root / "visible.txt").write_text("runtime data")
    (settings.project_root / "source.py").write_text("source")
    captured = manager.capture("alpha", session, settings.project_root)
    assert "source.py" in captured["files"]
    assert not any(path.startswith("workspace/") for path in captured["files"])
    session_repo = manager._session("alpha", session) / "repo"
    session_repo.mkdir()
    (session_repo / "source.py").write_text("session source")
    assert "source.py" in manager.capture("alpha", session, session_repo)["files"]


@pytest.mark.parametrize("partial", [False, True])
def test_restart_reclaims_intact_staging_and_preserves_partial_recovery_bytes(proposal, partial):
    manager, session, original, _, _, _ = proposal
    journal = apply(proposal, ["a.py"])
    journal["status"] = "applying"
    manager._save_json(manager._record_path("alpha", session, "journals", journal["id"]), journal)
    entry = journal["files"][0]
    staged = original / manager._temporary_name(journal["id"], entry["path"])
    content = manager.blob("alpha", session, entry["after"]["sha256"])
    staged.write_bytes(content[:3] if partial else content)
    restarted = ChangeManager(manager.settings)
    if partial:
        with pytest.raises(CodingConflict, match="recovery conflicts"):
            restarted.recover("alpha", session, original,
                              expected_root_identity=journal["source_root_identity"])
        assert staged.read_bytes() == content[:3]
    else:
        recovered = restarted.recover("alpha", session, original,
                                      expected_root_identity=journal["source_root_identity"])
        assert recovered[0]["status"] == "rolled_back"
        assert not staged.exists()
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"


@pytest.mark.parametrize("relative", ["workspace/users/beta/chats/chat/result.txt",
                                      "workspace/new/nested/new.py"])
def test_copied_application_paths_cannot_be_applied_to_original_runtime_storage(
    settings, tmp_path, relative, monkeypatch,
):
    manager, session = ChangeManager(settings), identifier()
    original = settings.project_root
    (original / "source.py").write_text("ordinary source")
    existing = settings.workspace_root / "users" / "beta" / "chats" / "chat" / "result.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("foreign corporation bytes")
    before = manager.capture("alpha", session, original)
    working = tmp_path / "isolated"
    working.mkdir()
    (working / "source.py").write_text("ordinary source")
    proposal = working / relative
    proposal.parent.mkdir(parents=True)
    proposal.write_text("attempted runtime write")
    change = manager.finalize("alpha", session, before, working, identifier())
    assert relative in {entry["path"] for entry in change["files"]}

    def no_original_file_read(*args, **kwargs):
        raise AssertionError("Protected apply target was read before its policy check.")

    monkeypatch.setattr(manager, "_at", no_original_file_read)
    with pytest.raises(CodingConflict, match="Application storage"):
        manager.apply("alpha", session, change["id"], original, working, change["revision"],
                      expected_root_identity=manager._root_identity(original))
    assert existing.read_text() == "foreign corporation bytes"
    assert not (settings.workspace_root / "new").exists()
    assert (original / "source.py").read_text() == "ordinary source"


@pytest.mark.parametrize("operation", ["apply", "revert", "recover"])
def test_registered_root_swap_before_worker_admission_is_rejected_without_file_reads(
    proposal, operation, monkeypatch,
):
    manager, session, original, working, _, change = proposal
    registered_identity = manager._root_identity(original)
    journal = apply(proposal, ["a.py"])
    moved = original.with_name("registered-original")
    original.rename(moved)
    shutil.copytree(moved, original)

    def no_source_capture(*args, **kwargs):
        raise AssertionError("The substituted source was read before registered-identity admission.")

    monkeypatch.setattr(manager, "capture", no_source_capture)
    with pytest.raises(CodingConflict, match="root was replaced before admission"):
        if operation == "apply":
            manager.apply("alpha", session, change["id"], original, working, change["revision"],
                          expected_root_identity=registered_identity)
        elif operation == "revert":
            manager.revert("alpha", session, journal["id"], original,
                           expected_root_identity=registered_identity)
        else:
            manager.recover("alpha", session, original, expected_root_identity=registered_identity)
    assert (original / "a.py").read_text() == "print('agent change')\n"
    assert (moved / "a.py").read_text() == "print('agent change')\n"


def isolated_proposal(proposal):
    manager, session, original, working, before, change = proposal
    isolated = manager._session("alpha", session) / "repo"
    working.rename(isolated)
    return manager, session, original, isolated, before, change


def test_discard_restores_only_isolated_frozen_baseline_and_preserves_original(proposal, monkeypatch):
    manager, session, original, working, before, change = isolated_proposal(proposal)

    def no_original_parent(*args, **kwargs):
        raise AssertionError("Discard reached the original apply broker.")

    monkeypatch.setattr(manager, "_parent", no_original_parent)
    result = manager.discard("alpha", session, change["id"], working, change["revision"])
    assert result == before
    assert (working / "a.py").read_text() == "print('user-edited baseline')\n"
    assert (working / "delete.txt").read_text() == "preserve deleted bytes\n"
    assert (working / "script.sh").stat().st_mode & 0o777 == 0o644
    assert not (working / "asset.bin").exists()
    assert not (working / "nested").exists()
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
    assert (original / ".env").read_text() == "a synthetic excluded secret"
    assert manager.discard_journals("alpha", session)[0]["status"] == "discarded"


@pytest.mark.parametrize("drift", ["revision", "working", "wrong_root"])
def test_discard_rejects_stale_or_out_of_scope_proposals(proposal, drift):
    manager, session, original, working, _, change = isolated_proposal(proposal)
    revision, root = change["revision"], working
    if drift == "revision":
        revision = "obsolete"
    elif drift == "working":
        (working / "a.py").write_text("follow-up work")
    else:
        root = original
    with pytest.raises(CodingConflict):
        manager.discard("alpha", session, change["id"], root, revision)
    assert (working / "a.py").read_text() == ("follow-up work" if drift == "working" else "print('agent change')\n")
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
    assert manager.discard_journals("alpha", session) == []


def test_discard_compensates_failed_directory_commit(proposal, monkeypatch):
    manager, session, original, working, _, change = isolated_proposal(proposal)
    rename = changes_module.os.rename

    def fail_commit(source, destination, **kwargs):
        if source.endswith(".staged"):
            raise OSError("synthetic discard commit failure")
        return rename(source, destination, **kwargs)

    monkeypatch.setattr(changes_module.os, "rename", fail_commit)
    with pytest.raises(OSError, match="discard commit failure"):
        manager.discard("alpha", session, change["id"], working, change["revision"])
    assert (working / "a.py").read_text() == "print('agent change')\n"
    assert (working / "asset.bin").exists()
    assert manager.discard_journals("alpha", session)[0]["status"] == "rolled_back"
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"


@pytest.mark.parametrize("boundary", ["after_move", "after_commit"])
def test_discard_recovers_process_exit_between_directory_moves(proposal, monkeypatch, boundary):
    manager, session, original, working, before, change = isolated_proposal(proposal)
    rename = changes_module.os.rename

    class ProcessExit(BaseException):
        pass

    def interrupted(source, destination, **kwargs):
        if boundary == "after_move" and source.endswith(".staged"):
            raise ProcessExit()
        result = rename(source, destination, **kwargs)
        if boundary == "after_commit" and source.endswith(".staged"):
            raise ProcessExit()
        return result

    monkeypatch.setattr(changes_module.os, "rename", interrupted)
    with pytest.raises(ProcessExit):
        manager.discard("alpha", session, change["id"], working, change["revision"])
    monkeypatch.setattr(changes_module.os, "rename", rename)
    recovered = ChangeManager(manager.settings).recover_discards("alpha", session)
    assert recovered[0]["status"] == ("rolled_back" if boundary == "after_move" else "discarded")
    result = manager.capture("alpha", session, working, tracked_paths=tuple(before["files"]))
    assert result["revision"] == (change["after_revision"] if boundary == "after_move" else before["revision"])
    assert (original / "a.py").read_text() == "print('user-edited baseline')\n"
