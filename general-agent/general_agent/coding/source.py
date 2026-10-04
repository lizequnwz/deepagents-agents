"""One source inclusion policy and secure byte access for coding services."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import TypedDict

from pathspec import GitIgnoreSpec

from general_agent.workspace import (
    WorkspacePathError,
    validate_workspace_path,
    workspace_directory,
    workspace_file,
)


class SourceEntry(TypedDict):
    sha256: str
    size: int
    mode: int
    content: bytes


_IGNORED_PARTS = {
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".cache", ".next", ".nuxt", "dist",
    "build", "coverage", "target", "large_tool_results",
}
_HIDDEN_FILES = {
    ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore",
    ".python-version", ".node-version", ".nvmrc", ".coveragerc", ".flake8",
    ".prettierrc", ".prettierrc.json", ".eslintrc", ".eslintrc.json",
    ".stylelintrc", ".env.example",
}
_HIDDEN_DIRECTORIES = {".github", ".devcontainer", ".vscode"}
_CREDENTIAL_NAMES = {
    "credentials", "credentials.json", "secrets.json", "id_rsa", "id_dsa",
    "id_ed25519", ".netrc", ".npmrc", ".pypirc", ".aws", ".ssh",
}
_KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def _source_parts(relative: str | PurePosixPath) -> tuple[str, ...]:
    raw = str(relative).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"..", "~"} for part in path.parts):
        raise WorkspacePathError("A safe repository-relative source path is required.")
    if "\x00" in raw:
        raise WorkspacePathError("Source paths cannot contain null bytes.")
    return path.parts


def ignored_source(relative: str | PurePosixPath) -> bool:
    """Known generated/dependency metadata omitted from source exports."""

    parts = _source_parts(relative)
    return any(part in _IGNORED_PARTS for part in parts)


def ignored_source_parts() -> tuple[str, ...]:
    """App-owned generated-directory names for pruning runtime exports."""

    return tuple(sorted(_IGNORED_PARTS))


def allowed_source(relative: str | PurePosixPath) -> bool:
    """Allow source dotfiles without making credentials or app state public."""

    try:
        parts = _source_parts(relative)
    except WorkspacePathError:
        return False
    if any(part in _IGNORED_PARTS for part in parts):
        return False
    for index, part in enumerate(parts):
        lower = part.lower()
        if lower in _CREDENTIAL_NAMES or Path(lower).suffix in _KEY_SUFFIXES:
            return False
        if lower == ".env" or (lower.startswith(".env.") and lower != ".env.example"):
            return False
        if part.startswith("."):
            if part in _HIDDEN_DIRECTORIES:
                continue
            if index == len(parts) - 1 and part in _HIDDEN_FILES:
                continue
            return False
    return True


def validate_source_path(relative: str | PurePosixPath) -> PurePosixPath:
    parts = _source_parts(relative)
    if not allowed_source(relative):
        raise WorkspacePathError("This repository path is excluded by the source policy.")
    return PurePosixPath(*parts)


@contextlib.contextmanager
def source_file(
    root: Path, relative: str | PurePosixPath, flags: int = os.O_RDONLY,
    *, create_parents: bool = False,
) -> Iterator[int]:
    path = root.joinpath(*validate_source_path(relative).parts)
    with workspace_file(root, path, flags, create_parents=create_parents) as descriptor:
        yield descriptor


def source_snapshot(
    root: Path, *, excluded_roots: tuple[Path, ...] = (),
    max_files: int = 5000, max_bytes: int = 50 * 1024 * 1024,
    max_file_bytes: int = 5 * 1024 * 1024,
    tracked_paths: tuple[str, ...] = (),
    exclusions: dict[str, str] | None = None,
) -> dict[str, SourceEntry]:
    """Capture approved regular files; all reads are no-follow and bounded.

    Policy exclusions and links are omitted from original-source onboarding.
    Container archive import must separately reject forbidden names/link types
    before calling this function on its application-owned staging directory.
    """

    root = Path(root)
    validate_workspace_path(root, root, must_exist=True)
    snapshot: dict[str, SourceEntry] = {}
    total = 0
    visited = 0
    deadline = time.monotonic() + 10
    excluded = tuple(Path(path) for path in excluded_roots)
    tracked = frozenset(path for path in tracked_paths if allowed_source(path))

    def walk(directory: Path, rules: tuple[tuple[Path, GitIgnoreSpec], ...] = ()) -> None:
        nonlocal total, visited
        ignore = directory / ".gitignore"
        try:
            with source_file(root, ignore.relative_to(root).as_posix()) as descriptor:
                with os.fdopen(os.dup(descriptor), "rb") as reader:
                    contents = reader.read(64 * 1024 + 1)
                if len(contents) > 64 * 1024:
                    raise WorkspacePathError("Repository ignore instructions exceed the size limit.")
            rules += ((directory, GitIgnoreSpec.from_lines(contents.decode("utf-8").splitlines())),)
        except (FileNotFoundError, IsADirectoryError):
            pass
        except WorkspacePathError:
            if ignore.is_symlink():
                pass
            else:
                raise
        with workspace_directory(root, directory) as descriptor:
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    visited += 1
                    if visited > max_files * 4 or time.monotonic() >= deadline:
                        raise WorkspacePathError("Repository inventory exceeds its resource limit.")
                    path = directory / entry.name
                    relative = path.relative_to(root).as_posix()
                    if any(path == target or path.is_relative_to(target) for target in excluded):
                        if exclusions is not None:
                            exclusions[relative] = "application_storage"
                        continue
                    if not allowed_source(relative):
                        if exclusions is not None:
                            exclusions[relative] = "generated_or_dependency" if ignored_source(relative) else "protected_source_policy"
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        if exclusions is not None:
                            exclusions[relative] = "symlink"
                        continue
                    directory_entry = stat.S_ISDIR(info.st_mode)
                    ignored = False
                    for scope, spec in rules:
                        candidate = path.relative_to(scope).as_posix() + ("/" if directory_entry else "")
                        result = spec.check_file(candidate)
                        if result.include is not None:
                            ignored = result.include
                    retained = relative in tracked or (
                        directory_entry and any(item.startswith(relative + "/") for item in tracked)
                    )
                    if ignored and not retained:
                        if exclusions is not None:
                            exclusions[relative] = "gitignore"
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        walk(path, rules)
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o7000:
                        if exclusions is not None:
                            exclusions[relative] = "nonregular_alias_or_privileged_mode"
                        continue
                    if len(snapshot) >= max_files:
                        raise WorkspacePathError(f"Repository exceeds the {max_files} file source limit.")
                    with source_file(root, relative) as source:
                        info = os.fstat(source)
                        if info.st_size > max_file_bytes:
                            raise WorkspacePathError(f"Source file '{relative}' exceeds the file size limit.")
                        with os.fdopen(os.dup(source), "rb") as reader:
                            content = reader.read(min(max_file_bytes, max_bytes - total) + 1)
                    if len(content) > max_file_bytes or total + len(content) > max_bytes:
                        raise WorkspacePathError("Repository exceeds the total source size limit.")
                    total += len(content)
                    snapshot[relative] = {
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content), "mode": stat.S_IMODE(info.st_mode),
                        "content": content,
                    }

    walk(root)
    return snapshot


def source_manifest(root: Path, **kwargs) -> dict[str, dict]:
    return {
        path: {key: entry[key] for key in ("sha256", "size", "mode")}
        for path, entry in source_snapshot(root, **kwargs).items()
    }


def source_revision(manifest: dict) -> str:
    metadata = {
        path: {key: entry[key] for key in ("sha256", "size", "mode")}
        for path, entry in manifest.items()
    }
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
