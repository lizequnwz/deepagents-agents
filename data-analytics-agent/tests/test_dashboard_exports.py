"""Parameterized dashboard calculations retain portable, exact provenance."""

import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from data_analytics_agent.api import create_app
from data_analytics_agent.exports import write_bundle
from tests.test_dashboard_execution import (
    assert_no_source_work,
    fixed_dashboard as fixed_dashboard,
    submit,
)


def test_filtered_export_keeps_query_definition_and_typed_parameters(fixed_dashboard, tmp_path):
    w = fixed_dashboard
    with TestClient(create_app(w.services)) as client:
        run_id = submit(w, client, ["South"])
        answer = w.services.runs.get(run_id).answer
        path = tmp_path / "filtered.zip"
        write_bundle(w.services, run_id, answer.report.report_id, path)
    with ZipFile(path) as archive:
        queries = json.loads(archive.read("sql-provenance.json"))
        filtered = [query for query in queries if query["dashboard_query"]]
        assert len(filtered) == 2
        for query in filtered:
            assert query["parameters"] == {"p0": "South"}
            assert "$p0" in query["query"] and "South" not in query["query"]
            receipt = query["dashboard_query"]
            assert receipt["filter_values"] == {"region": ["South"]}
            assert receipt["definition"]["input_result_id"] == w.population.result_id
        manifest = json.loads(archive.read("manifest.json"))
        for query in filtered:
            saved = manifest["datasets"][query["result_id"]]
            assert saved["dashboard_query"] == query["dashboard_query"]
    assert_no_source_work(w)


def test_export_refuses_a_changed_parameter_receipt(fixed_dashboard, tmp_path):
    w = fixed_dashboard
    with TestClient(create_app(w.services)) as client:
        run_id = submit(w, client, ["South"])
        answer = w.services.runs.get(run_id).answer
        result_id = answer.results[0].result_id
        receipt = w.services.storage.get("dashboard_queries", result_id, dict)
        receipt["parameters"] = {"p0": "North"}
        w.services.storage.put("dashboard_queries", result_id, receipt)
        with pytest.raises(ValueError, match="receipt"):
            write_bundle(w.services, run_id, answer.report.report_id, tmp_path / "changed.zip")
