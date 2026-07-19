from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from data_analytics_agent.coordinator import build_agent
from data_analytics_agent.backends import SQLiteBackend
from data_analytics_agent.config import Settings
from data_analytics_agent.stores import ResultStore


def test_agent_graph_builds_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "chinook.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE Artist (ArtistId INTEGER PRIMARY KEY, Name TEXT)"
    )
    connection.close()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = Settings()
    source = replace(
        settings.load_catalog().get("chinook"),
        target={"path": str(database)},
    )
    graph = build_agent(
        settings,
        ResultStore(),
        source=source,
        backend=SQLiteBackend(database),
    )
    assert graph.name == "data-analytics-agent"
    assert graph.context_schema is None
    state_properties = graph.get_input_jsonschema()["properties"]
    assert {"thread_id", "run_id", "source_id"} <= set(state_properties)
    assert {"model", "tools"} <= set(graph.nodes)


@pytest.mark.live
def test_live_agent_builds() -> None:
    if not os.getenv("RUN_LIVE_SMOKE"):
        pytest.skip("Set RUN_LIVE_SMOKE=1 to enable the live smoke test.")
    settings = Settings()
    if settings.readiness_errors():
        pytest.skip("OPENAI_API_KEY and a source registry are required.")
    source = settings.load_catalog().get(
        settings.load_catalog().default_source_id
    )
    assert (
        build_agent(
            settings,
            ResultStore(),
            source=source,
            backend=SQLiteBackend(
                settings.project_root / str(source.target["path"])
            ),
        )
        is not None
    )
