from __future__ import annotations


from data_analytics_agent.backends import (
    ColumnInfo,
    TableInfo,
    validate_readonly_sql,
)
from data_analytics_agent.config import Settings
from data_analytics_agent.agents.text_to_sql.tools import execute_query
from data_analytics_agent.stores import ResultStore


class FakeClientBackend:
    """Contract double shaped like a future injected cloud-client adapter."""

    dialect = "sqlite"
    backend_type = "fake-client"

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_batches(self, query, *, timeout_seconds, cancel=None):
        import pyarrow as pa

        validate_readonly_sql(query, dialect=self.dialect)
        self.executed.append(query)
        yield pa.record_batch({"value": range(10001)})

    def get_table_schema(self, table_names: list[str]) -> list[TableInfo]:
        assert table_names == ["facts"]
        return [
            TableInfo(
                name="facts",
                columns=(
                    ColumnInfo(
                        name="value",
                        data_type="NUMBER",
                        nullable=False,
                        primary_key=True,
                    ),
                ),
            )
        ]


def test_execute_query_accepts_dependency_injected_backend(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    backend = FakeClientBackend()
    store = ResultStore()
    query = "SELECT value FROM facts"

    result = execute_query(
        backend=backend,
        source=source,
        query=query,
        thread_id="thread-1",
        result_store=store,
        originating_question="Show all values",
    )

    assert backend.executed == [query]
    assert result.executed_sql == query
    assert result.truncated is True
    saved = store.get(
        result.result_id,
        "thread-1",
        source_id="test",
    )
    assert saved.source_id == "test"
    assert saved.rows[: source.limits.model_sample_rows] == result.sample_rows
    assert result.profile == saved.profile
    assert saved.originating_question == "Show all values"
