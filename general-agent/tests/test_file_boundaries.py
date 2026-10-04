from __future__ import annotations

import os
from pathlib import Path

import pytest

from general_agent.execution import CancellableLocalShellBackend
from general_agent.workspace import (
    Workspace,
    WorkspacePathError,
    agent_physical_path,
    agent_virtual_path,
    corp_storage_key,
    reset_current_workspace,
    set_current_workspace,
)


def backend_for(settings) -> CancellableLocalShellBackend:
    return CancellableLocalShellBackend(
        settings.workspace_root,
        package_root=settings.package_root,
        temp_root=settings.temp_root,
        timeout=settings.command_timeout_seconds,
        max_output_bytes=settings.max_command_output_bytes,
    )


def test_unscoped_file_tools_fail_closed_but_managed_skills_are_readable(settings) -> None:
    backend = backend_for(settings)
    (settings.workspace_root / "visible.txt").write_text("unscoped", encoding="utf-8")
    skill = settings.installed_skills_root / "sample"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("safe managed skill", encoding="utf-8")

    for convert in (agent_physical_path, agent_virtual_path):
        with pytest.raises(WorkspacePathError, match="corporation"):
            convert("visible.txt")
    assert backend.read("/visible.txt").error
    assert backend.write("/visible.txt", "replacement").error
    assert backend.edit("/visible.txt", "unscoped", "replacement").error
    assert backend.delete("/visible.txt").error
    assert backend.ls("/").error
    assert backend.glob("**/*").error
    assert backend.grep("unscoped").error
    assert backend.download_files(["/visible.txt"])[0].error
    assert backend.upload_files([("/visible.txt", b"replacement")])[0].error
    assert backend.read("/skills/sample/SKILL.md").file_data["content"] == "safe managed skill"
    assert backend.write("/skills/sample/SKILL.md", "replacement").error


