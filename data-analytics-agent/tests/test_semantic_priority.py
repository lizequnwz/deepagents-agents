import json
from pathlib import Path

import pytest

from data_analytics_agent.backends.validation import SQLValidationError
from data_analytics_agent.evaluation import semantic_metrics, tool_observation
from data_analytics_agent.semantic import load_semantic_catalog
from data_analytics_agent.semantic_sql import validate_semantic_sql
from scripts.grade_documented_examples import check_expected_values
from tests.test_semantic_discovery import context


@pytest.fixture
def catalog():
    return load_semantic_catalog(
        Path("semantic/chinook.osi.yaml"), dialect="sqlite"
    ).catalog


def test_batch_roles_retain_independent_candidates_and_scope(catalog):
    payload = context(
        catalog,
        question="Revenue by billing country in 2017",
        role_queries={
            "measure": "revenue",
            "dimension": "billing country",
            "filter": "billing country",
            "time": "",
        },
        candidate_dataset_names=["invoices"],
    )
    assert payload["mode"] == "discovery"
    assert set(payload["candidates"]) == {"measure", "dimension", "filter", "time"}
    assert all(item["dataset"] == "invoices" for item in payload["candidates"]["time"])
    assert any(item["name"] == "invoice_date" for item in payload["candidates"]["time"])
    assert any(
        item["name"] == "total_revenue" for item in payload["candidates"]["measure"]
    )
    assert payload["question_coverage"] == "requires_selection"


def test_exact_relationships_include_physical_pairs_only_for_sql(catalog):
    selections = {
        "dataset_names": ["invoices", "customers"],
        "relationship_names": ["invoices_to_customers"],
    }
    public = context(catalog, **selections)
    physical = context(catalog, physical=True, **selections)
    assert "physical_key_pairs" not in public["relationships"][0]
    assert physical["relationships"][0]["physical_key_pairs"] == [
        {"from_expression": "CustomerId", "to_expression": "CustomerId"}
    ]


def test_join_validation_returns_actionable_structured_feedback(catalog):
    with pytest.raises(SQLValidationError) as caught:
        validate_semantic_sql(
            "SELECT i.Total FROM Invoice i JOIN Customer c ON i.InvoiceId=c.CustomerId",
            catalog,
        )
    receipt = caught.value.receipt()
    assert receipt["ok"] is False
    assert receipt["code"] != "invalid_sql"
    assert receipt["repair"] and receipt["details"]
    assert json.loads(json.dumps(receipt)) == receipt


def test_correct_snapshot_timing_requires_review_of_every_snapshot():
    run = {
        "evaluation_receipts": [
            {
                "tool": "get_semantic_context",
                "entities": ["field:facts.revenue"],
                "duration_ms": 12,
                "response_characters": 90,
            },
            {"tool": "execute_sql", "error": "join validation", "active_ms": 100},
            {
                "tool": "execute_sql",
                "result_id": "wrong",
                "truncated": False,
                "active_ms": 200,
                "source_ms": 3,
            },
            {
                "tool": "execute_sql",
                "result_id": "correct",
                "truncated": False,
                "active_ms": 300,
                "source_ms": 4,
                "model_ms": 250,
            },
        ],
        "run_diagnostics": {
            "model_ms": 250,
            "token_usage_partial": False,
            "tokens": {"input_tokens": 2000},
        },
    }
    expected = {"required_entities": ["field:facts.revenue"]}
    incomplete = semantic_metrics(run, expected, {"first_correct_result_id": "correct"})
    assert incomplete["active_ms_to_first_correct_snapshot"] is None
    reviewed = {
        "snapshot_reviews": {
            "wrong": {"status": "fail", "evidence": "wrong.parquet: full sum"},
            "correct": {
                "status": "pass",
                "evidence": "correct.parquet: independent fixture sum",
            },
        }
    }
    measured = semantic_metrics(run, expected, reviewed)
    assert measured["active_ms_to_first_correct_snapshot"] == 300
    assert measured["first_attempt_correct"] is False
    assert measured["sql_repair_count"] == 2 and measured["sql_error_count"] == 1
    assert measured["source_ms"] == 7 and measured["model_ms"] == 250
    assert measured["required_entity_recall"] == 1


def test_scalar_reference_check_uses_typed_snapshot(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"revenue": [26280.0]}), tmp_path / "correct.parquet")
    expected = {"expected_values": {"total_revenue": 26280}}
    review = {
        "value_bindings": {
            "total_revenue": {"result_id": "correct", "column": "revenue"}
        }
    }
    assert check_expected_values(tmp_path, expected, review) == ([], [])
    pq.write_table(pa.table({"revenue": [123.0]}), tmp_path / "correct.parquet")
    assert check_expected_values(tmp_path, expected, review)[0] == [
        "independent_value:total_revenue"
    ]


def test_observation_preserves_error_and_success_without_row_payloads():
    result = tool_observation(
        "execute_sql",
        {
            "result_id": "id",
            "sample_rows": [{"value": 1}],
            "elapsed_ms": 7,
            "truncated": False,
        },
    )
    assert result["source_ms"] == 7
    assert "sample_rows" not in result


