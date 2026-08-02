"""Per-user workspace isolation, migration, uploads, and immutable snapshots."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Literal

from general_agent.schemas import Artifact, Attachment, WorkspaceEntry, utc_now

WorkspaceScope = Literal["chat", "shared"]

_CURRENT_CORP_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "general_agent_corp_id", default=None
)
_CURRENT_CONVERSATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "general_agent_conversation_id", default=None
)
_PROTECTED_PARTS = {
    ".app",
    ".packages",
    ".tmp",
    "__pycache__",
    ".pytest_cache",
    "large_tool_results",
}
_LAYOUT_NAMES = {"chats", "shared"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._() -]+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_LAYOUT_VERSION = 3


class WorkspacePathError(ValueError):
    """Raised when a client path escapes or targets protected storage."""


@dataclass(frozen=True, slots=True)
class FileStamp:
    size: int
    sha256: str


def validate_corp_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not _SAFE_ID.fullmatch(candidate):
        raise WorkspacePathError(
            "The corp ID must be 1-128 letters, numbers, underscores, or hyphens."
        )
    return candidate


def corp_storage_key(corp_id: str) -> str:
    """Return a stable opaque directory key without exposing the corp ID."""

    normalized = validate_corp_id(corp_id)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def set_current_workspace(
    corp_id: str, conversation_id: str
) -> tuple[contextvars.Token[str | None], contextvars.Token[str | None]]:
    corp_token = _CURRENT_CORP_ID.set(validate_corp_id(corp_id))
    conversation_token = _CURRENT_CONVERSATION_ID.set(
        _safe_conversation_id(conversation_id)
    )
    return corp_token, conversation_token


def reset_current_workspace(
    tokens: tuple[contextvars.Token[str | None], contextvars.Token[str | None]],
) -> None:
    corp_token, conversation_token = tokens
    _CURRENT_CONVERSATION_ID.reset(conversation_token)
    _CURRENT_CORP_ID.reset(corp_token)


def set_current_conversation(conversation_id: str) -> contextvars.Token[str | None]:
    """Compatibility helper for tests that set only the current chat."""

    return _CURRENT_CONVERSATION_ID.set(_safe_conversation_id(conversation_id))


def reset_current_conversation(token: contextvars.Token[str | None]) -> None:
    _CURRENT_CONVERSATION_ID.reset(token)


def current_conversation_id() -> str | None:
    return _CURRENT_CONVERSATION_ID.get()


def current_corp_id() -> str | None:
    return _CURRENT_CORP_ID.get()


def agent_physical_path(
    path: str,
    conversation_id: str | None = None,
    corp_id: str | None = None,
) -> str:
    """Translate an agent virtual path into a workspace-root-relative path."""

    raw = str(path or "").strip().replace("\\", "/")
    pure = PurePosixPath(raw.lstrip("/") or ".")
    if pure.is_absolute() or any(part in {"..", "~"} for part in pure.parts):
        raise WorkspacePathError("Absolute host paths and traversal are not allowed.")
    parts = tuple(part for part in pure.parts if part not in {"", "."})
    active_corp = corp_id or current_corp_id()
    active_conversation = conversation_id or current_conversation_id()

    if parts and parts[0] == "skills":
        if any(part.startswith(".") for part in parts[1:]):
            raise WorkspacePathError("Protected skill paths are not exposed.")
        return PurePosixPath(".app", *parts).as_posix()

    if any(part in _PROTECTED_PARTS or part.startswith(".") for part in parts):
        raise WorkspacePathError("Protected workspace paths are not exposed.")
    if not active_corp:
        return PurePosixPath(*parts).as_posix() if parts else ""

    user_prefix = PurePosixPath("users", corp_storage_key(active_corp))
    if parts and parts[0] in _LAYOUT_NAMES:
        return (user_prefix / PurePosixPath(*parts)).as_posix()
    if parts and parts[0] == "tmp":
        return (user_prefix / ".tmp" / PurePosixPath(*parts[1:])).as_posix()
    if not active_conversation:
        raise WorkspacePathError("A current conversation is required for this path.")
    return (
        user_prefix
        / "chats"
        / _safe_conversation_id(active_conversation)
        / PurePosixPath(*parts)
    ).as_posix()


def agent_virtual_path(
    relative_path: str,
    conversation_id: str | None = None,
    corp_id: str | None = None,
) -> str:
    """Convert a physical workspace-relative path to an agent-visible path."""

    normalized = PurePosixPath(str(relative_path).replace("\\", "/").lstrip("/"))
    parts = normalized.parts
    if len(parts) >= 2 and parts[:2] == (".app", "skills"):
        return "/" + PurePosixPath("skills", *parts[2:]).as_posix()
    active_corp = corp_id or current_corp_id()
    active_conversation = conversation_id or current_conversation_id()
    if not active_corp:
        return "/" + normalized.as_posix()
    prefix = ("users", corp_storage_key(active_corp))
    if parts[:2] != prefix:
        return "/" + normalized.as_posix()
    user_parts = parts[2:]
    if user_parts and user_parts[0] == ".tmp":
        return "/" + PurePosixPath("tmp", *user_parts[1:]).as_posix()
    if (
        active_conversation
        and len(user_parts) >= 2
        and user_parts[:2] == ("chats", active_conversation)
    ):
        remainder = user_parts[2:]
        return "/" + PurePosixPath(*remainder).as_posix() if remainder else "/"
    return "/" + PurePosixPath(*user_parts).as_posix()


def safe_filename(name: str) -> str:
    basename = Path(name.replace("\\", "/")).name.strip()
    basename = _SAFE_NAME.sub("_", basename).strip(". ")
    if not basename or basename in {".", ".."}:
        raise WorkspacePathError("The file name is empty or unsafe.")
    return basename[:240]


class Workspace:
    """Own per-user chat/shared files plus protected immutable snapshots."""

    def __init__(self, root: Path, data_root: Path, default_corp_id: str = "A123456") -> None:
        self.root = root.resolve()
        self.data_root = data_root.resolve()
        self.default_corp_id = validate_corp_id(default_corp_id)
        self.layout_marker = self.data_root / f"workspace-layout-v{_LAYOUT_VERSION}"
        self._metadata_lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.initialize_layout()

    def user_root(self, corp_id: str) -> Path:
        return self.root / "users" / corp_storage_key(corp_id)

    def user_data_root(self, corp_id: str) -> Path:
        return self.data_root / "users" / corp_storage_key(corp_id)

    def shared_root(self, corp_id: str) -> Path:
        return self.user_root(corp_id) / "shared"

    def chats_root(self, corp_id: str) -> Path:
        return self.user_root(corp_id) / "chats"

    def package_root(self, corp_id: str) -> Path:
        return self.user_root(corp_id) / ".packages"

    def temp_root(self, corp_id: str) -> Path:
        return self.user_root(corp_id) / ".tmp"

    def ensure_user(self, corp_id: str) -> Path:
        root = self.user_root(corp_id)
        for path in (
            root,
            root / "chats",
            root / "shared",
            root / ".packages",
            root / ".tmp",
            self.user_data_root(corp_id) / "attachments",
            self.user_data_root(corp_id) / "artifacts",
            self.user_data_root(corp_id) / "baselines",
        ):
            path.mkdir(parents=True, exist_ok=True)
        return root

    def initialize_layout(self) -> None:
        """Create the v3 tenant layout and migrate v2 data to the default user."""

        self.ensure_user(self.default_corp_id)
        memory = self.root / "MEMORY.md"
        memory.unlink(missing_ok=True)
        if self.layout_marker.exists():
            self.cleanup_temporary(self.default_corp_id)
            return

        target = self.user_root(self.default_corp_id)
        for name in ("chats", "shared"):
            source = self.root / name
            destination = target / name
            if source.is_dir() and not source.is_symlink():
                destination.mkdir(parents=True, exist_ok=True)
                for child in list(source.iterdir()):
                    shutil.move(str(child), str(_unique_path(destination / child.name)))
                source.rmdir()
        old_packages = self.root / ".packages"
        if old_packages.is_dir() and not old_packages.is_symlink():
            destination = target / ".packages"
            for child in list(old_packages.iterdir()):
                shutil.move(str(child), str(_unique_path(destination / child.name)))
            with contextlib.suppress(OSError):
                old_packages.rmdir()
        legacy = target / "shared" / "legacy"
        for child in list(self.root.iterdir()):
            if child.name in {"users", ".app", ".tmp", ".gitkeep"} or child.name.startswith("."):
                continue
            if child.is_symlink():
                continue
            destination = _unique_path(legacy / child.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(destination))
            self._upsert_metadata(
                self.default_corp_id,
                self.user_relative(self.default_corp_id, destination),
                origin="migration",
                retention="shared",
                original_name=child.name,
            )

        old_metadata = self.data_root / "workspace-metadata.json"
        if old_metadata.exists() and not self._metadata_path(self.default_corp_id).exists():
            destination = self._metadata_path(self.default_corp_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_metadata), str(destination))
        self.layout_marker.write_text(str(_LAYOUT_VERSION), encoding="utf-8")
        self.cleanup_temporary(self.default_corp_id)

    def chat_root(self, corp_id: str, conversation_id: str) -> Path:
        return self.chats_root(corp_id) / _safe_conversation_id(conversation_id)

    def ensure_chat(self, corp_id: str, conversation_id: str) -> Path:
        self.ensure_user(corp_id)
        root = self.chat_root(corp_id, conversation_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def resolve(
        self,
        relative_path: str,
        *,
        allow_root: bool = False,
        visible_only: bool = False,
        must_exist: bool = False,
    ) -> Path:
        """Resolve an internal physical workspace-relative path."""

        raw = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
        pure = PurePosixPath(raw or ".")
        if pure.is_absolute() or any(part in {"..", "~"} for part in pure.parts):
            raise WorkspacePathError("Absolute host paths and traversal are not allowed.")
        parts = tuple(part for part in pure.parts if part not in {"", "."})
        if not parts and not allow_root:
            raise WorkspacePathError("A file or directory path is required.")
        if visible_only and any(
            part in _PROTECTED_PARTS or part.startswith(".") for part in parts
        ):
            raise WorkspacePathError("Protected workspace paths are not exposed.")
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WorkspacePathError("The path escapes the workspace.")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(relative_path)
        if candidate.exists() and not candidate.resolve().is_relative_to(self.root):
            raise WorkspacePathError("Symlinks outside the workspace are not allowed.")
        return candidate

    def resolve_user(
        self,
        corp_id: str,
        relative_path: str,
        *,
        allow_root: bool = False,
        must_exist: bool = False,
    ) -> Path:
        """Resolve a public path inside one user's workspace."""

        base = self.ensure_user(corp_id).resolve()
        subpath = _safe_subpath(relative_path, allow_empty=allow_root)
        candidate = base.joinpath(*subpath.parts)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(base):
            raise WorkspacePathError("The path escapes the current user's workspace.")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(relative_path)
        if candidate.exists() and (
            candidate.is_symlink() or not candidate.resolve().is_relative_to(base)
        ):
            raise WorkspacePathError("Symlinks are not exposed through the workspace API.")
        return candidate

    def resolve_agent(self, path: str, *, must_exist: bool = False) -> Path:
        return self.resolve(agent_physical_path(path), must_exist=must_exist)

    def relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WorkspacePathError("The path is outside the workspace.")
        return resolved.relative_to(self.root).as_posix()

    def user_relative(self, corp_id: str, path: Path) -> str:
        resolved = path.resolve(strict=False)
        base = self.user_root(corp_id).resolve()
        if not resolved.is_relative_to(base):
            raise WorkspacePathError("The path is outside the current user's workspace.")
        return resolved.relative_to(base).as_posix()

    def list_entries(self, corp_id: str, relative_path: str = "") -> list[WorkspaceEntry]:
        directory = self.resolve_user(
            corp_id, relative_path, allow_root=True, must_exist=True
        )
        return self._entries(corp_id, directory)

    def list_scope(
        self,
        *,
        corp_id: str,
        scope: WorkspaceScope,
        conversation_id: str | None = None,
        relative_path: str = "",
    ) -> list[WorkspaceEntry]:
        base = self._scope_root(corp_id, scope, conversation_id)
        subpath = _safe_subpath(relative_path, allow_empty=True)
        directory = base.joinpath(*subpath.parts)
        if not directory.resolve(strict=False).is_relative_to(base.resolve()):
            raise WorkspacePathError("The path escapes the selected workspace scope.")
        if not directory.exists():
            raise FileNotFoundError(relative_path)
        return self._entries(corp_id, directory)

    def upload(
        self,
        *,
        corp_id: str,
        conversation_id: str,
        original_name: str,
        content_type: str | None,
        source: BinaryIO,
        max_bytes: int,
    ) -> tuple[Attachment, Path]:
        conversation_id = _safe_conversation_id(conversation_id)
        name = safe_filename(original_name)
        attachment_id = uuid.uuid4().hex
        destination = _unique_path(
            self.ensure_chat(corp_id, conversation_id) / "uploads" / name
        )
        size = self._copy_upload(source, destination, max_bytes, original_name)
        relative = self.user_relative(corp_id, destination)
        self._upsert_metadata(
            corp_id,
            relative,
            origin="upload",
            retention="chat",
            conversation_id=conversation_id,
            original_name=original_name,
        )
        protected = (
            self.user_data_root(corp_id) / "attachments" / attachment_id / name
        )
        protected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, protected)
        return (
            Attachment(
                attachment_id=attachment_id,
                original_name=original_name,
                relative_path=relative,
                content_type=content_type,
                size_bytes=size,
                created_at=utc_now(),
            ),
            protected,
        )

    def manual_upload(
        self,
        *,
        corp_id: str,
        original_name: str,
        source: BinaryIO,
        max_bytes: int,
        scope: WorkspaceScope = "shared",
        conversation_id: str | None = None,
    ) -> WorkspaceEntry:
        name = safe_filename(original_name)
        if scope == "chat":
            if not conversation_id:
                raise WorkspacePathError("A conversation ID is required for chat uploads.")
            conversation_id = _safe_conversation_id(conversation_id)
            destination = _unique_path(
                self.ensure_chat(corp_id, conversation_id) / "uploads" / name
            )
            retention = "chat"
        else:
            destination = _unique_path(self.shared_root(corp_id) / name)
            retention = "shared"
            conversation_id = None
        self._copy_upload(source, destination, max_bytes, original_name)
        relative = self.user_relative(corp_id, destination)
        self._upsert_metadata(
            corp_id,
            relative,
            origin="upload",
            retention=retention,
            conversation_id=conversation_id,
            original_name=original_name,
        )
        return self._entry(corp_id, destination)

    def promote(
        self, corp_id: str, relative_path: str, conversation_id: str
    ) -> WorkspaceEntry:
        conversation_id = _safe_conversation_id(conversation_id)
        source = self.resolve_user(corp_id, relative_path, must_exist=True)
        chat_root = self.chat_root(corp_id, conversation_id).resolve()
        if not source.resolve().is_relative_to(chat_root):
            raise WorkspacePathError(
                "Only files from the current chat can be kept in shared workspace."
            )
        destination = _unique_path(self.shared_root(corp_id) / source.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        old_relative = self.user_relative(corp_id, source)
        shutil.move(str(source), str(destination))
        new_relative = self.user_relative(corp_id, destination)
        self._move_metadata_prefix(
            corp_id, old_relative, new_relative, retention="shared"
        )
        return self._entry(corp_id, destination)

    def rename(self, corp_id: str, relative_path: str, new_name: str) -> str:
        source = self.resolve_user(corp_id, relative_path, must_exist=True)
        destination = source.with_name(safe_filename(new_name))
        if destination.exists():
            raise FileExistsError(destination.name)
        if not destination.resolve(strict=False).is_relative_to(
            self.user_root(corp_id).resolve()
        ):
            raise WorkspacePathError("The destination escapes the workspace.")
        old_relative = self.user_relative(corp_id, source)
        source.rename(destination)
        new_relative = self.user_relative(corp_id, destination)
        self._move_metadata_prefix(corp_id, old_relative, new_relative)
        return new_relative

    def delete(self, corp_id: str, relative_path: str) -> None:
        target = self.resolve_user(corp_id, relative_path, must_exist=True)
        relative = self.user_relative(corp_id, target)
        if relative in _LAYOUT_NAMES:
            raise WorkspacePathError("This workspace entry is protected.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self._remove_metadata_prefix(corp_id, relative)

    def cleanup_chat(self, corp_id: str, conversation_id: str) -> None:
        conversation_id = _safe_conversation_id(conversation_id)
        root = self.chat_root(corp_id, conversation_id)
        if root.exists():
            shutil.rmtree(root)
        self._remove_metadata_prefix(corp_id, f"chats/{conversation_id}")
        root.mkdir(parents=True, exist_ok=True)

    def cleanup_temporary(self, corp_id: str, conversation_id: str | None = None) -> None:
        temp_root = self.temp_root(corp_id)
        if temp_root.exists():
            for child in temp_root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
        roots = [self.chat_root(corp_id, conversation_id)] if conversation_id else [self.user_root(corp_id)]
        for root in roots:
            if not root.exists():
                continue
            for name in ("large_tool_results", "__pycache__", ".pytest_cache"):
                for cache in root.rglob(name):
                    if cache.is_dir() and not cache.is_symlink():
                        shutil.rmtree(cache, ignore_errors=True)

    def manifest(self, corp_id: str) -> dict[str, FileStamp]:
        result: dict[str, FileStamp] = {}
        root = self.ensure_user(corp_id)
        for path in root.rglob("*"):
            relative_parts = path.relative_to(root).parts
            if any(
                part in _PROTECTED_PARTS or part.startswith(".")
                for part in relative_parts
            ):
                continue
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            result[relative] = FileStamp(size=path.stat().st_size, sha256=_sha256(path))
        return result

    def stage_baseline(
        self, corp_id: str, run_id: str
    ) -> tuple[dict[str, FileStamp], Path]:
        manifest = self.manifest(corp_id)
        baseline = self.user_data_root(corp_id) / "baselines" / run_id
        if baseline.exists():
            shutil.rmtree(baseline)
        for relative in manifest:
            source = self.resolve_user(corp_id, relative, must_exist=True)
            destination = baseline / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return manifest, baseline

    def snapshot_changes(
        self,
        *,
        corp_id: str,
        run_id: str,
        conversation_id: str | None = None,
        before: dict[str, FileStamp],
        baseline: Path,
    ) -> list[tuple[Artifact, Path]]:
        after = self.manifest(corp_id)
        changed: list[tuple[str, str]] = []
        for relative, stamp in after.items():
            if relative not in before:
                changed.append((relative, "created"))
            elif before[relative] != stamp:
                changed.append((relative, "modified"))
        changed.extend((relative, "deleted") for relative in before.keys() - after.keys())

        artifacts: list[tuple[Artifact, Path]] = []
        artifact_root = self.user_data_root(corp_id) / "artifacts" / run_id
        for relative, change_type in sorted(changed):
            source = (
                baseline / relative
                if change_type == "deleted"
                else self.resolve_user(corp_id, relative, must_exist=True)
            )
            artifact_id = uuid.uuid4().hex
            destination = artifact_root / artifact_id / Path(relative).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            artifacts.append(
                (
                    Artifact(
                        artifact_id=artifact_id,
                        run_id=run_id,
                        relative_path=relative,
                        change_type=change_type,  # type: ignore[arg-type]
                        size_bytes=source.stat().st_size,
                        sha256=_sha256(source),
                        created_at=utc_now(),
                    ),
                    destination,
                )
            )
            if change_type == "deleted":
                self._remove_metadata_prefix(corp_id, relative)
            else:
                retention, owner = _retention_for_path(relative)
                self._upsert_metadata(
                    corp_id,
                    relative,
                    origin="agent",
                    retention=retention,
                    conversation_id=owner or conversation_id,
                    run_id=run_id,
                    original_name=Path(relative).name,
                    preserve_origin=change_type == "modified",
                )
        if baseline.exists():
            shutil.rmtree(baseline)
        return artifacts

    def _scope_root(
        self, corp_id: str, scope: WorkspaceScope, conversation_id: str | None
    ) -> Path:
        if scope == "shared":
            self.ensure_user(corp_id)
            return self.shared_root(corp_id)
        if scope != "chat":
            raise WorkspacePathError("Workspace scope must be 'chat' or 'shared'.")
        if not conversation_id:
            raise WorkspacePathError("A conversation ID is required for chat workspace.")
        return self.ensure_chat(corp_id, conversation_id)

    def _entries(self, corp_id: str, directory: Path) -> list[WorkspaceEntry]:
        if not directory.is_dir():
            raise WorkspacePathError("The requested workspace path is not a directory.")
        entries: list[WorkspaceEntry] = []
        for child in sorted(
            directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        ):
            if (
                child.name.startswith(".")
                or child.name in _PROTECTED_PARTS
                or child.is_symlink()
            ):
                continue
            entries.append(self._entry(corp_id, child))
        return entries

    def _entry(self, corp_id: str, path: Path) -> WorkspaceEntry:
        stat = path.stat()
        relative = self.user_relative(corp_id, path)
        metadata = self._metadata_for(corp_id, relative)
        scope, owner = _scope_for_path(relative)
        return WorkspaceEntry(
            path=relative,
            name=path.name,
            kind="directory" if path.is_dir() else "file",
            size_bytes=stat.st_size if path.is_file() else 0,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            scope=scope,
            origin=str(metadata.get("origin") or "unknown"),
            retention=str(metadata.get("retention") or scope),
            conversation_id=metadata.get("conversation_id") or owner,
            run_id=metadata.get("run_id"),
            original_name=metadata.get("original_name"),
            created_at=_parse_datetime(metadata.get("created_at")),
            can_promote=scope == "chat",
            can_modify=True,
        )

    def _copy_upload(
        self, source: BinaryIO, destination: Path, max_bytes: int, original_name: str
    ) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.uploading")
        size = 0
        try:
            with temp.open("wb") as handle:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(
                            f"{original_name!r} exceeds the {max_bytes} byte upload limit."
                        )
                    handle.write(chunk)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        return size

    def _metadata_path(self, corp_id: str) -> Path:
        return self.user_data_root(corp_id) / "workspace-metadata.json"

    def _load_metadata(self, corp_id: str) -> dict[str, dict[str, Any]]:
        with self._metadata_lock:
            path = self._metadata_path(corp_id)
            if not path.exists():
                return {}
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

    def _save_metadata(self, corp_id: str, value: dict[str, dict[str, Any]]) -> None:
        with self._metadata_lock:
            path = self._metadata_path(corp_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp, path)

    def _metadata_for(self, corp_id: str, relative: str) -> dict[str, Any]:
        return self._load_metadata(corp_id).get(relative, {})

    def _upsert_metadata(
        self,
        corp_id: str,
        relative: str,
        *,
        origin: str,
        retention: str,
        conversation_id: str | None = None,
        run_id: str | None = None,
        original_name: str | None = None,
        preserve_origin: bool = False,
    ) -> None:
        with self._metadata_lock:
            metadata = self._load_metadata(corp_id)
            previous = metadata.get(relative, {})
            now = utc_now().isoformat()
            metadata[relative] = {
                "origin": previous.get("origin")
                if preserve_origin and previous.get("origin")
                else origin,
                "retention": retention,
                "conversation_id": conversation_id or previous.get("conversation_id"),
                "run_id": run_id or previous.get("run_id"),
                "original_name": original_name or previous.get("original_name"),
                "created_at": previous.get("created_at") or now,
                "updated_at": now,
            }
            self._save_metadata(corp_id, metadata)

    def _move_metadata_prefix(
        self,
        corp_id: str,
        old_prefix: str,
        new_prefix: str,
        *,
        retention: str | None = None,
    ) -> None:
        with self._metadata_lock:
            metadata = self._load_metadata(corp_id)
            changed = False
            for path in list(metadata):
                if path != old_prefix and not path.startswith(old_prefix + "/"):
                    continue
                suffix = path[len(old_prefix) :].lstrip("/")
                new_path = new_prefix + (f"/{suffix}" if suffix else "")
                record = metadata.pop(path)
                if retention:
                    record["retention"] = retention
                record["updated_at"] = utc_now().isoformat()
                metadata[new_path] = record
                changed = True
            if changed:
                self._save_metadata(corp_id, metadata)

    def _remove_metadata_prefix(self, corp_id: str, prefix: str) -> None:
        with self._metadata_lock:
            metadata = self._load_metadata(corp_id)
            filtered = {
                path: value
                for path, value in metadata.items()
                if path != prefix and not path.startswith(prefix + "/")
            }
            if len(filtered) != len(metadata):
                self._save_metadata(corp_id, filtered)


def _safe_conversation_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not _SAFE_ID.fullmatch(candidate):
        raise WorkspacePathError("The conversation ID is invalid.")
    return candidate


def _safe_subpath(value: str, *, allow_empty: bool = False) -> PurePosixPath:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    pure = PurePosixPath(raw or ".")
    parts = tuple(part for part in pure.parts if part not in {"", "."})
    if not parts and allow_empty:
        return PurePosixPath(".")
    if not parts or any(
        part in {"..", "~"}
        or part.startswith(".")
        or part in _PROTECTED_PARTS
        or part == "users"
        for part in parts
    ):
        raise WorkspacePathError("The workspace subpath is unsafe.")
    return PurePosixPath(*parts)


def _unique_path(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 2
    while True:
        candidate = destination.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _scope_for_path(relative: str) -> tuple[str, str | None]:
    parts = PurePosixPath(relative).parts
    if len(parts) >= 2 and parts[0] == "chats":
        return "chat", parts[1]
    return "shared", None


def _retention_for_path(relative: str) -> tuple[str, str | None]:
    scope, owner = _scope_for_path(relative)
    return ("chat", owner) if scope == "chat" else ("shared", None)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
