from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone, timedelta
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
        description: list[Any] | None = None,
    ) -> None:
        self.description = description or [
            (name, 2, None, None, None, None, True) for name in columns
        ]
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
        description=[
            ("AMOUNT", 0, None, None, 12, 2, True),
            ("DAY", 3, None, None, None, None, True),
            ("PAYLOAD", 11, None, None, None, None, True),
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
        [
            "TABLE_CATALOG",
            "TABLE_SCHEMA",
            "TABLE_NAME",
            "COLUMN_NAME",
            "DATA_TYPE",
            "IS_NULLABLE",
        ],
        [
            ("DB", "PUBLIC", "ORDERS", "ORDER_ID", "NUMBER", "NO"),
            ("DB", "PUBLIC", "ORDERS", "TOTAL", "NUMBER", "YES"),
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


def test_qualified_schema_targets_only_requested_case_sensitive_objects():
    columns = [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "COLUMN_NAME",
        "DATA_TYPE",
        "IS_NULLABLE",
    ]
    name = '"My.DB"."Sales Team"."mixedTable"'
    cursor = FakeCursor(
        columns, [("My.DB", "Sales Team", "mixedTable", "ID", "NUMBER", "NO")]
    )
    client = FakeSnowflakeClient([cursor])
    result = SnowflakeBackend(client).get_table_schema([name])
    assert result[0].name == name
    assert result[0].columns[0].name == "ID"
    query = client.calls[0][0]
    assert 'FROM "My.DB".INFORMATION_SCHEMA.COLUMNS' in query
    assert "TABLE_SCHEMA = 'Sales Team'" in query
    assert "TABLE_NAME IN ('mixedTable')" in query
    assert "UPPER(" not in query and "CURRENT_SCHEMA()" not in query


def test_current_and_other_schema_same_named_tables_keep_separate_columns():
    columns = [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "COLUMN_NAME",
        "DATA_TYPE",
        "IS_NULLABLE",
    ]
    current = FakeCursor(
        columns, [("DB", "PUBLIC", "ORDERS", "LOCAL_ID", "NUMBER", "NO")]
    )
    other = FakeCursor(columns, [("DB", "OTHER", "ORDERS", "OTHER_ID", "NUMBER", "NO")])
    client = FakeSnowflakeClient([current, other])
    result = SnowflakeBackend(client).get_table_schema(["orders", "other.orders"])
    assert [table.name for table in result] == ["ORDERS", "OTHER.ORDERS"]
    assert [table.columns[0].name for table in result] == ["LOCAL_ID", "OTHER_ID"]
    assert "CURRENT_SCHEMA()" in client.calls[0][0]
    assert "TABLE_SCHEMA = 'OTHER'" in client.calls[1][0]


def test_case_sensitive_table_mismatch_does_not_use_similarly_named_table():
    columns = [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "COLUMN_NAME",
        "DATA_TYPE",
        "IS_NULLABLE",
    ]
    cursor = FakeCursor(columns, [("DB", "PUBLIC", "ORDERS", "ID", "NUMBER", "NO")])
    with pytest.raises(ValueError, match="Unknown table"):
        SnowflakeBackend(FakeSnowflakeClient([cursor])).get_table_schema(['"orders"'])


def test_qualified_catalog_readiness_distinguishes_case_sensitive_sources(tmp_path):
    import yaml
    from data_analytics_agent.semantic import load_semantic_catalog

    columns = [
        "TABLE_CATALOG",
        "TABLE_SCHEMA",
        "TABLE_NAME",
        "COLUMN_NAME",
        "DATA_TYPE",
        "IS_NULLABLE",
    ]
    cursor = FakeCursor(
        columns,
        [
            ("DB", "S", "ORDERS", "ID", "NUMBER", "NO"),
            ("DB", "S", "orders", "ID", "VARCHAR", "NO"),
        ],
    )
    datasets = [
        {
            "name": logical,
            "source": source,
            "primary_key": ["id"],
            "fields": [
                {
                    "name": "id",
                    "expression": {
                        "dialects": [{"dialect": "ANSI_SQL", "expression": "ID"}]
                    },
                }
            ],
        }
        for logical, source in [
            ("upper", '"DB"."S"."ORDERS"'),
            ("lower", '"DB"."S"."orders"'),
        ]
    ]
    path = tmp_path / "model.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "0.1.1",
                "semantic_model": [
                    {
                        "name": "case_test",
                        "datasets": datasets,
                        "metrics": [],
                        "relationships": [],
                    }
                ],
            }
        )
    )
    loaded = load_semantic_catalog(
        path,
        dialect="snowflake",
        backend=SnowflakeBackend(FakeSnowflakeClient([cursor])),
    )
    assert loaded.catalog is not None, loaded.diagnostics.errors
    assert loaded.catalog.datasets["upper"].fields["id"].physical_data_type == "NUMBER"
    assert loaded.catalog.datasets["lower"].fields["id"].physical_data_type == "VARCHAR"


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


