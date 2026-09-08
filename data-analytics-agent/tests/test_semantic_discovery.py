from __future__ import annotations

from pathlib import Path

import pytest

from data_analytics_agent.api import Services
from data_analytics_agent.config import Settings
from data_analytics_agent.semantic import (
    SEMANTIC_OVERVIEW_MAX_CHARS,
    SemanticCatalog,
    load_semantic_catalog,
    render_semantic_overview,
)
from data_analytics_agent.semantic_tools import create_semantic_context_tool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHINOOK_PATH = PROJECT_ROOT / "semantic" / "chinook.osi.yaml"


def _chinook_catalog() -> SemanticCatalog:
    loaded = load_semantic_catalog(CHINOOK_PATH, dialect="sqlite")
    assert loaded.diagnostics.errors == ()
    assert loaded.catalog is not None
    return loaded.catalog


def context(catalog, *, physical=False, **kwargs):
    return create_semantic_context_tool(
        catalog,
        source_id="test",
        dialect="sqlite",
        include_physical=physical,
    ).invoke({"question": "", **kwargs})


def test_catalog_retains_complete_immutable_osi_structure() -> None:
    catalog = _chinook_catalog()

    assert catalog.name == "chinook_music_store"
    assert len(catalog.datasets) == 11
    assert catalog.field_count == 64
    assert len(catalog.metrics) == 6
    assert len(catalog.relationships) == 11
    assert len(catalog.content_hash) == 64
    assert catalog.datasets["invoices"].fields["invoice_date"].is_time
    assert "Do not sum Total" in catalog.datasets["invoices"].instructions
    assert catalog.metrics["total_revenue"].expression == "SUM(invoices.Total)"
    with pytest.raises(TypeError):
        catalog.datasets["new"] = catalog.datasets["invoices"]  # type: ignore[index]


def test_content_hash_changes_with_model_revision(tmp_path: Path) -> None:
    original = CHINOOK_PATH.read_bytes()
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_bytes(original)
    second_path.write_bytes(original + b"\n")

    first = load_semantic_catalog(first_path, dialect="sqlite").catalog
    second = load_semantic_catalog(second_path, dialect="sqlite").catalog

    assert first is not None and second is not None
    assert first.content_hash != second.content_hash


def test_overview_is_business_facing_and_bounded(tmp_path: Path) -> None:
    datasets = "\n".join(
        f"""\
      - name: dataset_{index:03d}
        source: Table{index:03d}
        primary_key: [id]
        description: Dataset {index:03d} with a useful business description.
        fields:
          - name: id
            expression: {{dialects: [{{dialect: ANSI_SQL, expression: Id}}]}}
            description: Identifier.
"""
        for index in range(200)
    )
    model_path = tmp_path / "large.osi.yaml"
    model_path.write_text(
        """\
version: "0.1.1"
semantic_model:
  - name: large_model
    description: Large synthetic model.
    datasets:
"""
        + datasets
        + "    relationships: []\n    metrics: []\n",
        encoding="utf-8",
    )
    catalog = load_semantic_catalog(model_path, dialect="sqlite").catalog
    assert catalog is not None

    overview = render_semantic_overview(catalog)

    assert len(overview) <= SEMANTIC_OVERVIEW_MAX_CHARS
    assert "200 datasets" in overview
    assert "additional datasets omitted" in overview
    assert "source: Table" not in overview
    assert "expression:" not in overview
    disconnected = context(catalog, dataset_names=["dataset_000", "dataset_199"])
    assert disconnected["disconnected"] == [["dataset_000", "dataset_199"]]
    assert not disconnected["unresolved_references"]


def test_search_is_deterministic_bounded_and_filterable() -> None:
    catalog = _chinook_catalog()

    exact = catalog.search("total_revenue")
    first = catalog.search("revenue by country", limit=5)
    second = catalog.search("revenue by country", limit=5)
    metrics = catalog.search("revenue", entity_kinds=["metric"], limit=1)

    assert exact[0].kind == "metric"
    assert exact[0].name == "total_revenue"
    assert exact[0].match_reason == "exact_name"
    assert first == second
    assert len(first) == 5
    assert metrics[0].kind == "metric"
    assert metrics[0].match_reason == "exact_synonym"
    with pytest.raises(ValueError, match="between 1 and 25"):
        catalog.search("revenue", limit=26)


def test_context_includes_metric_dependencies_and_role_projection():
    catalog = _chinook_catalog()
    business = context(catalog, metric_names=["total_revenue"])
    sql = context(catalog, physical=True, metric_names=["total_revenue"])
    assert sql["complete"]
    assert sql["datasets"][0]["name"] == "invoices"
    assert sql["datasets"][0]["source"] == "Invoice"
    assert sql["metrics"][0]["expression"] == "SUM(invoices.Total)"
    assert "source" not in business["datasets"][0]
    assert "expression" not in business["metrics"][0]
    assert "expression" not in business["datasets"][0]["fields"][0]


def test_context_includes_bridge_definitions_and_keys():
    result = context(
        _chinook_catalog(), physical=True, dataset_names=["artists", "invoices"]
    )
    assert result["complete"]
    assert {d["name"] for d in result["datasets"]} == {
        "artists",
        "invoices",
        "albums",
        "tracks",
        "invoice_lines",
    }
    assert len(result["relationships"]) == 4
    assert not result["disconnected"]


def test_context_invalid_names_are_repairable():
    result = context(_chinook_catalog(), dataset_names=["Invoice"])
    assert not result["complete"]
    assert "invoices" in result["alternatives"]["datasets"]
    result = context(
        _chinook_catalog(),
        dataset_names=["invoices"],
        field_names={"invoices": ["InvoiceId"]},
    )
    assert not result["complete"]
    assert "logical names" in result["unresolved_references"][0]


