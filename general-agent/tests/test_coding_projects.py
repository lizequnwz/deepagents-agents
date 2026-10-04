from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from general_agent.coding.context import repository_context
from general_agent.coding.projects import Projects, repository_identity
from general_agent.coding.source import (
    allowed_source, ignored_source, ignored_source_parts, source_file, source_revision,
    source_snapshot, validate_source_path,
)
from general_agent.coding.store import CodingConflict, CodingStore
from general_agent.workspace import WorkspacePathError


@pytest.fixture
def registry(settings):
    store = CodingStore(settings.coding_db)
    yield Projects(settings, store)
    store.close()


def repository(settings) -> Path:
    root = settings.project_root / "source"
    root.mkdir()
    (root / "main.py").write_text("print('working source')\n")
    return root


@pytest.mark.parametrize("path", (
    "../outside", "/absolute", "a/../../outside", ".env", ".env.local", ".env.example.bak",
    "a/.secret", ".git/config", ".aws/credentials", "credentials.json", "test.pem",
    "node_modules/pkg.js", ".venv/bin/python", "workspace/.app/skills/x",
))
def test_source_policy_rejects_unsafe_names(path):
    assert not allowed_source(path)
    with pytest.raises(WorkspacePathError):
        validate_source_path(path)


def test_source_policy_allows_specific_source_dotfiles():
    for path in (".gitignore", ".env.example", ".github/workflows/check.yml", "src/main.py"):
        assert allowed_source(path)
    assert ignored_source("node_modules/pkg.js")
    assert "node_modules" in ignored_source_parts()
    assert ".git" not in ignored_source_parts()


def test_snapshot_ignores_secrets_links_generated_and_gitignore(settings):
    root = repository(settings)
    (root / ".env").write_text("SECRET_TOKEN")
    (root / ".env.example").write_text("TOKEN=placeholder")
    (root / ".gitignore").write_text("ignored.py\nsub/*.tmp\n!sub/keep.tmp\n")
    (root / "ignored.py").write_text("tracked source")
    (root / "sub").mkdir()
    (root / "sub/drop.tmp").write_text("discard")
    (root / "sub/keep.tmp").write_text("keep")
    (root / "sub/.gitignore").write_text("local.py\n")
    (root / "sub/local.py").write_text("discard")
    (root / "node_modules").mkdir()
    (root / "node_modules/pkg.js").write_text("dependency")
    (root / "alias.py").symlink_to(root / "main.py")
    os.link(root / "ignored.py", root / "hardlink.py")
    exclusions = {}
    snapshot = source_snapshot(root, exclusions=exclusions)
    assert set(snapshot) == {"main.py", ".env.example", ".gitignore", "sub/keep.tmp", "sub/.gitignore"}
    assert exclusions[".env"] == "protected_source_policy"
    assert exclusions["node_modules"] == "generated_or_dependency"
    assert exclusions["alias.py"] == "symlink"
    assert "hardlink.py" in exclusions
    assert all(b"SECRET_TOKEN" not in entry["content"] for entry in snapshot.values())


def test_snapshot_retains_tracked_ignored_sources_and_limits(settings):
    root = repository(settings)
    (root / ".gitignore").write_text("ignored/\n")
    (root / "ignored").mkdir()
    (root / "ignored/source.py").write_text("tracked")
    assert "ignored/source.py" not in source_snapshot(root)
    snapshot = source_snapshot(root, tracked_paths=("ignored/source.py",))
    assert "ignored/source.py" in snapshot
    with pytest.raises(WorkspacePathError, match="file source limit"):
        source_snapshot(root, max_files=1)
    with pytest.raises(WorkspacePathError, match="size limit"):
        source_snapshot(root, max_bytes=1)
    with pytest.raises(WorkspacePathError, match="size limit"):
        source_snapshot(root, max_file_bytes=1)
    assert source_revision(snapshot) == source_revision(dict(reversed(tuple(snapshot.items()))))
    altered = {path: dict(entry) for path, entry in snapshot.items()}
    altered["main.py"]["mode"] ^= 0o100
    assert source_revision(snapshot) != source_revision(altered)


def test_secure_source_opens_reject_alias_before_truncation(settings):
    root = repository(settings)
    outside = settings.project_root / "foreign.py"
    outside.write_text("foreign")
    (root / "link.py").symlink_to(outside)
    os.link(outside, root / "hard.py")
    for path in ("link.py", "hard.py"):
        with pytest.raises((OSError, WorkspacePathError)):
            with source_file(root, path, os.O_WRONLY | os.O_TRUNC):
                pass
    assert outside.read_text() == "foreign"


