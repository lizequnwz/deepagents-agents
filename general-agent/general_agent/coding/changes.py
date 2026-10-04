"""Scoped immutable source versions and conflict-safe, journaled application."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from general_agent.coding.source import source_file, source_revision, source_snapshot, validate_source_path
from general_agent.coding.store import CodingConflict, identifier, now
from general_agent.config import Settings
from general_agent.workspace import (
    corp_storage_key, remove_workspace_tree, workspace_directory, workspace_file,
)

_IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write(descriptor: int, data: bytes) -> None:
    with os.fdopen(os.dup(descriptor), "wb") as writer:
        writer.write(data)
        writer.flush()
    os.fsync(descriptor)


def _file_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old != new:
            changes.append({"path": path, "kind": "created" if old is None else
                            "deleted" if new is None else "modified", "before": old, "after": new})
    return changes


class ChangeManager:
    """Keep review bytes independent of mutable workcopies and Git metadata.

    Application-owned writers are serialized. All selected files are checked
    before any write, then checked again through no-follow parent descriptors.
    A non-cooperating external editor can still race the last check and rename;
    postflight detects observed drift and compensation never overwrites it.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.coding_root
        self._lock = threading.RLock()
        with workspace_directory(settings.project_root, self.root, create=True):
            pass

    def _session(self, corp_id: str, session_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(session_id):
            raise ValueError("Invalid coding session identifier.")
        path = self.root / corp_storage_key(corp_id) / session_id
        with workspace_directory(self.root, path, create=True):
            pass
        return path

    def _record_path(self, corp_id: str, session_id: str, kind: str, record_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(record_id):
            raise ValueError("Invalid coding record identifier.")
        return self._session(corp_id, session_id) / kind / f"{record_id}.json"

    def _json(self, path: Path) -> dict[str, Any]:
        with workspace_file(self.root, path, os.O_RDONLY) as descriptor:
            with os.fdopen(os.dup(descriptor), "rb") as reader:
                return json.load(reader)

    def _save_json(self, path: Path, record: dict[str, Any], *, immutable: bool = False) -> None:
        temporary = path if immutable else path.with_name(f"{identifier()}.pending")
        with workspace_file(self.root, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            create_parents=True) as descriptor:
            os.fchmod(descriptor, 0o400 if immutable else 0o600)
            _write(descriptor, _canonical(record))
        with workspace_directory(self.root, path.parent) as parent:
            if not immutable:
                os.replace(temporary.name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)

    def _blob_path(self, corp_id: str, session_id: str, sha256: str) -> Path:
        if not _HASH.fullmatch(sha256):
            raise ValueError("Invalid source blob identifier.")
        return self._session(corp_id, session_id) / "blobs" / sha256

    def blob(self, corp_id: str, session_id: str, sha256: str) -> bytes:
        """Read an immutable version only within its owning corporation/session."""

        with workspace_file(self.root, self._blob_path(corp_id, session_id, sha256),
                            os.O_RDONLY) as descriptor:
            with os.fdopen(os.dup(descriptor), "rb") as reader:
                data = reader.read(self.settings.max_repository_mb * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise CodingConflict("An immutable source version failed its integrity check.")
        return data

    def capture(self, corp_id: str, session_id: str, root: Path,
                *, tracked_paths: tuple[str, ...] = (),
                excluded_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
        """Persist every allowed source version and return a JSON-safe manifest."""

        with self._lock:
            inventory = source_snapshot(
                root, max_files=self.settings.max_repository_files,
                max_bytes=self.settings.max_repository_mb * 1024 * 1024,
                tracked_paths=tracked_paths,
                excluded_roots=tuple(path for path in (
                    self.settings.workspace_root, self.settings.data_root,
                    self.settings.project_root / ".venv", *excluded_roots,
                ) if path.is_relative_to(root)),
            )
            session = self._session(corp_id, session_id)
            with workspace_directory(self.root, session / "blobs", create=True) as parent:
                existing = {}
                for name in os.listdir(parent):
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if not _HASH.fullmatch(name) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise CodingConflict("Immutable coding storage contains an invalid version.")
                    existing[name] = info.st_size
            additions = {entry["sha256"]: len(entry["content"]) for entry in inventory.values()
                         if entry["sha256"] not in existing}
            # Reserve storage before writing. History is never silently evicted.
            if sum(existing.values()) + sum(additions.values()) > self.settings.coding_storage_mb * 1024 * 1024:
                raise ValueError("Immutable coding history exceeds the session storage limit.")
            files = {}
            for path, entry in inventory.items():
                data = entry["content"]
                sha256 = entry["sha256"]
                blob_path = self._blob_path(corp_id, session_id, sha256)
                try:
                    with workspace_file(self.root, blob_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                        create_parents=True) as descriptor:
                        os.fchmod(descriptor, 0o400)
                        _write(descriptor, data)
                except FileExistsError:
                    if self.blob(corp_id, session_id, sha256) != data:
                        raise CodingConflict("An immutable source version was changed.")
                files[path] = {key: entry[key] for key in ("sha256", "size", "mode")}
            return {"revision": source_revision(files), "files": files}

    def _validate_snapshot(self, corp_id: str, session_id: str, snapshot: dict[str, Any]) -> None:
        if source_revision(snapshot["files"]) != snapshot["revision"]:
            raise CodingConflict("Source manifest integrity check failed.")
        for path, entry in snapshot["files"].items():
            validate_source_path(path)
            data = self.blob(corp_id, session_id, entry["sha256"])
            if len(data) != entry["size"]:
                raise CodingConflict("Source version size does not match its manifest.")

    def finalize(
        self, corp_id: str, session_id: str, before_snapshot: dict[str, Any],
        root: Path, attempt_id: str, *, tracked_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Freeze a cumulative proposal against the session's accepted baseline."""

        with self._lock:
            self._validate_snapshot(corp_id, session_id, before_snapshot)
            after = self.capture(corp_id, session_id, root,
                                 tracked_paths=tuple(set(before_snapshot["files"]) | set(tracked_paths)))
            files = _file_changes(before_snapshot["files"], after["files"])
            revision = hashlib.sha256(_canonical({"before": before_snapshot, "after": after})).hexdigest()
            change = {"id": identifier(), "attempt_id": attempt_id, "created": now(),
                      "revision": revision, "before_revision": before_snapshot["revision"],
                      "after_revision": after["revision"], "before": before_snapshot,
                      "after": after, "files": files}
            self._save_json(self._record_path(corp_id, session_id, "changes", change["id"]),
                            change, immutable=True)
            return change

    def get(self, corp_id: str, session_id: str, change_id: str) -> dict[str, Any]:
        change = self._json(self._record_path(corp_id, session_id, "changes", change_id))
        before, after = change["before"], change["after"]
        revision = hashlib.sha256(_canonical({"before": before, "after": after})).hexdigest()
        if (change["id"] != change_id or revision != change["revision"]
                or source_revision(before["files"]) != before["revision"]
                or source_revision(after["files"]) != after["revision"]
                or before["revision"] != change["before_revision"]
                or after["revision"] != change["after_revision"]
                or change["files"] != _file_changes(before["files"], after["files"])):
            raise CodingConflict("Immutable change metadata failed its integrity check.")
        return change

    def diff(self, corp_id: str, session_id: str, change_id: str,
             *, max_chars: int = 200_000) -> dict[str, Any]:
        change = self.get(corp_id, session_id, change_id)
        pieces, files, remaining, truncated = [], [], max_chars, False
        for entry in change["files"]:
            old, new = entry["before"], entry["after"]
            old_data = self.blob(corp_id, session_id, old["sha256"]) if old else b""
            new_data = self.blob(corp_id, session_id, new["sha256"]) if new else b""
            binary = b"\0" in old_data or b"\0" in new_data
            try:
                old_text, new_text = old_data.decode("utf-8"), new_data.decode("utf-8")
            except UnicodeDecodeError:
                binary = True
            path = entry["path"]
            if binary:
                text = f"Binary source changed: {path}\n"
            else:
                lines = difflib.unified_diff(
                    old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                    fromfile=f"a/{path}" if old else "/dev/null",
                    tofile=f"b/{path}" if new else "/dev/null",
                )
                text = "".join(line if line.endswith("\n") else
                               line + "\n\\ No newline at end of file\n" for line in lines)
            if old and new and old["mode"] != new["mode"]:
                text = f"Mode {old['mode']:04o} -> {new['mode']:04o}: {path}\n" + text
            if len(text) > remaining:
                truncated = True
            pieces.append(text[:remaining])
            remaining = max(0, remaining - len(text))
            files.append({**entry, "binary": binary})
        return {"change_id": change_id, "revision": change["revision"],
                "text": "".join(pieces), "truncated": truncated, "files": files}

    @staticmethod
    def _root_identity(root: Path) -> dict[str, int]:
        with workspace_directory(root, root) as descriptor:
            info = os.fstat(descriptor)
            return {"device": info.st_dev, "inode": info.st_ino}

    @contextmanager
    def _parent(self, root: Path, path: str, identity: dict[str, int], *,
                create: bool = False, nearest: bool = False) -> Iterator[tuple[int, bool]]:
        parts = validate_source_path(path).parts
        target = root.joinpath(*parts)
        if any(target == excluded or target.is_relative_to(excluded) for excluded in (
            self.settings.workspace_root, self.settings.data_root,
            self.settings.project_root / ".venv",
        )):
            raise CodingConflict("Application storage cannot be an original source apply target.")
        with workspace_directory(root, root) as root_descriptor:
            info = os.fstat(root_descriptor)
            if {"device": info.st_dev, "inode": info.st_ino} != identity:
                raise CodingConflict("The registered original repository root was replaced.")
            descriptor = os.dup(root_descriptor)
            complete = True
            try:
                for part in parts[:-1]:
                    if create:
                        try:
                            os.mkdir(part, dir_fd=descriptor)
                        except FileExistsError:
                            pass
                    try:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                        dir_fd=descriptor)
                    except FileNotFoundError:
                        if not nearest:
                            raise
                        complete = False
                        break
                    os.close(descriptor)
                    descriptor = child
                yield descriptor, complete
            finally:
                os.close(descriptor)

    @staticmethod
    def _at(parent: int, name: str) -> tuple[dict[str, Any] | None, tuple[int, int] | None]:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return None, None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CodingConflict("Apply targets must be regular files without aliases.")
            with os.fdopen(os.dup(descriptor), "rb") as reader:
                digest = hashlib.file_digest(reader, "sha256").hexdigest()
            return ({"sha256": digest, "size": info.st_size, "mode": stat.S_IMODE(info.st_mode)},
                    (info.st_dev, info.st_ino))
        finally:
            os.close(descriptor)

    def _replace(self, root: Path, path: str, expected: dict[str, Any] | None,
                 desired: dict[str, Any] | None, data: bytes | None,
                 *, root_identity: dict[str, int], operation_id: str) -> None:
        """Mutate one checked path through its pinned, no-follow parent."""

        validate_source_path(path)
        target = root / path
        with self._parent(root, path, root_identity, create=desired is not None) as (parent, _):
            current, inode = self._at(parent, target.name)
            if current != expected:
                raise CodingConflict(f"Source changed before applying {path}.")
            temporary = self._temporary_name(operation_id, path)
            temporary_inode = None
            try:
                if desired is not None:
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=parent)
                    try:
                        info = os.fstat(descriptor)
                        temporary_inode = (info.st_dev, info.st_ino)
                        _write(descriptor, data or b"")
                        os.fchmod(descriptor, desired["mode"])
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                rechecked, actual_inode = self._at(parent, target.name)
                if rechecked != expected or actual_inode != inode:
                    raise CodingConflict(f"Source changed during application of {path}.")
                if desired is None:
                    if expected is not None:
                        os.unlink(target.name, dir_fd=parent)
                else:
                    os.replace(temporary, target.name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                if temporary_inode is not None:
                    try:
                        info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                        if (info.st_dev, info.st_ino) == temporary_inode:
                            os.unlink(temporary, dir_fd=parent)
                    except FileNotFoundError:
                        pass

    def _execute_journal(self, corp_id: str, session_id: str, journal: dict[str, Any],
                         root: Path, *, reverse: bool) -> dict[str, Any]:
        path = self._record_path(corp_id, session_id, "journals", journal["id"])
        entries = journal["files"]
        expected_key, desired_key = ("after", "before") if reverse else ("before", "after")
        # Load and integrity-check every desired version before the first write.
        staged = {entry["path"]: self.blob(corp_id, session_id, entry[desired_key]["sha256"])
                  if entry[desired_key] else None for entry in entries}
        journal.update(status="reverting" if reverse else "applying", error=None)
        self._save_json(path, journal)
        try:
            for entry in entries:
                self._replace(root, entry["path"], entry[expected_key], entry[desired_key],
                              staged[entry["path"]], root_identity=journal["source_root_identity"],
                              operation_id=journal["id"])
            if self._root_identity(root) != journal["source_root_identity"]:
                raise CodingConflict("The original repository root changed during application.")
            final = self.capture(corp_id, session_id, root,
                                 tracked_paths=tuple(entry["path"] for entry in entries))
            if self._root_identity(root) != journal["source_root_identity"]:
                raise CodingConflict("The original repository root changed during verification.")
            for entry in entries:
                if final["files"].get(entry["path"]) != entry[desired_key]:
                    raise CodingConflict(f"Source changed after applying {entry['path']}.")
            journal.update(status="reverted" if reverse else "applied", ended=now(),
                           **{"reverted_manifest" if reverse else "applied_manifest": final})
            self._save_json(path, journal)
            return journal
        except Exception as exc:
            journal["error"] = str(exc)
            self._compensate(corp_id, session_id, journal, root, reverse=reverse)
            raise

    def _compensate(self, corp_id: str, session_id: str, journal: dict[str, Any],
                    root: Path, *, reverse: bool) -> dict[str, Any]:
        original_key, changed_key = ("after", "before") if reverse else ("before", "after")
        conflicts = self._cleanup_stages(journal, root)
        for entry in reversed(journal["files"]):
            target = root / entry["path"]
            try:
                try:
                    with self._parent(root, entry["path"], journal["source_root_identity"]) as (parent, _):
                        current, _ = self._at(parent, target.name)
                except FileNotFoundError:
                    current = None
                if current == entry[original_key]:
                    continue
                if current != entry[changed_key]:
                    raise CodingConflict("A later external edit prevents compensation.")
                original = entry[original_key]
                data = self.blob(corp_id, session_id, original["sha256"]) if original else None
                self._replace(root, entry["path"], current, original, data,
                              root_identity=journal["source_root_identity"],
                              operation_id=journal["id"] + "-restore")
            except (OSError, ValueError) as exc:
                conflicts.append({"path": entry["path"], "reason": str(exc)})
        journal.update(status="conflicted" if conflicts else "applied" if reverse else "rolled_back",
                       conflicts=conflicts, ended=now())
        self._save_json(self._record_path(corp_id, session_id, "journals", journal["id"]), journal)
        return journal

    @staticmethod
    def _temporary_name(operation_id: str, path: str) -> str:
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
        return f".coding-{operation_id}-{digest}.tmp"

    def _cleanup_stages(self, journal: dict[str, Any], root: Path) -> list[dict[str, str]]:
        """Reclaim only intact journal-owned staging versions after a crash."""

        conflicts = []
        for entry in journal["files"]:
            for operation_id in (journal["id"], journal["id"] + "-restore"):
                try:
                    with self._parent(root, entry["path"], journal["source_root_identity"],
                                      nearest=True) as (parent, complete):
                        if not complete:
                            continue
                        name = self._temporary_name(operation_id, entry["path"])
                        staged, inode = self._at(parent, name)
                        if staged is None:
                            continue
                        intact = any(version and staged["sha256"] == version["sha256"]
                                     and staged["size"] == version["size"]
                                     for version in (entry["before"], entry["after"]))
                        actual, actual_inode = self._at(parent, name)
                        if not intact or actual != staged or actual_inode != inode:
                            raise CodingConflict("A partial or changed staging file requires explicit recovery.")
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                except (OSError, ValueError) as exc:
                    conflicts.append({"path": entry["path"], "reason": str(exc)})
        return conflicts

    def apply(self, corp_id: str, session_id: str, change_id: str, source_root: Path,
              working_root: Path, expected_revision: str, paths: list[str] | None = None,
              *, expected_root_identity: dict[str, int]) -> dict[str, Any]:
        with self._lock:
            identity = dict(expected_root_identity)
            self.recover(corp_id, session_id, source_root, expected_root_identity=identity)
            change = self.get(corp_id, session_id, change_id)
            if change["revision"] != expected_revision:
                raise CodingConflict("The reviewed change revision no longer matches.")
            working = self.capture(corp_id, session_id, working_root,
                                   tracked_paths=tuple(change["after"]["files"]))
            if working["revision"] != change["after_revision"]:
                raise CodingConflict("The working copy changed after this proposal was reviewed.")
            available = {entry["path"]: entry for entry in change["files"]}
            selected = sorted(available if paths is None else paths)
            if not selected or len(selected) != len(set(selected)) or any(path not in available for path in selected):
                raise ValueError("Select distinct paths from this change set.")
            entries = [available[path] for path in selected]
            self._preflight(source_root, entries, identity, expected_key="before")
            journal = {"id": identifier(), "change_id": change_id, "created": now(),
                       "source_root": str(source_root), "selected_paths": selected,
                       "source_root_identity": identity,
                       "files": entries, "status": "prepared", "error": None}
            self._save_json(self._record_path(corp_id, session_id, "journals", journal["id"]),
                            journal, immutable=True)
            return self._execute_journal(corp_id, session_id, journal, source_root, reverse=False)

    def journal(self, corp_id: str, session_id: str, journal_id: str) -> dict[str, Any]:
        return self._json(self._record_path(corp_id, session_id, "journals", journal_id))

    def revert(self, corp_id: str, session_id: str, journal_id: str,
               source_root: Path, *, expected_root_identity: dict[str, int]) -> dict[str, Any]:
        with self._lock:
            identity = dict(expected_root_identity)
            self.recover(corp_id, session_id, source_root, expected_root_identity=identity)
            journal = self.journal(corp_id, session_id, journal_id)
            if (journal["status"] != "applied" or journal["source_root"] != str(source_root)
                    or journal["source_root_identity"] != identity):
                raise CodingConflict("Only an applied operation on this repository can be reverted.")
            self._preflight(source_root, journal["files"], journal["source_root_identity"],
                            expected_key="after")
            return self._execute_journal(corp_id, session_id, journal, source_root, reverse=True)

    def _preflight(self, root: Path, entries: list[dict[str, Any]],
                   identity: dict[str, int], *, expected_key: str) -> None:
        for entry in entries:
            validate_source_path(entry["path"])
            target = root / entry["path"]
            with self._parent(root, entry["path"], identity, nearest=True) as (parent, complete):
                current, _ = self._at(parent, target.name) if complete else (None, None)
                if not os.access(".", os.W_OK | os.X_OK, dir_fd=parent):
                    raise CodingConflict(f"The source parent is not writable at {entry['path']}.")
            if current != entry[expected_key]:
                raise CodingConflict(f"The original source conflicts at {entry['path']}.")

    def recover(self, corp_id: str, session_id: str, source_root: Path,
                *, expected_root_identity: dict[str, int]) -> list[dict[str, Any]]:
        """Compensate interrupted operations; retain conflicts for explicit recovery."""

        recovered = []
        with self._lock:
            identity = dict(expected_root_identity)
            if self._root_identity(source_root) != identity:
                raise CodingConflict("The registered original repository root was replaced before admission.")
            root = self._session(corp_id, session_id) / "journals"
            with workspace_directory(self.root, root, create=True) as parent:
                names = os.listdir(parent)
            for name in sorted(names):
                if not name.endswith(".json"):
                    continue
                journal = self.journal(corp_id, session_id, name[:-5])
                if (journal["source_root"] != str(source_root)
                        or journal["source_root_identity"] != identity):
                    raise CodingConflict("Apply recovery belongs to a different repository.")
                if journal["status"] in {"applying", "reverting", "prepared"}:
                    if self._root_identity(source_root) != journal["source_root_identity"]:
                        raise CodingConflict("Apply recovery cannot use a replaced repository root.")
                    recovered.append(self._compensate(
                        corp_id, session_id, journal, source_root,
                        reverse=journal["status"] == "reverting",
                    ))
                elif journal["status"] == "conflicted":
                    raise CodingConflict("An interrupted apply has unresolved recovery conflicts.")
            if any(journal["status"] == "conflicted" for journal in recovered):
                raise CodingConflict("An interrupted apply has unresolved recovery conflicts.")
        return recovered

    def journals(self, corp_id: str, session_id: str) -> list[dict[str, Any]]:
        """Read durable terminal operations for accepted-baseline reconciliation."""

        root = self._session(corp_id, session_id) / "journals"
        with workspace_directory(self.root, root, create=True) as parent:
            names = os.listdir(parent)
        records = [self.journal(corp_id, session_id, name[:-5]) for name in names
                   if name.endswith(".json")]
        return sorted(records, key=lambda record: record["created"])

    def discard_journals(self, corp_id: str, session_id: str) -> list[dict[str, Any]]:
        directory = self._session(corp_id, session_id) / "discards"
        with workspace_directory(self.root, directory, create=True) as parent:
            names = os.listdir(parent)
        records = [self._json(self._record_path(corp_id, session_id, "discards", name[:-5]))
                   for name in names if name.endswith(".json")]
        return sorted(records, key=lambda record: record["created"])

    def _recover_discard(self, corp_id: str, session_id: str, record: dict[str, Any]) -> None:
        if (record["stage"] != f"discard-{record['id']}.staged"
                or record["backup"] != f"discard-{record['id']}.previous"):
            raise CodingConflict("Discard recovery contains invalid isolated directory names.")
        directory = self._session(corp_id, session_id)
        path = self._record_path(corp_id, session_id, "discards", record["id"])
        backup, staged = directory / record["backup"], directory / record["stage"]
        with workspace_directory(self.root, directory) as parent:
            def identity(name: str) -> dict[str, int] | None:
                try:
                    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                except FileNotFoundError:
                    return None
                try:
                    info = os.fstat(descriptor)
                    return {"device": info.st_dev, "inode": info.st_ino}
                finally:
                    os.close(descriptor)

            current, previous, proposed = identity("repo"), identity(record["backup"]), identity(record["stage"])
            if current == record["stage_identity"] and proposed is None:
                # The directory swap committed, possibly before its status save.
                if previous not in (None, record["repo_identity"]):
                    raise CodingConflict("Discard recovery found a changed backup directory.")
                status = "discarded"
            elif current == record["repo_identity"] and previous is None:
                status = "rolled_back"
            elif current is None and previous == record["repo_identity"]:
                os.rename(record["backup"], "repo", src_dir_fd=parent, dst_dir_fd=parent)
                status = "rolled_back"
            else:
                raise CodingConflict("Discard recovery found a replaced working directory.")
            if proposed not in (None, record["stage_identity"]):
                raise CodingConflict("Discard recovery found a replaced staging directory.")
            os.fsync(parent)
        if status == "discarded" and previous is not None:
            remove_workspace_tree(self.root, backup)
        if proposed is not None:
            remove_workspace_tree(self.root, staged)
        record.update(status=status, ended=now())
        self._save_json(path, record)

    def recover_discards(self, corp_id: str, session_id: str) -> list[dict[str, Any]]:
        """Recover isolated-copy swaps without opening any registered original."""

        with self._lock:
            for record in self.discard_journals(corp_id, session_id):
                if record["status"] == "prepared":
                    self._recover_discard(corp_id, session_id, record)
            return self.discard_journals(corp_id, session_id)

    def discard(self, corp_id: str, session_id: str, change_id: str, working_root: Path,
                expected_revision: str) -> dict[str, Any]:
        """Restore a rejected proposal only inside its owning isolated copy."""

        with self._lock:
            directory = self._session(corp_id, session_id)
            if working_root != directory / "repo":
                raise CodingConflict("Discard can only target this session's isolated working copy.")
            self.recover_discards(corp_id, session_id)
            change = self.get(corp_id, session_id, change_id)
            if change["revision"] != expected_revision:
                raise CodingConflict("The reviewed change revision no longer matches.")
            after = self.capture(corp_id, session_id, working_root,
                                 tracked_paths=tuple(change["after"]["files"]))
            if after["revision"] != change["after_revision"]:
                raise CodingConflict("The working copy changed after this proposal was reviewed.")
            before = change["before"]
            self._validate_snapshot(corp_id, session_id, before)
            if sum(entry["size"] for entry in before["files"].values()) > self.settings.coding_storage_mb * 1024 * 1024:
                raise ValueError("Discard staging exceeds the isolated source storage limit.")
            operation_id = identifier()
            staged = directory / f"discard-{operation_id}.staged"
            backup = directory / f"discard-{operation_id}.previous"
            with workspace_directory(self.root, staged, create=True):
                pass
            record = None
            try:
                for relative, entry in before["files"].items():
                    data = self.blob(corp_id, session_id, entry["sha256"])
                    with source_file(staged, relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                     create_parents=True) as descriptor:
                        _write(descriptor, data)
                        os.fchmod(descriptor, entry["mode"])
                        os.fsync(descriptor)
                staged_snapshot = self.capture(corp_id, session_id, staged,
                                               tracked_paths=tuple(before["files"]))
                if staged_snapshot["revision"] != before["revision"]:
                    raise CodingConflict("Discard staging does not match the frozen source baseline.")
                root_identity = self._root_identity(working_root)
                record = {"id": operation_id, "created": now(), "change_id": change_id,
                          "stage": staged.name, "backup": backup.name, "status": "prepared",
                          "repo_identity": root_identity, "stage_identity": self._root_identity(staged),
                          "before_revision": before["revision"], "after_revision": after["revision"]}
                self._save_json(self._record_path(corp_id, session_id, "discards", operation_id),
                                record, immutable=True)
                # Root freezes application writers; this catches drift during staging.
                rechecked = self.capture(corp_id, session_id, working_root,
                                         tracked_paths=tuple(change["after"]["files"]))
                if rechecked["revision"] != after["revision"]:
                    raise CodingConflict("The working copy changed while discard was staged.")
                with workspace_directory(self.root, directory) as parent:
                    current = os.stat("repo", dir_fd=parent, follow_symlinks=False)
                    if {"device": current.st_dev, "inode": current.st_ino} != root_identity:
                        raise CodingConflict("The isolated working root changed during discard.")
                    os.rename("repo", backup.name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                    os.rename(staged.name, "repo", src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                self._recover_discard(corp_id, session_id, record)
                return {"revision": before["revision"], "files": before["files"]}
            except Exception:
                if record is not None:
                    self._recover_discard(corp_id, session_id, record)
                else:
                    remove_workspace_tree(self.root, staged)
                raise
