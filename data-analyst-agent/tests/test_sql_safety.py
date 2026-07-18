from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from text2sql_agent.sql_tools import (
    MAX_RESULT_ROWS,
    SQLValidationError,
    execute_query,
    validate_readonly_sql,
)
from text2sql_agent.stores import ResultStore


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
        database_path=database,
        query=query,
        thread_id="thread-a",
        result_store=store,
        timeout_seconds=2,
    )
    assert result.executed_sql == query
    assert result.row_count == MAX_RESULT_ROWS
    assert result.truncated is True
    assert len(result.sample_rows) == 10
    assert store.get(result.result_id, "thread-a").rows[-1]["value"] == 499


def test_readonly_database_remains_unchanged(database: Path) -> None:
    store = ResultStore()
    execute_query(
        database_path=database,
        query="SELECT COUNT(*) AS count FROM numbers",
        thread_id="thread-a",
        result_store=store,
        timeout_seconds=2,
    )
    connection = sqlite3.connect(database)
    count = connection.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
    connection.close()
    assert count == 600


def test_execution_timeout(database: Path) -> None:
    with pytest.raises(TimeoutError):
        execute_query(
            database_path=database,
            query=(
                "WITH RECURSIVE counter(x) AS ("
                "SELECT 1 UNION ALL SELECT x + 1 FROM counter WHERE x < 10000000"
                ") SELECT SUM(x) FROM counter"
            ),
            thread_id="thread-a",
            result_store=ResultStore(),
            timeout_seconds=0.000001,
        )