async def test_project_scope_and_secure_session_copy(registry, settings):
    root = repository(settings)
    (root / ".env").write_text("SECRET")
    (root / "main.py").chmod(0o755)
    project = await registry.register("CORP_A", root, "Source", {"test": "python -m pytest"})
    assert project["identity"] == repository_identity(root)
    assert project["onboarding"]["status"] == "ready"
    assert ".env" in project["onboarding"]["exclusions"]
    session = registry.create_session("CORP_A", project["id"])
    repo = registry.repository("CORP_A", session["id"])
    assert repo != root
    assert (repo / "main.py").read_bytes() == (root / "main.py").read_bytes()
    assert (repo / "main.py").stat().st_mode & 0o777 == 0o755
    assert not (repo / ".env").exists()
    assert not (repo / ".git").exists()
    assert session["revision"] == source_revision(source_snapshot(repo))
    (repo / "main.py").write_text("edited isolated source")
    assert (root / "main.py").read_text() == "print('working source')\n"
    with pytest.raises(KeyError):
        registry.repository("CORP_B", session["id"])
    with pytest.raises(KeyError):
        registry.create_session("CORP_B", project["id"])


async def test_ownership_claim_precedes_foreign_source_read(registry, settings, monkeypatch):
    root = repository(settings)
    await registry.register("CORP_A", root, "Source")
    monkeypatch.setattr("general_agent.coding.projects.source_snapshot", lambda *a, **kw: pytest.fail("foreign bytes read"))
    for candidate in (root, root.parent):
        with pytest.raises(CodingConflict, match="overlap"):
            await registry.register("CORP_B", candidate, "Foreign")
    nested = root / "nested"
    nested.mkdir()
    with pytest.raises(CodingConflict, match="overlap"):
        await registry.register("CORP_B", nested, "Foreign")


async def test_repository_identity_and_app_storage_rejection(registry, settings):
    root = repository(settings)
    project = await registry.register("CORP_A", root, "Source")
    moved = root.with_name("old-source")
    root.rename(moved)
    root.mkdir()
    with pytest.raises(CodingConflict, match="replaced"):
        registry.create_session("CORP_A", project["id"])
    alias = root.with_name("alias")
    alias.symlink_to(root, target_is_directory=True)
    for unsafe in (alias, settings.workspace_root, settings.data_root):
        with pytest.raises((OSError, WorkspacePathError)):
            await registry.register("CORP_A", unsafe, "Unsafe")


async def test_session_ownership_survives_atomic_runtime_source_replace(registry, settings):
    root = repository(settings)
    project = await registry.register("CORP_A", root, "Source")
    session = registry.create_session("CORP_A", project["id"])
    repo = registry.repository("CORP_A", session["id"])
    old_repo = repo.with_name("old-repo")
    repo.rename(old_repo)
    repo.mkdir()
    (repo / "main.py").write_text("reconciled container source")
    assert registry.repository("CORP_A", session["id"]) == repo
    shutil.rmtree(repo)
    repo.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        registry.repository("CORP_A", session["id"])


async def test_registering_application_repo_excludes_visible_runtime(registry, settings):
    (settings.workspace_root / "visible.txt").write_text("FOREIGN_CORP")
    (settings.project_root / "source.py").write_text("application source")
    project = await registry.register("CORP_A", settings.project_root, "Application")
    assert project["onboarding"]["exclusions"]["workspace"] == "application_storage"
    session = registry.create_session("CORP_A", project["id"])
    repo = registry.repository("CORP_A", session["id"])
    assert "source.py" in session["opening_manifest"]
    assert not (repo / "workspace").exists()
    assert not (repo / ".data").exists()


async def test_git_metadata_is_bounded_no_hooks_and_retains_tracked_ignored(registry, settings):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git unavailable")
    root = repository(settings)
    subprocess.run([git, "init", "-q", str(root)], check=True, capture_output=True)
    (root / "tracked.py").write_text("tracked source")
    subprocess.run([git, "-C", str(root), "add", "tracked.py", "main.py"], check=True, capture_output=True)
    (root / ".gitignore").write_text("tracked.py\n")
    marker = settings.project_root / "hook-ran"
    fsmonitor = root / ".git/hooks/fsmonitor"
    fsmonitor.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    fsmonitor.chmod(0o755)
    subprocess.run([git, "-C", str(root), "config", "core.fsmonitor", str(fsmonitor)], check=True, capture_output=True)
    project = await registry.register("CORP_A", root, "Source")
    assert project["onboarding"]["git"]["available"]
    assert "tracked.py" in project["onboarding"]["git"]["tracked_paths"]
    session = registry.create_session("CORP_A", project["id"])
    assert "tracked.py" in session["opening_manifest"]
    assert not marker.exists()


def test_context_scopes_instructions_and_excludes_credential_text(settings):
    root = repository(settings)
    (root / "AGENTS.md").write_text("Root guidance")
    (root / "README.md").write_text("Overview")
    (root / ".env").write_text("SECRET")
    (root / "src").mkdir()
    (root / "src/AGENTS.md").write_text("Scoped guidance")
    context = repository_context(root)
    assert {entry["path"]: entry["scope"] for entry in context["instructions"]} == {
        "AGENTS.md": "/", "src/AGENTS.md": "src/",
    }
    assert "Overview" in context["summary"]
    assert "SECRET" not in str(context)
    assert ".env" not in context["inventory"]
    assert context["instructions"][0]["sha256"] == hashlib.sha256(b"Root guidance").hexdigest()
    (root / "AGENTS.md").write_text("A" * 90_000)
    context = repository_context(root)
    assert sum(len(entry["text"]) for entry in context["instructions"]) <= 80_000
    assert len(context["summary"]) <= 20_000
    assert context["truncated"]
