from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_analytics_agent.config import Settings


@pytest.fixture
def test_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    project_root = tmp_path / "project"
    semantic_dir = project_root / "semantic"
    database_dir = project_root / "db"
    semantic_dir.mkdir(parents=True)
    database_dir.mkdir(parents=True)

    database_path = database_dir / "test.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE Artist (ArtistId INTEGER PRIMARY KEY, Name TEXT)"
    )
    connection.commit()
    connection.close()

    (semantic_dir / "test.osi.yaml").write_text(
        """\
version: "0.1.1"
semantic_model:
  - name: test_model
    description: Test model.
    datasets:
      - name: artists
        source: Artist
        primary_key: [artist_id]
        description: Artists.
        fields:
          - name: artist_id
            expression: {dialects: [{dialect: ANSI_SQL, expression: ArtistId}]}
            description: Artist identifier.
          - name: name
            expression: {dialects: [{dialect: ANSI_SQL, expression: Name}]}
            description: Artist name.
    relationships: []
    metrics:
      - name: artist_count
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(DISTINCT artists.ArtistId)
        description: Number of artists.
""",
        encoding="utf-8",
    )
    registry_path = project_root / "data_sources.yaml"
    registry_path.write_text(
        """\
version: 1
default_source: test
backends:
  sqlite:
    type: sqlite
sources:
  test:
    name: Test source
    description: Test source for isolated API tests.
    backend: sqlite
    semantic_model: semantic/test.osi.yaml
    dialect: sqlite
    target:
      path: db/test.sqlite
    examples: []
  test_alt:
    name: Alternate test source
    description: Second source for conversation binding tests.
    backend: sqlite
    semantic_model: semantic/test.osi.yaml
    dialect: sqlite
    target:
      path: db/test.sqlite
    examples: []
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return Settings(
        project_root=project_root,
        data_sources_config_path=registry_path,
    )
