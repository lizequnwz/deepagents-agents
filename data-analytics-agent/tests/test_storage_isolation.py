"""Protect configured workspace history before pytest collection and fixtures."""

import os
import subprocess
import sys
from pathlib import Path
from data_analytics_agent.persistence import LocalStorage
from data_analytics_agent.stores import ConversationStore, RunStore


def test_settings_storage_is_per_test(test_settings, tmp_path):
    assert test_settings.storage_dir == (tmp_path / "storage").resolve()


def test_collection_ignores_inherited_workspace_storage(tmp_path):
    root = tmp_path / "developer-sentinel"
    storage = LocalStorage(root)
    conversations, runs = ConversationStore(storage), RunStore(storage)
    thread = conversations.create("sentinel")
    run = runs.create(thread, "sentinel", "Keep this history")
    conversations.begin_run(thread, run)
    runs.start_active(run)
    sentinel = storage.artifacts / "sentinel.txt"
    sentinel.write_text("Keep this artifact")
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    collection = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "tests/test_history.py",
            "-q",
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "ANALYTICS_STORAGE_DIR": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert collection.returncode == 0, collection.stdout + collection.stderr
    after = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert before == after
