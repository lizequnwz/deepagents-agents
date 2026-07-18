from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from text2sql_agent.agent import build_agent
from text2sql_agent.config import Settings
from text2sql_agent.stores import ResultStore


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
    settings = Settings(database_path=database)
    graph = build_agent(settings, ResultStore())
    assert graph.name == "chinook-data-analyst"
    assert {"model", "tools"} <= set(graph.nodes)


@pytest.mark.live
def test_live_agent_builds() -> None:
    if not os.getenv("RUN_LIVE_SMOKE"):
        pytest.skip("Set RUN_LIVE_SMOKE=1 to enable the live smoke test.")
    settings = Settings()
    if settings.readiness_errors():
        pytest.skip("OPENAI_API_KEY and Chinook database are required.")
    assert build_agent(settings, ResultStore()) is not None
