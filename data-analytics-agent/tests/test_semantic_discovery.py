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
from data_analytics_agent.semantic_tools import create_semantic_tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHINOOK_PATH = PROJECT_ROOT / "semantic" / "chinook.osi.yaml"


def _chinook_catalog() -> SemanticCatalog:
    loaded = load_semantic_catalog(CHINOOK_PATH, dialect="sqlite")
    assert loaded.diagnostics.errors == ()
    assert loaded.catalog is not None
    return loaded.catalog


def _tools(catalog: SemanticCatalog, *, physical: bool = False):
    return {
        item.name: item
        for item in create_semantic_tools(
            catalog,
            include_physical=physical,
        )
    }


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
    disconnected = _tools(catalog)["get_relationships"].invoke(
        {
            "dataset_names": ["dataset_000"],
            "target_dataset": "dataset_199",
        }
    )
    assert disconnected["path_found"] is False
    assert disconnected["path"] is None


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


def test_entity_tools_apply_role_specific_projections_and_field_selection() -> None:
    catalog = _chinook_catalog()
    business = _tools(catalog)
    sql = _tools(catalog, physical=True)

    business_result = business["get_semantic_entities"].invoke(
        {"dataset_names": ["invoices"], "metric_names": ["total_revenue"]}
    )
    sql_result = sql["get_semantic_entities"].invoke(
        {
            "dataset_names": ["invoices"],
            "metric_names": ["total_revenue"],
            "field_names": {"invoices": ["invoice_date", "total"]},
        }
    )

    business_dataset = business_result["datasets"][0]
    sql_dataset = sql_result["datasets"][0]
    assert len(business_dataset["fields"]) == 9
    assert "source" not in business_dataset
    assert "expression" not in business_dataset["fields"][0]
    assert "expression" not in business_result["metrics"][0]
    assert sql_dataset["source"] == "Invoice"
    assert [field["name"] for field in sql_dataset["fields"]] == [
        "invoice_date",
        "total",
    ]
    assert sql_dataset["fields"][1]["expression"] == "Total"
    assert sql_result["metrics"][0]["expression"] == "SUM(invoices.Total)"
    assert business_result["model_hash"] == catalog.content_hash


def test_entity_tool_batches_common_multi_dataset_queries() -> None:
    catalog = _chinook_catalog()
    sql = _tools(catalog, physical=True)

    result = sql["get_semantic_entities"].invoke(
        {
            "dataset_names": [
                "invoice_lines",
                "invoices",
                "customers",
                "tracks",
                "genres",
                "albums",
                "artists",
            ],
            "field_names": {
                "invoice_lines": ["invoice_id", "track_id", "unit_price"],
                "invoices": ["invoice_id", "customer_id", "invoice_date"],
                "customers": ["customer_id", "country"],
                "tracks": ["track_id", "genre_id", "album_id"],
                "genres": ["genre_id", "name"],
                "albums": ["album_id", "artist_id"],
                "artists": ["artist_id", "name"],
            },
        }
    )

    assert [dataset["name"] for dataset in result["datasets"]] == [
        "invoice_lines",
        "invoices",
        "customers",
        "tracks",
        "genres",
        "albums",
        "artists",
    ]


def test_entity_tool_requires_field_selection_for_broad_requests() -> None:
    catalog = _chinook_catalog()
    sql = _tools(catalog, physical=True)

    result = sql["get_semantic_entities"].invoke(
        {
            "dataset_names": ["invoice_lines", "invoices", "customers"],
        }
    )

    assert "field_names is required" in result
    assert "use an empty list" in result


def test_entity_tool_error_explains_logical_field_names() -> None:
    catalog = _chinook_catalog()
    sql = _tools(catalog, physical=True)

    result = sql["get_semantic_entities"].invoke(
        {
            "dataset_names": ["invoices"],
            "field_names": {"invoices": ["InvoiceId"]},
        }
    )

    assert "logical names, not physical column names" in result
    assert "invoice_id" in result


def test_relationship_tool_returns_declared_adjacency_and_shortest_path() -> None:
    catalog = _chinook_catalog()
    relationships = _tools(catalog)["get_relationships"].invoke(
        {"dataset_names": ["artists"], "target_dataset": "invoices"}
    )

    assert relationships["path_found"] is True
    assert [edge["name"] for edge in relationships["relationships"]] == [
        "albums_to_artists"
    ]
    assert [edge["name"] for edge in relationships["path"]] == [
        "albums_to_artists",
        "tracks_to_albums",
        "invoice_lines_to_tracks",
        "invoice_lines_to_invoices",
    ]
    assert relationships["path_dataset_names"] == [
        "albums",
        "artists",
        "invoice_lines",
        "invoices",
        "tracks",
    ]


def test_relationship_tool_focuses_multi_dataset_requests() -> None:
    catalog = _chinook_catalog()
    relationships = _tools(catalog)["get_relationships"].invoke(
        {"dataset_names": ["invoice_lines", "invoices", "customers"]}
    )

    assert [edge["name"] for edge in relationships["relationships"]] == [
        "invoice_lines_to_invoices",
        "invoices_to_customers",
    ]
    assert relationships["path_dataset_names"] == []


def test_semantic_tool_schema_exposes_limits_and_logical_name_contract() -> None:
    catalog = _chinook_catalog()
    tools = _tools(catalog, physical=True)

    search_schema = tools["search_semantic_model"].args_schema.model_json_schema()
    entity_schema = tools["get_semantic_entities"].args_schema.model_json_schema()
    serialized = str({"search": search_schema, "entities": entity_schema})

    assert "Maximum matches to return, from 1 through 10." in serialized
    assert "Up to 10 exact logical dataset names" in serialized
    assert "never physical names such as InvoiceId" in serialized


def test_services_cache_catalogs_built_during_readiness(
    test_settings: Settings,
) -> None:
    services = Services(settings=test_settings)

    assert all(summary.ready for summary in services.source_summaries())
    first = services.semantic_catalog_for_source("test")
    second = services.semantic_catalog_for_source("test")

    assert first is second
    assert first.datasets["artists"].fields["artist_id"].physical_data_type
