"""User-brokered repository ownership and isolated source-session creation."""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

from general_agent.coding.source import allowed_source, source_file, source_revision, source_snapshot
from general_agent.coding.store import CodingConflict, CodingStore, identifier, now
from general_agent.config import Settings
from general_agent.processes import ProcessSupervisor
from general_agent.workspace import (
    WorkspacePathError, corp_storage_key, remove_workspace_tree, workspace_directory,
)


_IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
_GIT_REVISION = re.compile(r"^[a-f0-9]{40,64}$")
_PINNED_GIT = "import os,sys; os.fchdir(int(sys.argv[1])); os.execv(sys.argv[2], sys.argv[2:])"


def repository_identity(root: Path) -> dict[str, int]:
    """Pin every ancestor without following links, then identify the root."""

    with workspace_directory(root, root) as descriptor:
        info = os.fstat(descriptor)
        return {"device": info.st_dev, "inode": info.st_ino}


class Projects:
    def __init__(self, settings: Settings, store: CodingStore):
        self.settings = settings
        self.store = store
        self._lock = threading.RLock()
        with workspace_directory(settings.project_root, settings.coding_root, create=True):
            pass

    @property
    def excluded_roots(self) -> tuple[Path, ...]:
        return (self.settings.data_root, self.settings.workspace_root,
                self.settings.project_root / ".venv")

    def _approved_root(self, value: str | Path) -> tuple[Path, dict[str, int]]:
        root = Path(value)
        if not root.is_absolute() or any(part in {"..", "~"} for part in root.parts):
            raise WorkspacePathError("Choose an absolute repository root without traversal or symlinks.")
        identity = repository_identity(root)
        for excluded in self.excluded_roots:
            if root == excluded or root.is_relative_to(excluded):
                raise WorkspacePathError("Application storage cannot be registered as repository source.")
            try:
                excluded_identity = repository_identity(excluded)
            except FileNotFoundError:
                continue
            if identity == excluded_identity:
                raise WorkspacePathError("Application storage cannot be registered as repository source.")
        if root == Path(root.anchor):
            raise WorkspacePathError("A filesystem root cannot be registered as repository source.")
        return root, identity

    def source_root(self, corp_id: str, project_id: str) -> Path:
        record = self.store.project(corp_id, project_id)
        root, identity = self._approved_root(record["root"])
        if identity != record["identity"]:
            raise CodingConflict("The registered repository root was replaced. Register its new identity explicitly.")
        return root

    async def register(
        self, corp_id: str, root: str | Path, name: str, checks: dict[str, str] | None = None,
    ) -> dict:
        name = name.strip()
        checks = dict(checks or {})
        if not name or len(name) > 120:
            raise ValueError("A repository name of at most 120 characters is required.")
        if len(checks) > 10 or any(
            not label.strip() or len(label) > 80 or not command.strip()
            or len(command) > 4096 or "\0" in command for label, command in checks.items()
        ):
            raise ValueError("Approve at most ten named, bounded check commands.")
        source, identity = self._approved_root(root)
        # The atomic ownership claim precedes reading any source or Git bytes.
        proposed = {"id": identifier(), "name": name, "root": str(source),
                    "identity": identity, "checks": checks, "created": now(),
                    "onboarding": {"status": "pending"}}
        record = self.store.register_project(corp_id, proposed)
        if record["identity"] != identity:
            raise CodingConflict("The registered repository root was replaced.")
        if record["id"] != proposed["id"] and record["onboarding"]["status"] == "ready":
            return record
        try:
            git = await self._git_metadata(source, identity, record["id"])
            exclusions: dict[str, str] = {}
            snapshot = source_snapshot(
                source, excluded_roots=self.excluded_roots,
                max_files=self.settings.max_repository_files,
                max_bytes=self.settings.max_repository_mb * 1024 * 1024,
                tracked_paths=tuple(git["tracked_paths"]), exclusions=exclusions,
            )
            if repository_identity(source) != identity:
                raise CodingConflict("Repository identity changed during onboarding.")
            files = {path: {key: entry[key] for key in ("sha256", "size", "mode")}
                     for path, entry in snapshot.items()}
            record.update(onboarding={
                "status": "ready", "files": len(files), "bytes": sum(item["size"] for item in files.values()),
                "revision": source_revision(files), "exclusions": exclusions, "git": git,
                "policy": "approved source; credentials, application state, links and generated files excluded",
            })
        except Exception:
            record["onboarding"] = {"status": "failed", "error": "Repository onboarding failed; inspect source policy and limits."}
            self.store.save_project(corp_id, record)
            raise
        self.store.save_project(corp_id, record)
        return record

    def create_session(self, corp_id: str, project_id: str) -> dict:
        with self._lock:
            project = self.store.project(corp_id, project_id)
            if project["onboarding"]["status"] != "ready":
                raise CodingConflict("Complete repository onboarding before creating a session.")
            root = self.source_root(corp_id, project_id)
            snapshot = source_snapshot(
                root, excluded_roots=self.excluded_roots,
                max_files=self.settings.max_repository_files,
                max_bytes=self.settings.max_repository_mb * 1024 * 1024,
                tracked_paths=tuple(project["onboarding"]["git"]["tracked_paths"]),
            )
            if repository_identity(root) != project["identity"]:
                raise CodingConflict("Repository identity changed while creating the session.")
            session_id = identifier()
            directory = self.settings.coding_root / corp_storage_key(corp_id) / session_id
            repo = directory / "repo"
            with workspace_directory(self.settings.coding_root, repo, create=True):
                pass
            try:
                for path, entry in snapshot.items():
                    with source_file(repo, path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                     create_parents=True) as descriptor:
                        with os.fdopen(os.dup(descriptor), "wb") as writer:
                            writer.write(entry["content"])
                            writer.flush()
                        os.fchmod(descriptor, entry["mode"] & 0o777)
                        os.fsync(descriptor)
                files = {path: {key: entry[key] for key in ("sha256", "size", "mode")}
                         for path, entry in snapshot.items()}
                record = {"id": session_id, "project_id": project_id, "created": now(),
                          "repo": str(repo), "opening_manifest": files,
                          "tracked_paths": sorted(files),
                          "revision": source_revision(files), "identity": repository_identity(directory)}
                self.store.add_session(corp_id, record)
            except BaseException:
                remove_workspace_tree(self.settings.coding_root, directory)
                raise
            return record

    def repository(self, corp_id: str, session_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(session_id):
            raise ValueError("Invalid coding session identifier.")
        record = self.store.session(corp_id, session_id)
        expected = self.settings.coding_root / corp_storage_key(corp_id) / session_id / "repo"
        if Path(record["repo"]) != expected or repository_identity(expected.parent) != record["identity"]:
            raise CodingConflict("The isolated repository copy was replaced.")
        # Runtime reconciliation atomically replaces repo, while its owning
        # session directory and corporation remain fixed.
        repository_identity(expected)
        return expected

    async def _git_metadata(self, root: Path, identity: dict[str, int], owner: str) -> dict:
        result = {"available": False, "revision": None, "tracked_paths": [], "changes": [], "reason": None}
        git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        if git is None:
            result["reason"] = "Git is unavailable; source snapshots remain usable."
            return result
        metadata = root / ".git"
        try:
            self._validate_git_metadata(root, metadata)
        except (OSError, ValueError):
            result["reason"] = "Git metadata must be a bounded directory without symlinks; source snapshots remain usable."
            return result
        env = {
            "PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat", "GIT_EXTERNAL_DIFF": "/bin/false",
        }
        supervisor = ProcessSupervisor()
        with workspace_directory(root, root) as descriptor:
            prefix = (
                git, "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null", "-c", "core.excludesFile=/dev/null",
                "-c", "core.attributesFile=/dev/null", "-c", "submodule.recurse=false",
                "-c", "protocol.allow=never", "--git-dir=.git", "--work-tree=.",
            )
            async def run(*arguments: str):
                value = await supervisor.run_bytes(
                    (sys.executable, "-I", "-c", _PINNED_GIT, str(descriptor), *prefix, *arguments),
                    owner_id=owner, cwd=Path("/"),
                    env=env, timeout=5, max_output_bytes=1024 * 1024,
                    pass_fds=(descriptor,),
                )
                if value.timed_out or value.truncated or value.exit_code != 0:
                    raise CodingConflict("Git metadata exceeded its bounds or could not be inspected.")
                return value.stdout

            try:
                tracked = await run("ls-files", "--cached", "-z")
                status = await run("status", "--porcelain=v1", "-z", "--untracked-files=normal", "--ignore-submodules=all")
                try:
                    revision = (await run("rev-parse", "--verify", "HEAD")).decode("ascii").strip()
                except CodingConflict:
                    revision = ""
            except (OSError, ValueError):
                result["reason"] = "Git inspection failed; source snapshots remain usable."
                return result
        if repository_identity(root) != identity:
            raise CodingConflict("Repository identity changed during Git inspection.")
        result.update(available=True, revision=revision if _GIT_REVISION.fullmatch(revision) else None,
                      tracked_paths=sorted({path for raw in tracked.split(b"\0")
                                            if (path := raw.decode("utf-8", "replace")) and allowed_source(path)}))
        fields = iter(status.split(b"\0"))
        for raw in fields:
            if len(raw) < 4:
                continue
            state, path = raw[:2].decode("ascii", "replace"), raw[3:].decode("utf-8", "replace")
            if "R" in state or "C" in state:
                next(fields, b"")
            if allowed_source(path):
                result["changes"].append({"path": path, "status": state})
        return result

    @staticmethod
    def _validate_git_metadata(root: Path, directory: Path) -> None:
        deadline = time.monotonic() + 5
        visited = 0
        def walk(path: Path) -> None:
            nonlocal visited
            with workspace_directory(root, path) as descriptor:
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > 100_000 or time.monotonic() >= deadline:
                            raise CodingConflict("Git metadata exceeds its inventory bound.")
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            walk(path / entry.name)
                        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                            raise CodingConflict("Git metadata cannot contain links or special files.")
        walk(directory)
