from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from data_analytics_agent.backends import SQLiteBackend
from data_analytics_agent.config import Settings
from data_analytics_agent.data_sources import DataSource, ExecutionLimits
from data_analytics_agent.agents.text_to_sql.tools import (
    MAX_RESULT_ROWS,
    SQLValidationError,
    execute_query,
    validate_readonly_sql,
)
from data_analytics_agent.stores import ResultStore


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE numbers (value INTEGER PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO numbers(value) VALUES (?)",
        [(number,) for number in range(600)],
    )
    connection.commit()
    connection.close()
    return path


def _source(
    *,
    timeout_seconds: float = 2,
) -> DataSource:
    base = Settings().load_catalog().get("chinook")
    return replace(
        base,
        limits=ExecutionLimits(
            timeout_seconds=timeout_seconds,
            max_result_rows=MAX_RESULT_ROWS,
            model_sample_rows=10,
        ),
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
        "SELECT 1 UNION SELECT 2",
    ],
)
def test_accepts_readonly_query_forms(query: str) -> None:
    assert validate_readonly_sql(query) is not None


@pytest.mark.parametrize(
    "query",
    [
        "",
        "SELECT 1; SELECT 2",
        "INSERT INTO numbers VALUES (1)",
        "UPDATE numbers SET value = 2",
        "DELETE FROM numbers",
        "CREATE TABLE unsafe (id INTEGER)",
        "DROP TABLE numbers",
        "PRAGMA table_info(numbers)",
        "ATTACH DATABASE 'other.db' AS other",
        "BEGIN TRANSACTION",
        "VACUUM",
    ],
)
def test_rejects_unsafe_or_multiple_sql(query: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_readonly_sql(query)


def test_exact_sql_cap_truncation_and_model_sample(database: Path) -> None:
    store = ResultStore()
    query = "SELECT value FROM numbers ORDER BY value"
    result = execute_query(
        backend=SQLiteBackend(database),
        source=_source(),
        query=query,
        thread_id="thread-a",
        result_store=store,
    )
    assert result.executed_sql == query
    assert result.row_count == MAX_RESULT_ROWS
    assert result.truncated is True
    assert len(result.sample_rows) == 10
    assert store.get(
        result.result_id,
        "thread-a",
        source_id="chinook",
    ).rows[-1]["value"] == 499


def test_readonly_database_remains_unchanged(database: Path) -> None:
    store = ResultStore()
    execute_query(
        backend=SQLiteBackend(database),
        source=_source(),
        query="SELECT COUNT(*) AS count FROM numbers",
        thread_id="thread-a",
        result_store=store,
    )
    connection = sqlite3.connect(database)
    count = connection.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
    connection.close()
    assert count == 600


def test_execution_timeout(database: Path) -> None:
    with pytest.raises(TimeoutError):
        execute_query(
            backend=SQLiteBackend(database),
            source=_source(timeout_seconds=0.000001),
            query=(
                "WITH RECURSIVE counter(x) AS ("
                "SELECT 1 UNION ALL SELECT x + 1 FROM counter WHERE x < 10000000"
                ") SELECT SUM(x) FROM counter"
            ),
            thread_id="thread-a",
            result_store=ResultStore(),
        )
