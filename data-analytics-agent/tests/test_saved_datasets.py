"""Saved evidence remains inspectable without application-selected populations."""

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from data_analytics_agent.api import Services, create_app
from tests.test_persistent_analyst import save
from tests.test_run_manager import Graph


def test_empty_reader_rejects_duplicate_column_aliases(workspace):
    schema = pa.schema([("same", pa.int64()), ("same", pa.int64())])
    reader = pa.RecordBatchReader.from_batches(schema, [])
    with pytest.raises(ValueError, match="unique aliases|duplicate"):
        workspace.results.save_batches(
            reader, thread_id=workspace.thread, source_id="test"
        )


def test_saved_sql_rejects_aliases_that_only_differ_by_case(workspace):
    from langchain_core.tools import ToolException
    from data_analytics_agent.agents.text_to_sql.tools import (
        create_query_saved_results_tool,
    )

    w = workspace
    left = save(w, [{"amount": 10}])
    right = save(w, [{"amount": 100}])
    with pytest.raises(ToolException, match="aliases.*unique"):
        create_query_saved_results_tool(w.results, w.runs, source_id="test").func(
            query='SELECT amount FROM "Snapshot"',
            bindings={"Snapshot": left.result_id, "snapshot": right.result_id},
            purpose="Distinct saved inputs",
            runtime=w.runtime("case-collision"),
        )


def test_dataset_list_preserves_evidence_and_conversation_source_isolation(
    workspace, test_settings
):
    w = workspace
    base = save(w, [{"region": "West"}, {"region": "East"}])
    incomplete = save(w, [{"region": "West"}], truncated=True)
    presentation = save(
        w, [{"region": "West"}], kind="presentation", parent_result_ids=[base.result_id]
    )
    other = w.conversations.create("test")
    w.results.save(
        columns=["region"],
        rows=[{"region": "Private"}],
        thread_id=other,
        source_id="test",
    )
    w.results.save(
        columns=["region"],
        rows=[{"region": "Other source"}],
        thread_id=w.thread,
        source_id="test_alt",
    )
    services = Services(
        settings=test_settings,
        conversations=w.conversations,
        results=w.results,
        runs=w.runs,
        analyses=w.analyses,
        reports=w.reports,
        agent=Graph([]),
    )
    with TestClient(create_app(services)) as api:
        response = api.get(f"/api/conversations/{w.thread}/datasets")
        assert response.status_code == 200
        available = response.json()["datasets"]
        assert [item["result_id"] for item in available] == [
            presentation.result_id,
            incomplete.result_id,
            base.result_id,
        ]
        assert available[0]["parent_result_ids"] == [base.result_id]
        assert available[1]["complete"] is False
        assert api.get(f"/api/results/{base.result_id}").status_code == 200
        assert api.get(f"/api/results/{base.result_id}/download").status_code == 200
