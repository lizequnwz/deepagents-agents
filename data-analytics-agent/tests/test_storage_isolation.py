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


def test_server_startup_uses_configured_root_and_preserves_history(test_settings):
    """Exercise the server import and lifespan with the original storage layout."""
    root = test_settings.storage_dir
    storage = LocalStorage(root)
    thread = ConversationStore(storage).create("test")
    artifact = storage.artifacts / "report.html"
    artifact.write_text("Saved report")
    script = """
from fastapi.testclient import TestClient
from data_analytics_agent.api import app, Services
services = app.state.services
assert services.storage.root == services.settings.storage_dir
assert len(services.conversations.list()) == 1
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    thread_id = services.conversations.create('test')
assert Services().conversations.exists(thread_id)
print(services.storage.root)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "ANALYTICS_STORAGE_DIR": str(root),
            "DATA_SOURCES_CONFIG": str(test_settings.data_sources_config_path),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith(str(root))
    assert ConversationStore(storage).exists(thread)
    assert artifact.read_text() == "Saved report"
    assert (root / "metadata.sqlite").is_file()
    assert (root / "checkpoints.sqlite").is_file()
    assert not list(root.glob("schema-*"))
