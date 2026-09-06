from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from data_analytics_agent import api
from data_analytics_agent.api import Services
from data_analytics_agent.backends import (
    SQLExecutionError,
    SnowflakeBackend,
    SQLValidationError,
    create_backend,
)
from data_analytics_agent.config import Settings


class FakeCursor:
    def __init__(
        self,
        columns: list[str],
        rows: list[Any],
        *,
        fetch_error: Exception | None = None,
    ) -> None:
        self.description = [(name,) for name in columns]
        self.rows = list(rows)
        self.fetch_error = fetch_error
        self.fetch_sizes: list[int] = []
        self.closed = False

    def fetchmany(self, size: int) -> list[Any]:
        self.fetch_sizes.append(size)
        if self.fetch_error is not None:
            raise self.fetch_error
        batch = self.rows[:size]
        self.rows = self.rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True


class FakeSnowflakeClient:
    def __init__(self, cursors: list[FakeCursor]) -> None:
        self.cursors = list(cursors)
        self.calls: list[tuple[str, float]] = []

    def run_query(
        self,
        query: str,
        *,
        timeout_seconds: float,
    ) -> FakeCursor:
        self.calls.append((query, timeout_seconds))
        return self.cursors.pop(0)


class FakeSnowflakeError(RuntimeError):
    def __init__(self, message: str, *, errno: int) -> None:
        super().__init__(message)
        self.msg = message
        self.errno = errno


def test_execute_forwards_exact_sql_caps_normalizes_and_closes() -> None:
    cursor = FakeCursor(
        ["AMOUNT", "DAY", "PAYLOAD"],
        [
            (Decimal("1.20"), date(2026, 7, 20), b"a"),
            (Decimal("2.30"), date(2026, 7, 21), b"b"),
            (Decimal("3.40"), date(2026, 7, 22), b"c"),
        ],
    )
    client = FakeSnowflakeClient([cursor])
    backend = SnowflakeBackend(client)
    query = "SELECT amount, day, payload FROM facts ORDER BY day"

    import pyarrow as pa

    result = pa.Table.from_batches(
        list(backend.execute_batches(query, timeout_seconds=7.5))
    )
    assert client.calls == [(query, 7.5)]
    assert cursor.closed
    assert result.to_pylist()[0] == {
        "AMOUNT": Decimal("1.20"),
        "DAY": date(2026, 7, 20),
        "PAYLOAD": b"a",
    }
    assert result.num_rows == 3


def test_execute_rejects_unsafe_sql_before_calling_client() -> None:
    client = FakeSnowflakeClient([])
    backend = SnowflakeBackend(client)

    with pytest.raises(SQLValidationError):
        list(
            backend.execute_batches(
                "DELETE FROM facts",
                timeout_seconds=5,
            )
        )

    assert client.calls == []


def test_execute_translates_cancel_and_closes_cursor() -> None:
    cursor = FakeCursor(
        ["VALUE"],
        [],
        fetch_error=FakeSnowflakeError("query canceled", errno=604),
    )
    backend = SnowflakeBackend(FakeSnowflakeClient([cursor]))

    with pytest.raises(TimeoutError, match="exceeded 3 seconds"):
        list(
            backend.execute_batches(
                "SELECT value FROM facts",
                timeout_seconds=3,
            )
        )

    assert cursor.closed is True


def test_execute_wraps_expected_provider_query_errors() -> None:
    cursor = FakeCursor(
        ["VALUE"],
        [],
        fetch_error=FakeSnowflakeError("unknown table", errno=2003),
    )
    backend = SnowflakeBackend(FakeSnowflakeClient([cursor]))

    with pytest.raises(SQLExecutionError, match=r"\[2003\] unknown table"):
        list(
            backend.execute_batches(
                "SELECT value FROM missing_facts",
                timeout_seconds=3,
            )
        )

    assert cursor.closed is True


def test_targeted_schema_uses_configured_context() -> None:
    columns = FakeCursor(
        ["TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "IS_NULLABLE"],
        [
            ("ORDERS", "ORDER_ID", "NUMBER", "NO"),
            ("ORDERS", "TOTAL", "NUMBER", "YES"),
        ],
    )
    client = FakeSnowflakeClient([columns])
    backend = SnowflakeBackend(client)

    schema = backend.get_table_schema(["orders"])

    assert schema[0].name == "ORDERS"
    actual_columns = [
        (column.name, column.data_type, column.nullable) for column in schema[0].columns
    ]
    assert actual_columns == [
        ("ORDER_ID", "NUMBER", False),
        ("TOTAL", "NUMBER", True),
    ]
    assert columns.closed is True
    assert len(client.calls) == 1
    assert all(timeout == 10 for _, timeout in client.calls)
    assert "INFORMATION_SCHEMA.COLUMNS" in client.calls[0][0]
    assert "'ORDERS'" in client.calls[0][0]


def test_factory_requires_empty_target_and_injected_client(
    test_settings: Settings,
) -> None:
    sqlite_source = test_settings.load_catalog().get("test")
    snowflake_source = replace(
        sqlite_source,
        backend_id="snowflake",
        backend_type="snowflake",
        dialect="snowflake",
        target={},
    )

    with pytest.raises(ValueError, match="requires a snowlib client"):
        create_backend(snowflake_source, test_settings.project_root)

    client = FakeSnowflakeClient([])
    backend = create_backend(
        snowflake_source,
        test_settings.project_root,
        snowflake_client=client,
    )
    assert isinstance(backend, SnowflakeBackend)
    assert backend.client is client

    targeted = replace(snowflake_source, target={"schema": "OTHER"})
    with pytest.raises(ValueError, match="empty target"):
        create_backend(
            targeted,
            test_settings.project_root,
            snowflake_client=client,
        )


def test_services_lazily_creates_and_reuses_snowlib_client(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_catalog = test_settings.load_catalog()
    sqlite_source = sqlite_catalog.get("test")
    snowflake_source = replace(
        sqlite_source,
        backend_id="snowflake",
        backend_type="snowflake",
        dialect="snowflake",
        target={},
    )
    catalog = replace(
        sqlite_catalog,
        sources={"test": snowflake_source},
    )
    client = FakeSnowflakeClient([])
    created: list[object] = []

    def create_client() -> FakeSnowflakeClient:
        created.append(object())
        return client

    monkeypatch.setattr(api, "_create_snowflake_client", create_client)
    services = Services(settings=test_settings, catalog=catalog)

    first = services.backend_for_source("test")
    second = services.backend_for_source("test")

    assert first is second
    assert isinstance(first, SnowflakeBackend)
    assert first.client is client
    assert len(created) == 1


def test_snowlib_remains_optional_for_sqlite(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called() -> Any:
        raise AssertionError("snowlib should not be initialized")

    monkeypatch.setattr(api, "_create_snowflake_client", fail_if_called)
    services = Services(settings=test_settings)

    backend = services.backend_for_source("test")

    assert backend.backend_type == "sqlite"
