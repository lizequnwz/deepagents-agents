"""Minimal corporation-scoped file storage for advisor matching."""

from __future__ import annotations

import contextvars
import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from general_agent.schemas import Attachment, utc_now

_CURRENT_CORP_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "advisor_match_corp_id", default=None
)
_CURRENT_CONVERSATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "advisor_match_conversation_id", default=None
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._() -]+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CATEGORIES = {"attachments", "advisor_references", "artifacts"}


class WorkspacePathError(ValueError):
    """Raised when protected storage scope or path validation fails."""


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
    conversation_token = _CURRENT_CONVERSATION_ID.set(_safe_id(conversation_id))
    return corp_token, conversation_token


def reset_current_workspace(
    tokens: tuple[contextvars.Token[str | None], contextvars.Token[str | None]],
) -> None:
    corp_token, conversation_token = tokens
    _CURRENT_CONVERSATION_ID.reset(conversation_token)
    _CURRENT_CORP_ID.reset(corp_token)


def current_conversation_id() -> str | None:
    return _CURRENT_CONVERSATION_ID.get()


def current_corp_id() -> str | None:
    return _CURRENT_CORP_ID.get()


def safe_filename(name: str) -> str:
    basename = Path(str(name).replace("\\", "/")).name.strip()
    basename = _SAFE_NAME.sub("_", basename).strip(". ")
    if not basename or basename in {".", ".."}:
        raise WorkspacePathError("The file name is empty or unsafe.")
    return basename[:240]


class Workspace:
    """Own immutable attachments, reference snapshots, and workbook artifacts."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.users_root = self.data_root / "users"
        self.users_root.mkdir(parents=True, exist_ok=True)

    def user_data_root(self, corp_id: str) -> Path:
        return self.users_root / corp_storage_key(corp_id)

    def ensure_user(self, corp_id: str) -> Path:
        root = self.user_data_root(corp_id)
        for category in sorted(_CATEGORIES):
            (root / category).mkdir(parents=True, exist_ok=True)
        return root

    def category_root(self, corp_id: str, category: str) -> Path:
        if category not in _CATEGORIES:
            raise WorkspacePathError("Unknown protected storage category.")
        return self.ensure_user(corp_id) / category

    def attachment_file(
        self, corp_id: str, attachment_id: str, original_name: str
    ) -> Path:
        return self._scoped_file(
            corp_id, "attachments", attachment_id, safe_filename(original_name)
        )

    def reference_file(self, corp_id: str, snapshot_id: str) -> Path:
        return self._scoped_file(
            corp_id, "advisor_references", snapshot_id, "advisor_reference.csv"
        )

    def artifact_file(
        self, corp_id: str, run_id: str, artifact_id: str
    ) -> Path:
        run_root = self.category_root(corp_id, "artifacts") / _safe_id(run_id)
        target = run_root / _safe_id(artifact_id) / "advisor_matches.xlsx"
        self._assert_within(target, self.category_root(corp_id, "artifacts"))
        return target

    def validate_file(self, corp_id: str, category: str, path: Path) -> Path:
        root = self.category_root(corp_id, category).resolve()
        candidate = path.resolve(strict=False)
        if not candidate.is_relative_to(root):
            raise WorkspacePathError("The protected file is outside its corporation scope.")
        if not path.is_file() or path.is_symlink():
            raise WorkspacePathError("The protected file is unavailable or invalid.")
        return path

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
        _safe_id(conversation_id)
        attachment_id = uuid.uuid4().hex
        destination = self.attachment_file(corp_id, attachment_id, original_name)
        size, sha256 = self._copy_upload(source, destination, max_bytes, original_name)
        return (
            Attachment(
                attachment_id=attachment_id,
                original_name=original_name,
                content_type=content_type,
                size_bytes=size,
                sha256=sha256,
                created_at=utc_now(),
            ),
            destination,
        )

    def _scoped_file(
        self, corp_id: str, category: str, object_id: str, filename: str
    ) -> Path:
        root = self.category_root(corp_id, category)
        target = root / _safe_id(object_id) / filename
        self._assert_within(target, root)
        return target

    @staticmethod
    def _assert_within(candidate: Path, root: Path) -> None:
        if not candidate.resolve(strict=False).is_relative_to(root.resolve()):
            raise WorkspacePathError("The protected path escapes its storage root.")

    @staticmethod
    def _copy_upload(
        source: BinaryIO, destination: Path, max_bytes: int, original_name: str
    ) -> tuple[int, str]:
        destination.parent.mkdir(parents=True, exist_ok=False)
        temporary = destination.with_name(f".{destination.name}.uploading")
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("xb") as handle:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(
                            f"{original_name!r} exceeds the {max_bytes} byte upload limit."
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.parent.rmdir()
            raise
        return size, digest.hexdigest()


def _safe_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not _SAFE_ID.fullmatch(candidate):
        raise WorkspacePathError("The storage identifier is invalid.")
    return candidate