@pytest.mark.asyncio
async def test_symlink_aliases_cannot_cross_corporations_or_mutate_skills(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    own = workspace.ensure_chat("CORP_A", "chat")
    foreign = workspace.ensure_chat("CORP_B", "chat")
    (foreign / "target.txt").write_text("foreign bytes", encoding="utf-8")
    skill = settings.installed_skills_root / "sample"
    skill.mkdir(parents=True)
    (skill / "target.txt").write_text("managed bytes", encoding="utf-8")
    (own / "other").symlink_to(foreign, target_is_directory=True)
    (own / "skill-link").symlink_to(skill, target_is_directory=True)
    (own / "linked.txt").symlink_to(foreign / "target.txt")
    backend = backend_for(settings)

    async with backend.run_scope("run", "CORP_A", "chat"):
        for prefix in ("/other", "/skill-link"):
            target = prefix + "/target.txt"
            assert backend.read(target).error
            assert backend.write(target, "replacement").error
            assert backend.edit(target, "bytes", "replacement").error
            assert backend.delete(target).error
            assert backend.ls(prefix).error
            assert backend.glob("**/*", prefix).error
            assert backend.grep("bytes", prefix).error
            assert backend.upload_files([(target, b"replacement")])[0].error
            assert backend.download_files([target])[0].error
        assert backend.read("/linked.txt").error
        assert backend.ls("/").entries == []
        assert backend.glob("**/*").matches == []
        assert backend.grep("bytes").matches == []
        with pytest.raises(WorkspacePathError, match="corporation"):
            backend._to_virtual_path(foreign / "target.txt")
    assert (foreign / "target.txt").read_text() == "foreign bytes"
    assert (skill / "target.txt").read_text() == "managed bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["ripgrep", "python"])
async def test_hidden_and_protected_paths_never_reach_search_engines(settings, monkeypatch, engine) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    own = workspace.ensure_chat("CORP_A", "chat")
    (own / "visible.txt").write_text("before\nneedle public\nafter\n", encoding="utf-8")
    (own / ".env").write_text("needle SECRET_HIDDEN", encoding="utf-8")
    for directory in (".config", "__pycache__", "large_tool_results"):
        hidden = own / directory
        hidden.mkdir()
        (hidden / "private.txt").write_text("needle SECRET_PROTECTED", encoding="utf-8")
    backend = backend_for(settings)
    observed = []
    real_search = backend._ripgrep_snapshot

    def search(pattern, content, deadline, count):
        observed.append(content)
        assert b"SECRET" not in content
        return None if engine == "python" else real_search(pattern, content, deadline, count)

    monkeypatch.setattr(backend, "_ripgrep_snapshot", search)
    async with backend.run_scope("run", "CORP_A", "chat"):
        assert [entry["path"] for entry in backend.ls("/").entries] == ["/visible.txt"]
        assert [entry["path"] for entry in backend.glob("**/*").matches] == ["/visible.txt"]
        result = backend.grep("needle", glob="**/*", context_lines=1)
        assert not result.error
        assert result.matches == [{
            "path": "/visible.txt", "line": 2, "text": "needle public",
            "context_before": [{"line": 1, "text": "before"}],
            "context_after": [{"line": 3, "text": "after"}],
        }]
        assert backend.grep("needle", glob=".env").matches == []
        assert backend.grep("needle", "/.env").error
        assert backend.read("/.env").error
    assert observed == [b"before\nneedle public\nafter\n"]


@pytest.mark.asyncio
async def test_only_current_run_temporary_files_are_exposed(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    workspace.ensure_chat("CORP_A", "chat")
    backend = backend_for(settings)
    async with backend.run_scope("run-one", "CORP_A", "chat"):
        assert not backend.write("/tmp/visible.txt", "temporary").error
        assert backend.read("/tmp/visible.txt").file_data["content"] == "temporary"
        assert [entry["path"] for entry in backend.glob("**/*", "/tmp").matches] == ["/tmp/visible.txt"]
        foreign_temp = workspace.temp_root("CORP_A") / "run-two" / "secret.txt"
        foreign_temp.parent.mkdir()
        foreign_temp.write_text("other run", encoding="utf-8")
        with pytest.raises(WorkspacePathError):
            backend._to_virtual_path(foreign_temp)


@pytest.mark.parametrize("operation", ["read", "write", "edit"])
def test_file_opens_pin_parent_before_a_directory_replacement(settings, monkeypatch, operation) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    own = workspace.ensure_chat("CORP_A", "chat")
    parent = own / "folder"
    parent.mkdir()
    target = parent / "target.txt"
    target.write_text("owned bytes", encoding="utf-8")
    foreign = workspace.ensure_chat("CORP_B", "chat")
    (foreign / "target.txt").write_text("foreign bytes", encoding="utf-8")
    original_open = os.open
    replaced = False

    def replacement_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        if path == "target.txt" and dir_fd is not None and not replaced:
            replaced = True
            parent.rename(own / "pinned-folder")
            parent.symlink_to(foreign, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("general_agent.workspace.os.open", replacement_open)
    backend = backend_for(settings)
    tokens = set_current_workspace("CORP_A", "chat")
    try:
        if operation == "read":
            assert backend.read("/folder/target.txt").file_data["content"] == "owned bytes"
        elif operation == "write":
            assert not backend.write("/folder/target.txt", "owned edits").error
        else:
            assert not backend.edit("/folder/target.txt", "bytes", "edits").error
    finally:
        reset_current_workspace(tokens)
    assert (foreign / "target.txt").read_text() == "foreign bytes"


@pytest.mark.asyncio
async def test_hard_link_alias_cannot_read_or_truncate_foreign_bytes(settings) -> None:
    workspace = Workspace(settings.workspace_root, settings.data_root)
    own = workspace.ensure_chat("CORP_A", "chat")
    foreign = workspace.ensure_chat("CORP_B", "chat")
    target = foreign / "target.txt"
    target.write_text("foreign bytes", encoding="utf-8")
    os.link(target, own / "alias.txt")
    backend = backend_for(settings)
    async with backend.run_scope("run", "CORP_A", "chat"):
        assert backend.read("/alias.txt").error
        assert backend.write("/alias.txt", "replacement").error
        assert backend.edit("/alias.txt", "foreign", "replacement").error
        assert backend.grep("foreign").matches == []
        assert backend.ls("/").entries == []
    assert target.read_text() == "foreign bytes"


def test_reverse_paths_reject_other_corporations_and_hidden_paths() -> None:
    own = f"users/{corp_storage_key('CORP_A')}"
    foreign = f"users/{corp_storage_key('CORP_B')}"
    for path in (f"{foreign}/chats/chat/file.txt", f"{own}/chats/chat/.env", f"{own}/.packages/file.txt"):
        with pytest.raises(WorkspacePathError):
            agent_virtual_path(path, corp_id="CORP_A", conversation_id="chat")
