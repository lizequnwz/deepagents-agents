"""Bounded repository context from the same approved source inventory as tools."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from general_agent.coding.source import source_revision, source_snapshot


_OVERVIEW_FILES = (
    "README.md", "README.rst", "README", "pyproject.toml", "package.json",
    "Cargo.toml", "go.mod", "Makefile", "justfile", "pytest.ini", "tox.ini",
)


def repository_context(
    repo: Path, *, tracked_paths: tuple[str, ...] = (), max_files: int = 5000,
    max_bytes: int = 50 * 1024 * 1024,
) -> dict:
    """Return scoped instruction data and a compact map, never host-parent files.

    Repository text is untrusted task data. Each AGENTS.md applies only to its
    own directory and descendants; callers retain application policy authority.
    """

    inventory = source_snapshot(
        repo, tracked_paths=tracked_paths, max_files=max_files, max_bytes=max_bytes,
    )
    paths = sorted(inventory)
    instructions = []
    instruction_remaining = 80_000
    truncated = False
    for path in paths:
        if PurePosixPath(path).name != "AGENTS.md":
            continue
        entry = inventory[path]
        try:
            text = entry["content"].decode("utf-8")
        except UnicodeDecodeError:
            truncated = True
            continue
        if "\0" in text:
            truncated = True
            continue
        if len(text) > instruction_remaining:
            truncated = True
        if not instruction_remaining:
            continue
        scope = PurePosixPath(path).parent.as_posix()
        instructions.append({
            "path": path, "scope": "/" if scope == "." else scope + "/",
            "sha256": entry["sha256"], "text": text[:instruction_remaining],
            "truncated": len(text) > instruction_remaining,
        })
        instruction_remaining -= min(len(text), instruction_remaining)

    top_level = sorted({PurePosixPath(path).parts[0] for path in paths})
    test_paths = [path for path in paths if (
        "tests" in PurePosixPath(path).parts or "test" in PurePosixPath(path).parts
        or PurePosixPath(path).name.startswith("test_")
        or PurePosixPath(path).name.endswith((".test.ts", ".test.js", "_test.go"))
    )]
    ci_paths = [path for path in paths if path.startswith(".github/workflows/")]
    overview = {
        "source_files": len(paths), "source_bytes": sum(entry["size"] for entry in inventory.values()),
        "top_level": top_level, "tests": test_paths[:80], "ci": ci_paths[:40],
        "instruction_scopes": [{"path": item["path"], "scope": item["scope"]} for item in instructions],
    }
    summary = "Repository source map:\n" + json.dumps(overview, ensure_ascii=False, indent=2)
    for path in _OVERVIEW_FILES:
        entry = inventory.get(path)
        if entry is None:
            continue
        try:
            text = entry["content"].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "\0" in text:
            continue
        summary += f"\n\n--- {path} (repository data) ---\n{text[:4000]}"
    if len(summary) > 20_000:
        summary = summary[:20_000]
        truncated = True
    return {
        "summary": summary, "instructions": instructions, "inventory": paths,
        "revision": source_revision(inventory), "truncated": truncated,
    }
