"""Adversarial metadata and execution checks; no LLM or external source needed."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from data_analytics_agent.backends.validation import SQLValidationError
from data_analytics_agent.semantic import (
    SemanticField,
    SemanticMetric,
    SemanticRelationship,
    load_semantic_catalog,
)
from data_analytics_agent.semantic_context import build_semantic_context
from data_analytics_agent.semantic_sql import validate_semantic_sql
from data_analytics_agent.semantic_tools import create_browse_semantic_tool


@pytest.fixture
def catalog():
    return load_semantic_catalog(
        Path("semantic/chinook.osi.yaml"), dialect="sqlite"
    ).catalog


def context(catalog, **kw):
    return build_semantic_context(
        catalog, source_id="test", dialect="sqlite", include_physical=True, **kw
    )


def test_question_discovery_does_not_claim_coverage_or_starve_metrics(catalog):
    for question in (
        "revenue by country",
        "monthly revenue by genre",
        "sales by artist",
    ):
        result = context(catalog, question=question)
        assert result["mode"] == "discovery"
        assert not result["definitions_complete"]
        assert result["question_coverage"] == "requires_selection"
        assert "total_revenue" in {m["name"] for m in result["candidates"]["metric"]}
        assert result["candidates"]["field"]
        assert not result["omissions"]
        assert len(json.dumps(result)) < 12000


def test_explicit_selections_never_claim_question_coverage(catalog):
    result = context(catalog, question="revenue by genre", dataset_names=["invoices"])
    assert result["definitions_complete"]
    assert result["question_coverage"] == "not_assessed"
    assert not result["metrics"]


def test_wide_dataset_automatic_projection(catalog):
    fields = dict(catalog.datasets["invoices"].fields)
    fields.update(
        {
            f"field_{i}": SemanticField(
                f"field_{i}", "Explanation " * 100, f"Column{i}"
            )
            for i in range(100)
        }
    )
    datasets = dict(catalog.datasets)
    datasets["invoices"] = replace(datasets["invoices"], fields=fields)
    wide = replace(catalog, datasets=datasets, content_hash="wide")
    result = context(wide, metric_names=["total_revenue"])
    assert result["definitions_complete"]
    assert {f["name"] for f in result["datasets"][0]["fields"]} == {
        "total",
        "invoice_id",
    }
    assert result["datasets"][0]["omitted_field_count"] == len(fields) - 2


def test_self_relationship_and_exact_route_selection(catalog):
    result = context(catalog, dataset_names=["employees"])
    assert [r["name"] for r in result["relationships"]] == ["employees_to_managers"]
    assert {"employee_id", "reports_to"} <= {
        f["name"] for f in result["datasets"][0]["fields"]
    }
    alternate = SemanticRelationship(
        "alternate", "artists", "albums", ("artist_id",), ("artist_id",)
    )
    adjacency = dict(catalog.adjacency)
    for name in ("artists", "albums"):
        adjacency[name] = (*adjacency[name], alternate)
    revised = replace(
        catalog,
        adjacency=adjacency,
        relationships=(*catalog.relationships, alternate),
        content_hash="alternate-route",
    )
    ambiguous = context(revised, dataset_names=["artists", "albums"])
    assert not ambiguous["definitions_complete"] and ambiguous["blocking_issues"]
    assert not ambiguous[
        "relationships"
    ]  # Candidate routes do not expand into SQL context.
    selected = context(
        revised,
        dataset_names=["artists", "albums"],
        relationship_names=["albums_to_artists"],
    )
    assert selected["definitions_complete"] and not selected["ambiguities"]
    assert [r["name"] for r in selected["relationships"]] == ["albums_to_artists"]


def test_browsing_supports_roles_relationships_examples_and_byte_budget(catalog):
    browse = create_browse_semantic_tool(catalog, include_physical=True)
    assert "total_revenue" in {
        i["name"] for i in browse.func(entity_kind="metric", query="revenue")["items"]
    }
    dates = browse.func(entity_kind="field", dataset_name="invoices", time_only=True)[
        "items"
    ]
    assert [d["name"] for d in dates] == ["invoice_date"]
    assert browse.func(entity_kind="relationship", dataset_name="employees")["items"]
    assert browse.func(entity_kind="example")["items"]
    fields = dict(catalog.datasets["invoices"].fields)
    fields["total"] = replace(fields["total"], description="x" * 15000)
    datasets = dict(catalog.datasets)
    datasets["invoices"] = replace(datasets["invoices"], fields=fields)
    browse = create_browse_semantic_tool(replace(catalog, datasets=datasets))
    result = browse.func(entity_kind="field", dataset_name="invoices", query="total")
    assert len(json.dumps(result)) < 6000
    assert result["omissions"] and not result["items"]


def test_no_relation_metric_rejected(catalog):
    metrics = dict(catalog.metrics, unbound=SemanticMetric("unbound", "", "COUNT(*)"))
    with pytest.raises(ValueError, match="no bound dataset"):
        _ = replace(catalog, metrics=metrics).bindings


def test_logical_field_composition_rejected_explicitly(catalog):
    fields = dict(catalog.datasets["invoices"].fields)
    fields["net_amount"] = SemanticField("net_amount", "", "Total")
    fields["adjusted"] = SemanticField("adjusted", "", "net_amount * 0.9")
    datasets = dict(catalog.datasets)
    datasets["invoices"] = replace(datasets["invoices"], fields=fields)
    with pytest.raises(ValueError, match="logical field composition"):
        _ = replace(catalog, datasets=datasets).bindings


def test_scalar_physical_fields_expand_in_metrics(catalog):
    fields = dict(
        catalog.datasets["invoices"].fields,
        adjusted=SemanticField("adjusted", "", "Total * 0.9"),
    )
    datasets = dict(catalog.datasets)
    datasets["invoices"] = replace(datasets["invoices"], fields=fields)
    metrics = dict(
        catalog.metrics,
        adjusted_revenue=SemanticMetric(
            "adjusted_revenue", "", "SUM(invoices.adjusted)"
        ),
    )
    revised = replace(
        catalog, datasets=datasets, metrics=metrics, content_hash="computed"
    )
    result = context(revised, metric_names=["adjusted_revenue"])
    assert result["definitions_complete"]
    assert result["metrics"][0]["expression"] == "SUM((invoices.Total * 0.9))"
    validate_semantic_sql(
        "SELECT SUM(Total * 0.9) FROM Invoice",
        revised,
        metric_names=["adjusted_revenue"],
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT Name FROM Secret",
        "SELECT Missing FROM Invoice",
        "SELECT * FROM Invoice",
        "SELECT i.Total FROM Invoice i JOIN Customer c ON i.InvoiceId=c.CustomerId",
        "SELECT i.Total FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId OR 1=1",
        "SELECT SUM(i.Total) FROM Invoice i JOIN InvoiceLine l ON i.InvoiceId=l.InvoiceId",
    ],
)
def test_invalid_sql_is_rejected(catalog, query):
    with pytest.raises(SQLValidationError):
        validate_semantic_sql(query, catalog)


def test_canonical_metric_filters_and_explicit_routes(catalog):
    with pytest.raises(SQLValidationError, match="canonical expression"):
        validate_semantic_sql(
            "SELECT AVG(Total) FROM Invoice", catalog, metric_names=["total_revenue"]
        )
    with pytest.raises(SQLValidationError, match="selected declared relationships"):
        validate_semantic_sql(
            "SELECT c.Country FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId",
            catalog,
            relationship_names=[],
        )


def test_transparent_cte_and_self_join(catalog):
    validate_semantic_sql(
        "WITH x AS (SELECT ArtistId AS id FROM Artist) SELECT x.id, a.Title FROM x JOIN Album a ON x.id=a.ArtistId",
        catalog,
    )
    validate_semantic_sql(
        "SELECT e.FirstName, m.FirstName FROM Employee e LEFT JOIN Employee m ON e.ReportsTo=m.EmployeeId",
        catalog,
        relationship_names=["employees_to_managers"],
    )


def test_correct_line_revenue_has_correct_result_at_requested_grain(catalog):
    query = """SELECT g.Name, SUM(l.UnitPrice*l.Quantity) AS revenue
    FROM InvoiceLine l JOIN Track t ON l.TrackId=t.TrackId
    JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.Name"""
    validate_semantic_sql(query, catalog, metric_names=["line_revenue"])
    with sqlite3.connect(":memory:") as db:
        db.executescript("""CREATE TABLE InvoiceLine(TrackId, UnitPrice, Quantity);
        CREATE TABLE Track(TrackId, GenreId); CREATE TABLE Genre(GenreId, Name);
        INSERT INTO Genre VALUES(1,'Rock'),(2,'Jazz');
        INSERT INTO Track VALUES(1,1),(2,1),(3,2);
        INSERT INTO InvoiceLine VALUES(1,2,3),(2,5,2),(3,7,1);""")
        assert dict(db.execute(query)) == {"Rock": 16, "Jazz": 7}


def test_loader_preserves_context_and_rejects_invalid_metric(tmp_path):
    document = yaml.safe_load(Path("semantic/chinook.osi.yaml").read_text())
    model = document["semantic_model"][0]
    model["datasets"][0]["ai_context"] = "Use curated artist identity."
    model["metrics"][0]["ai_context"]["examples"] = ["Monthly invoice revenue"]
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(document))
    loaded = load_semantic_catalog(path, dialect="sqlite")
    assert (
        loaded.catalog.datasets["artists"].instructions
        == "Use curated artist identity."
    )
    assert loaded.catalog.metrics["total_revenue"].examples == (
        "Monthly invoice revenue",
    )
    model["metrics"][0]["expression"]["dialects"][0]["expression"] = "COUNT(*)"
    path.write_text(yaml.safe_dump(document))
    invalid = load_semantic_catalog(path, dialect="sqlite")
    assert (
        invalid.catalog is None and "no bound dataset" in invalid.diagnostics.errors[0]
    )


def test_correlated_and_membership_filters_use_declared_keys(catalog):
    validate_semantic_sql(
        "SELECT i.Total FROM Invoice i WHERE EXISTS (SELECT 1 FROM Customer c WHERE c.CustomerId=i.CustomerId)",
        catalog,
    )
    validate_semantic_sql(
        "SELECT i.Total FROM Invoice i WHERE i.CustomerId IN (SELECT c.CustomerId FROM Customer c)",
        catalog,
    )
    for query in [
        "SELECT i.Total FROM Invoice i WHERE EXISTS (SELECT 1 FROM Customer c WHERE c.CustomerId=i.InvoiceId)",
        "SELECT i.Total FROM Invoice i WHERE i.InvoiceId IN (SELECT c.CustomerId FROM Customer c)",
    ]:
        with pytest.raises(SQLValidationError):
            validate_semantic_sql(query, catalog)


def test_multihop_fanout_and_duplicated_cte_keys_rejected(catalog):
    for query in [
        """SELECT SUM(l.UnitPrice*l.Quantity) FROM InvoiceLine l
        JOIN Track t ON l.TrackId=t.TrackId
        JOIN PlaylistTrack p ON p.TrackId=t.TrackId""",
        """WITH c AS (SELECT c.CustomerId FROM Customer c
        JOIN Invoice i ON c.CustomerId=i.CustomerId)
        SELECT SUM(i.Total) FROM Invoice i JOIN c ON i.CustomerId=c.CustomerId""",
    ]:
        with pytest.raises(SQLValidationError, match="fan out"):
            validate_semantic_sql(query, catalog)


def test_preaggregated_key_preserves_invoice_grain(catalog):
    query = """WITH lines AS (SELECT InvoiceId, COUNT(*) AS n FROM InvoiceLine GROUP BY InvoiceId)
    SELECT SUM(i.Total) FROM Invoice i JOIN lines l ON l.InvoiceId=i.InvoiceId"""
    validate_semantic_sql(query, catalog, metric_names=["total_revenue"])


def test_source_tool_checks_sql_before_execution_including_reviewed_edits(
    workspace, test_settings
):
    from langchain_core.tools import ToolException

    from data_analytics_agent.agents.text_to_sql.tools import create_execute_sql_tool

    source = test_settings.load_catalog().get("test")
    catalog = load_semantic_catalog(
        source.semantic_model_path, dialect="sqlite"
    ).catalog

    class NoExecution:
        def execute_batches(self, *args, **kwargs):
            raise AssertionError("Ungrounded SQL reached the backend")

    tool = create_execute_sql_tool(
        source, NoExecution(), workspace.results, workspace.runs, catalog=catalog
    )
    # The tool receives the final argument, including any approval-stage edit.
    with pytest.raises(ToolException, match="Undeclared physical source"):
        tool.func(
            query="SELECT Name FROM Undeclared",
            purpose="Reviewed query",
            runtime=workspace.runtime("invalid-edit"),
        )


def test_computed_field_expansion_preserves_operator_precedence(catalog):
    fields = dict(catalog.datasets["invoice_lines"].fields)
    fields["adjusted"] = SemanticField("adjusted", "", "UnitPrice + 1")
    datasets = dict(catalog.datasets)
    datasets["invoice_lines"] = replace(datasets["invoice_lines"], fields=fields)
    metrics = dict(
        catalog.metrics,
        adjusted=SemanticMetric(
            "adjusted", "", "SUM(invoice_lines.adjusted * invoice_lines.Quantity)"
        ),
    )
    revised = replace(catalog, datasets=datasets, metrics=metrics)
    assert (
        revised.bindings.metrics["adjusted"].expression
        == "SUM((invoice_lines.UnitPrice + 1) * invoice_lines.Quantity)"
    )
    validate_semantic_sql(
        "SELECT SUM((UnitPrice + 1) * Quantity) FROM InvoiceLine",
        revised,
        metric_names=["adjusted"],
    )
    with pytest.raises(SQLValidationError, match="canonical expression"):
        validate_semantic_sql(
            "SELECT SUM(UnitPrice + 1 * Quantity) FROM InvoiceLine",
            revised,
            metric_names=["adjusted"],
        )


def test_computed_field_retains_operand_semantic_instructions(catalog):
    fields = dict(catalog.datasets["invoices"].fields)
    fields["total"] = replace(
        fields["total"], instructions="Declared source units; do not invent currency."
    )
    fields["adjusted"] = SemanticField("adjusted", "", "Total * 0.9")
    datasets = dict(catalog.datasets)
    datasets["invoices"] = replace(datasets["invoices"], fields=fields)
    revised = replace(catalog, datasets=datasets, content_hash="operand-instructions")
    result = context(revised, field_names={"invoices": ["adjusted"]})
    selected = {f["name"]: f for f in result["datasets"][0]["fields"]}
    assert (
        selected["total"]["instructions"]
        == "Declared source units; do not invent currency."
    )


def test_aggregate_populations_can_join_on_same_unique_dimension(catalog):
    query = """WITH a AS (SELECT CustomerId, SUM(Total) AS revenue FROM Invoice GROUP BY CustomerId),
    b AS (SELECT CustomerId, COUNT(*) AS orders FROM Invoice GROUP BY CustomerId)
    SELECT a.CustomerId, a.revenue, b.orders FROM a JOIN b ON a.CustomerId=b.CustomerId"""
    validate_semantic_sql(query, catalog, metric_names=["total_revenue"])


def test_unused_cte_cannot_satisfy_selected_metric(catalog):
    query = """WITH unused AS (SELECT SUM(Total) AS revenue FROM Invoice)
    SELECT AVG(Total) FROM Invoice"""
    with pytest.raises(SQLValidationError, match="canonical expression"):
        validate_semantic_sql(query, catalog, metric_names=["total_revenue"])


def test_composite_relationship_requires_all_keys(catalog):
    relation = SemanticRelationship(
        "composite",
        "invoices",
        "customers",
        ("invoice_id", "customer_id"),
        ("customer_id", "support_rep_id"),
    )
    revised = replace(catalog, relationships=(relation,))
    with pytest.raises(SQLValidationError, match="selected declared relationships"):
        validate_semantic_sql(
            "SELECT i.Total FROM Invoice i JOIN Customer c ON i.InvoiceId=c.CustomerId",
            revised,
        )
    validate_semantic_sql(
        "SELECT i.Total FROM Invoice i JOIN Customer c ON i.InvoiceId=c.CustomerId AND i.CustomerId=c.SupportRepId",
        revised,
    )


def test_empty_discovery_is_repairable(catalog):
    result = context(catalog, question="!!!")
    assert not result["definitions_complete"] and result["blocking_issues"]


def test_financial_metric_keeps_embedded_business_filters():
    catalog = load_semantic_catalog(
        Path("semantic/financial.osi.yaml"), dialect="sqlite"
    ).catalog
    validate_semantic_sql(
        "SELECT SUM(CASE WHEN type = 'PRIJEM' THEN amount ELSE 0 END) FROM trans",
        catalog,
        metric_names=["transaction_inflow"],
    )
    with pytest.raises(SQLValidationError, match="canonical expression"):
        validate_semantic_sql(
            "SELECT SUM(amount) FROM trans",
            catalog,
            metric_names=["transaction_inflow"],
        )