def test_context_budget_never_splits_required_definitions():
    from data_analytics_agent.semantic_context import build_semantic_context
    import json

    result = build_semantic_context(
        _chinook_catalog(),
        source_id="test",
        dialect="sqlite",
        include_physical=True,
        full=True,
        budget=1000,
    )
    assert len(json.dumps(result)) <= 1000
    assert not result["complete"] and result["omissions"]
    assert result["datasets"] == []


def test_context_cache_is_version_source_dialect_and_projection_bound():
    from dataclasses import replace
    from data_analytics_agent.semantic_context import build_semantic_context

    catalog = _chinook_catalog()
    first = build_semantic_context(
        catalog,
        source_id="a",
        dialect="sqlite",
        include_physical=True,
        metric_names=["total_revenue"],
    )
    revised = replace(
        catalog, content_hash="new", instructions="Revised business policy"
    )
    second = build_semantic_context(
        revised,
        source_id="a",
        dialect="sqlite",
        include_physical=True,
        metric_names=["total_revenue"],
    )
    assert first["model_hash"] != second["model_hash"]
    assert second["instructions"] == "Revised business policy"
    third = build_semantic_context(
        catalog,
        source_id="b",
        dialect="duckdb",
        include_physical=False,
        metric_names=["total_revenue"],
    )
    assert third["source_id"] == "b" and third["dialect"] == "duckdb"
    assert "expression" not in third["metrics"][0]
    first["datasets"].clear()
    assert build_semantic_context(
        catalog,
        source_id="a",
        dialect="sqlite",
        include_physical=True,
        metric_names=["total_revenue"],
    )["datasets"]


def test_small_catalog_inline_definitions(test_settings):
    from data_analytics_agent.semantic_context import render_sql_context

    catalog = load_semantic_catalog(
        test_settings.load_catalog().get("test").semantic_model_path, dialect="sqlite"
    ).catalog
    prompt = render_sql_context(catalog, source_id="test", dialect="sqlite")
    assert "Complete exact catalog definitions" in prompt
    assert '"expression":"ArtistId"' in prompt
    assert catalog.content_hash in prompt


def test_services_cache_catalogs_built_during_readiness(
    test_settings: Settings,
) -> None:
    services = Services(settings=test_settings)

    assert all(summary.ready for summary in services.source_summaries())
    first = services.semantic_catalog_for_source("test")
    second = services.semantic_catalog_for_source("test")

    assert first is second
    assert first.datasets["artists"].fields["artist_id"].physical_data_type


def test_browse_and_reviewed_value_lookup_do_not_bypass_sql_review(test_settings):
    from types import SimpleNamespace
    from data_analytics_agent.semantic_tools import (
        create_browse_semantic_tool,
        create_lookup_values_tool,
    )
    from data_analytics_agent.semantic import load_semantic_catalog
    from data_analytics_agent.stores import ResultStore, RunStore

    source = test_settings.load_catalog().get("test")
    catalog = load_semantic_catalog(
        source.semantic_model_path, dialect="sqlite"
    ).catalog
    page = create_browse_semantic_tool(catalog).func(
        dataset_name="artists", offset=0, limit=1
    )
    assert len(page["items"]) == 1 and page["next_offset"] == 1

    class NoExecution:
        def execute_batches(self, *args, **kwargs):
            raise AssertionError("Value lookup bypassed SQL review")

    runs = RunStore()
    run = runs.create("thread", "test", "Find artists")
    lookup = create_lookup_values_tool(
        catalog, source, NoExecution(), ResultStore(), runs, require_approval=True
    )
    result = lookup.func(
        dataset_name="artists",
        field_name="name",
        search="O'Reilly",
        runtime=SimpleNamespace(
            state={"thread_id": "thread", "run_id": run, "source_id": "test"},
            tool_call_id="lookup",
        ),
    )
    assert result["requires_sql_execution"] and "o''reilly" in result["query"]


def test_ambiguous_declared_routes_are_explicit():
    from dataclasses import replace
    from data_analytics_agent.semantic import SemanticRelationship

    catalog = _chinook_catalog()
    extra = SemanticRelationship(
        "alternate",
        "artists",
        "albums",
        ("artist_id",),
        ("artist_id",),
        "A different business role",
    )
    adjacency = dict(catalog.adjacency)
    adjacency["artists"] = (*adjacency["artists"], extra)
    adjacency["albums"] = (*adjacency["albums"], extra)
    revised = replace(
        catalog,
        content_hash="alternate",
        relationships=(*catalog.relationships, extra),
        adjacency=adjacency,
    )
    result = context(revised, dataset_names=["artists", "albums"])
    assert result["ambiguities"]
    assert len(result["ambiguities"][0]["routes"]) == 2


def test_large_catalog_question_resolves_outside_overview(test_settings):
    from dataclasses import replace
    from data_analytics_agent.semantic import SemanticDataset, SemanticField

    catalog = load_semantic_catalog(
        test_settings.load_catalog().get("test").semantic_model_path, dialect="sqlite"
    ).catalog
    datasets = {
        f"unrelated_{i}": SemanticDataset(
            f"unrelated_{i}",
            f"Table{i}",
            "Unrelated",
            ("id",),
            {"id": SemanticField("id", "Identifier", "Id")},
        )
        for i in range(300)
    }
    datasets.update(catalog.datasets)
    catalog = replace(catalog, datasets=datasets, content_hash="large-test")
    result = context(catalog, physical=True, question="artist_count")
    assert result["complete"]
    assert result["metrics"][0]["name"] == "artist_count"
    assert any(d["source"] == "Artist" for d in result["datasets"])