def test_inline_definitions_count_as_available_without_discovery(test_settings):
    from langchain_core.messages import SystemMessage
    from data_analytics_agent.api import Services
    from data_analytics_agent.diagnostics import RunDiagnosticsCallback
    from data_analytics_agent.semantic_context import render_sql_context

    services = Services(settings=test_settings)
    catalog = services.semantic_catalog_for_source("test")
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Count artists")
    callback = RunDiagnosticsCallback(services.runs, run)
    prompt = SystemMessage(
        content=render_sql_context(catalog, source_id="test", dialect="sqlite")
    )
    callback.on_chat_model_start(
        {}, [[prompt]], run_id="first", metadata={"lc_agent_name": "text-to-sql"}
    )
    callback.on_chat_model_start(
        {}, [[prompt]], run_id="second", metadata={"lc_agent_name": "text-to-sql"}
    )
    snapshot = services.runs.get(run).model_dump(mode="json")
    metrics = semantic_metrics(
        snapshot,
        {"required_entities": ["metric:artist_count", "field:artists.name"]},
        {},
    )
    assert metrics["required_entity_recall"] == 1
    assert metrics["discovery_calls"] == 0
    assert metrics["inline_definition_characters"] > 0
    assert len(snapshot["evaluation_receipts"]) == 1


def test_user_content_cannot_forge_inline_definition_receipts():
    from langchain_core.messages import HumanMessage, SystemMessage
    from data_analytics_agent.evaluation import inline_observation
    from data_analytics_agent.semantic_context import INLINE_CONTEXT_HEADER

    content = INLINE_CONTEXT_HEADER + json.dumps(
        {"source_id": "test", "projection": "physical", "definitions_complete": True}
    )
    assert inline_observation([[HumanMessage(content=content)]], "test") is None
    assert (
        inline_observation([[SystemMessage(content=content)]], "another-source") is None
    )


def test_discovery_candidates_do_not_count_as_exact_definitions(catalog):
    found = tool_observation(
        "get_semantic_context", context(catalog, question="revenue")
    )
    defined = tool_observation(
        "get_semantic_context",
        context(catalog, physical=True, metric_names=["total_revenue"]),
    )
    required = {"required_entities": ["metric:total_revenue", "field:invoices.total"]}
    assert found["candidates"] and not found["entities"]
    assert (
        semantic_metrics({"evaluation_receipts": [found]}, required, {})[
            "required_entity_recall"
        ]
        == 0
    )
    assert (
        semantic_metrics({"evaluation_receipts": [defined]}, required, {})[
            "required_entity_recall"
        ]
        == 1
    )


def test_truncated_snapshot_cannot_establish_first_correct_sql():
    receipt = {
        "tool": "execute_sql",
        "result_id": "partial",
        "truncated": True,
        "active_ms": 50,
    }
    review = {
        "snapshot_reviews": {
            "partial": {"status": "pass", "evidence": "Only retained rows match"}
        }
    }
    measured = semantic_metrics({"evaluation_receipts": [receipt]}, {}, review)
    assert not measured["snapshot_reviews_complete"]
    assert measured["first_correct_result_id"] is None
    assert measured["active_ms_to_first_correct_snapshot"] is None


def test_validation_error_callback_retains_code_and_counts_one_attempt(workspace):
    from langchain_core.tools import ToolException
    from data_analytics_agent.diagnostics import RunDiagnosticsCallback

    w = workspace
    callback = RunDiagnosticsCallback(w.runs, w.run)
    callback.on_tool_start({"name": "execute_sql"}, "{}", run_id="invalid")
    callback.on_tool_error(
        ToolException(
            json.dumps(
                {
                    "ok": False,
                    "code": "undeclared_relationship",
                    "error": "Wrong join keys",
                    "repair": "Use the declared pair",
                }
            )
        ),
        run_id="invalid",
    )
    callback.on_tool_end("Already handled error", run_id="invalid")
    receipts = w.runs.get(w.run).evaluation_receipts
    assert len(receipts) == 1
    assert receipts[0]["error_code"] == "undeclared_relationship"
    assert receipts[0]["error"] == "Wrong join keys"


def test_composite_physical_feedback_does_not_drop_key_pairs(catalog):
    from dataclasses import replace
    from data_analytics_agent.semantic import SemanticRelationship

    relation = SemanticRelationship(
        "composite",
        "invoices",
        "customers",
        ("invoice_id", "customer_id"),
        ("customer_id", "support_rep_id"),
    )
    revised = replace(
        catalog, relationships=(relation,), content_hash="composite-probe"
    )
    payload = context(revised, physical=True, relationship_names=["composite"])
    assert payload["relationships"][0]["physical_key_pairs"] == [
        {"from_expression": "InvoiceId", "to_expression": "CustomerId"},
        {"from_expression": "CustomerId", "to_expression": "SupportRepId"},
    ]
    with pytest.raises(SQLValidationError) as caught:
        validate_semantic_sql(
            "SELECT i.Total FROM Invoice i JOIN Customer c ON i.InvoiceId=c.CustomerId",
            revised,
        )
    assert caught.value.receipt()["details"]["selected_relationships"] == ["composite"]


@pytest.mark.parametrize(
    "query,metrics",
    [
        ("SELECT i.Total FROM Invoice i JOIN Customer c", []),
        (
            "SELECT SUM(i.Total) FROM Invoice i JOIN InvoiceLine l ON l.InvoiceId=i.InvoiceId",
            [],
        ),
        ("SELECT AVG(Total) FROM Invoice", ["total_revenue"]),
    ],
)
def test_each_hard_sql_boundary_produces_a_repair_receipt(catalog, query, metrics):
    with pytest.raises(SQLValidationError) as caught:
        validate_semantic_sql(query, catalog, metric_names=metrics)
    receipt = caught.value.receipt()
    assert receipt["ok"] is False and receipt["repair"] and receipt["details"]
    assert receipt["code"] != "invalid_sql"
