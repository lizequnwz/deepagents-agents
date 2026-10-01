"""Source discovery keeps assignment identity, evidence, and replay boundaries."""

import sqlite3

import pytest

from data_analytics_agent.backends.sqlite import SQLiteBackend
from data_analytics_agent.handoff import AssignmentMiddleware
from data_analytics_agent.persistence import LocalStorage
from data_analytics_agent.semantic import load_semantic_catalog
from data_analytics_agent.semantic_tools import create_lookup_values_tool
from data_analytics_agent.stores import ResultStore, RunStore


@pytest.fixture
def lookup_source(test_settings):
    source = test_settings.load_catalog().get("test")
    database = test_settings.project_root / source.target["path"]
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO Artist (Name) VALUES (?)",
            [("Alpha",), ("Alpha",), ("Beta",)],
        )
    catalog = load_semantic_catalog(
        source.semantic_model_path, dialect=source.dialect
    ).catalog

    class CountingBackend(SQLiteBackend):
        calls = 0

        def execute_batches(self, *args, **kwargs):
            self.calls += 1
            return super().execute_batches(*args, **kwargs)

    return catalog, source, CountingBackend(database)


def test_lookup_replay_isolates_assignments_and_preserves_receipts(
    workspace, lookup_source
):
    w = workspace
    catalog, source, backend = lookup_source
    lookup = create_lookup_values_tool(catalog, source, backend, w.results, w.runs)
    runtime = w.runtime("same-call")
    w.runs.begin_assignment(w.run, "alpha", "text-to-sql", "Find Alpha")
    runtime.state["assignment_id"] = "alpha"
    first = lookup.func(
        dataset_name="artists", field_name="name", search="Alpha", runtime=runtime
    )
    assert first["sample_rows"] == [{"value": "Alpha", "frequency": 2}]
    assert lookup.func(
        dataset_name="artists", field_name="name", search="Alpha", runtime=runtime
    ) == first

    w.runs.begin_assignment(w.run, "beta", "text-to-sql", "Find Beta")
    runtime.state["assignment_id"] = "beta"
    second = lookup.func(
        dataset_name="artists", field_name="name", search="Beta", runtime=runtime
    )
    assert second["sample_rows"] == [{"value": "Beta", "frequency": 1}]
    assert second["result_id"] != first["result_id"]
    assert backend.calls == 2

    reopened = LocalStorage(w.storage.root)
    runs, results = RunStore(reopened), ResultStore(reopened)
    restarted_lookup = create_lookup_values_tool(catalog, source, backend, results, runs)
    assert restarted_lookup.func(
        dataset_name="artists", field_name="name", search="Beta", runtime=runtime
    ) == second
    assert backend.calls == 2
    assert len(results.list_for_conversation(w.thread, source_id="test")) == 2

    continuation = runs.continuation(w.run)
    saved = {
        a["brief"]: a["result"]["datasets"] for a in continuation["assignments"]
    }
    assert saved["Find Alpha"][0]["result_id"] == first["result_id"]
    assert saved["Find Beta"][0]["result_id"] == second["result_id"]
    receipt = AssignmentMiddleware(runs, "text-to-sql").after_agent(
        {**runtime.state, "structured_response": {"answer": "Beta exists."}}, None
    )["structured_response"]
    assert receipt["datasets"] == saved["Find Beta"]
    assert receipt["datasets"][0]["label"] == "Value lookup: artists.name"


@pytest.mark.parametrize("require_approval", [False, True])
def test_lookup_rejects_wrong_source_before_execution_or_replay(
    workspace, lookup_source, require_approval
):
    w = workspace
    catalog, source, backend = lookup_source
    runtime = w.runtime("lookup")
    w.storage.commit(w.run, "test-assignment:lookup", '{"result_id": "other"}')
    runtime.state["source_id"] = "test_alt"
    lookup = create_lookup_values_tool(
        catalog, source, backend, w.results, w.runs, require_approval=require_approval
    )
    with pytest.raises(ValueError, match="Source mismatch"):
        lookup.func(dataset_name="artists", field_name="name", runtime=runtime)
    assert backend.calls == 0
    assert not w.results.list_for_conversation(w.thread, source_id="test")
    assert not w.runs.assignment(w.run, "test-assignment").datasets