def test_empty_results_preserve_declared_types_and_precision():
    import pyarrow as pa
    from types import SimpleNamespace

    description = [
        SimpleNamespace(name="AMOUNT", type_code=0, precision=38, scale=8),
        SimpleNamespace(name="DAY", type_code=3),
        SimpleNamespace(name="EVENT_TIME", type_code=8),
        SimpleNamespace(name="CLOCK", type_code=12),
        SimpleNamespace(name="FLAG", type_code=13),
        SimpleNamespace(name="PAYLOAD", type_code=11),
    ]
    cursor = FakeCursor([d.name for d in description], [], description=description)
    batch = list(
        SnowflakeBackend(FakeSnowflakeClient([cursor])).execute_batches(
            "SELECT amount, day, event_time, clock, flag, payload FROM facts",
            timeout_seconds=5,
        )
    )[0]
    assert batch.num_rows == 0
    assert batch.schema.types == [
        pa.decimal128(38, 8),
        pa.date32(),
        pa.timestamp("us"),
        pa.time64("us"),
        pa.bool_(),
        pa.binary(),
    ]
    assert cursor.closed


def test_generic_timestamp_uses_documented_aware_fetch_contract():
    from datetime import datetime, timezone, timedelta
    import pyarrow as pa

    value = datetime(2026, 10, 18, 10, 0, tzinfo=timezone(timedelta(hours=-4)))
    cursor = FakeCursor(
        ["AT"], [(value,)], description=[("AT", 4, None, None, None, None, True)]
    )
    batch = list(
        SnowflakeBackend(FakeSnowflakeClient([cursor])).execute_batches(
            "SELECT at FROM facts", timeout_seconds=5
        )
    )[0]
    assert batch.schema.field("AT").type == pa.timestamp("us", tz="UTC")
    assert batch.to_pylist()[0]["AT"] == value.astimezone(timezone.utc)


def test_null_leading_batch_cannot_change_later_declared_schema():
    import pyarrow as pa

    description = [
        ("AMOUNT", 0, None, None, 38, 4, True),
        ("DAY", 3, None, None, None, None, True),
    ]
    cursor = FakeCursor(
        ["AMOUNT", "DAY"],
        [(None, None)] * 8192
        + [(Decimal("123456789012345678901234567890.1234"), date(2025, 1, 1))],
        description=description,
    )
    batches = list(
        SnowflakeBackend(FakeSnowflakeClient([cursor])).execute_batches(
            "SELECT amount, day FROM facts", timeout_seconds=5
        )
    )
    assert len(batches) == 2 and batches[0].schema == batches[1].schema
    combined = pa.Table.from_batches(batches)
    assert combined.schema.types == [pa.decimal128(38, 4), pa.date32()]
    assert combined.column("AMOUNT")[-1].as_py() == Decimal(
        "123456789012345678901234567890.1234"
    )


def test_aware_timestamp_types_keep_instants_and_naive_types_stay_naive():
    import pyarrow as pa

    aware = datetime(2025, 1, 1, 6, tzinfo=timezone(timedelta(hours=-5)))
    naive = datetime(9999, 1, 1, 12)
    cursor = FakeCursor(
        ["TZ", "LTZ", "NTZ", "CLOCK"],
        [(aware, aware, naive, time(12, 4, 3, 123456))],
        description=[("TZ", 7), ("LTZ", 6), ("NTZ", 8), ("CLOCK", 12)],
    )
    batch = list(
        SnowflakeBackend(FakeSnowflakeClient([cursor])).execute_batches(
            "SELECT tz, ltz, ntz, clock FROM facts", timeout_seconds=5
        )
    )[0]
    assert batch.schema.types == [
        pa.timestamp("us", tz="UTC"),
        pa.timestamp("us", tz="UTC"),
        pa.timestamp("us"),
        pa.time64("us"),
    ]
    assert batch.column(0)[0].as_py() == aware
    assert batch.column(2)[0].as_py() == naive


@pytest.mark.parametrize(
    "description",
    [[("VALUE",)], [("VALUE", 999)], [("VALUE", 0, None, None, None, None, True)]],
)
def test_missing_unknown_or_incomplete_type_metadata_fails_explicitly(description):
    cursor = FakeCursor(["VALUE"], [], description=description)
    with pytest.raises(SQLExecutionError, match="metadata|type code|precision"):
        list(
            SnowflakeBackend(FakeSnowflakeClient([cursor])).execute_batches(
                "SELECT value FROM facts", timeout_seconds=5
            )
        )
    assert cursor.closed
