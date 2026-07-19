from __future__ import annotations

from pathlib import Path

import yaml

SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1] / "semantic" / "chinook.osi.yaml"
)
FINANCIAL_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1] / "semantic" / "financial.osi.yaml"
)

EXPECTED_SOURCES = {
    "Artist": {"ArtistId", "Name"},
    "Album": {"AlbumId", "Title", "ArtistId"},
    "Employee": {
        "EmployeeId",
        "LastName",
        "FirstName",
        "Title",
        "ReportsTo",
        "BirthDate",
        "HireDate",
        "Address",
        "City",
        "State",
        "Country",
        "PostalCode",
        "Phone",
        "Fax",
        "Email",
    },
    "Customer": {
        "CustomerId",
        "FirstName",
        "LastName",
        "Company",
        "Address",
        "City",
        "State",
        "Country",
        "PostalCode",
        "Phone",
        "Fax",
        "Email",
        "SupportRepId",
    },
    "Genre": {"GenreId", "Name"},
    "Invoice": {
        "InvoiceId",
        "CustomerId",
        "InvoiceDate",
        "BillingAddress",
        "BillingCity",
        "BillingState",
        "BillingCountry",
        "BillingPostalCode",
        "Total",
    },
    "MediaType": {"MediaTypeId", "Name"},
    "Track": {
        "TrackId",
        "Name",
        "AlbumId",
        "MediaTypeId",
        "GenreId",
        "Composer",
        "Milliseconds",
        "Bytes",
        "UnitPrice",
    },
    "InvoiceLine": {
        "InvoiceLineId",
        "InvoiceId",
        "TrackId",
        "UnitPrice",
        "Quantity",
    },
    "Playlist": {"PlaylistId", "Name"},
    "PlaylistTrack": {"PlaylistId", "TrackId"},
}

EXPECTED_FINANCIAL_SOURCES = {
    "account": {"account_id", "district_id", "frequency", "date"},
    "card": {"card_id", "disp_id", "type", "issued"},
    "client": {"client_id", "gender", "birth_date", "district_id"},
    "disp": {"disp_id", "client_id", "account_id", "type"},
    "district": {
        "district_id",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8",
        "A9",
        "A10",
        "A11",
        "A12",
        "A13",
        "A14",
        "A15",
        "A16",
    },
    "loan": {
        "loan_id",
        "account_id",
        "date",
        "amount",
        "duration",
        "payments",
        "status",
    },
    "order": {
        "order_id",
        "account_id",
        "bank_to",
        "account_to",
        "amount",
        "k_symbol",
    },
    "trans": {
        "trans_id",
        "account_id",
        "date",
        "type",
        "operation",
        "amount",
        "balance",
        "k_symbol",
        "bank",
        "account",
    },
}


def test_osi_model_covers_complete_chinook_schema() -> None:
    document = yaml.safe_load(SEMANTIC_PATH.read_text())
    assert document["version"] == "0.1.1"
    models = document["semantic_model"]
    assert len(models) == 1
    model = models[0]
    datasets = {dataset["name"]: dataset for dataset in model["datasets"]}
    assert {dataset["source"] for dataset in datasets.values()} == set(
        EXPECTED_SOURCES
    )

    for dataset in datasets.values():
        physical_fields = {
            field["expression"]["dialects"][0]["expression"]
            for field in dataset["fields"]
        }
        assert physical_fields == EXPECTED_SOURCES[dataset["source"]]
        logical_fields = {field["name"] for field in dataset["fields"]}
        assert set(dataset["primary_key"]) <= logical_fields
        for field in dataset["fields"]:
            dialect = field["expression"]["dialects"][0]
            assert dialect["dialect"] == "ANSI_SQL"
            assert field["description"]

    assert len(model["relationships"]) == 11
    for relationship in model["relationships"]:
        assert relationship["from"] in datasets
        assert relationship["to"] in datasets
        assert len(relationship["from_columns"]) == len(
            relationship["to_columns"]
        )
        from_fields = {
            field["name"]
            for field in datasets[relationship["from"]]["fields"]
        }
        to_fields = {
            field["name"]
            for field in datasets[relationship["to"]]["fields"]
        }
        assert set(relationship["from_columns"]) <= from_fields
        assert set(relationship["to_columns"]) <= to_fields

    assert {metric["name"] for metric in model["metrics"]} == {
        "total_revenue",
        "line_revenue",
        "units_sold",
        "invoice_count",
        "customer_count",
        "track_count",
    }


def test_financial_osi_model_covers_complete_schema_and_business_context() -> None:
    document = yaml.safe_load(FINANCIAL_SEMANTIC_PATH.read_text())
    assert document["version"] == "0.1.1"
    model = document["semantic_model"][0]
    datasets = {dataset["name"]: dataset for dataset in model["datasets"]}
    assert {dataset["source"] for dataset in datasets.values()} == set(
        EXPECTED_FINANCIAL_SOURCES
    )

    for dataset in datasets.values():
        physical_fields = {
            field["expression"]["dialects"][0]["expression"]
            for field in dataset["fields"]
        }
        assert physical_fields == EXPECTED_FINANCIAL_SOURCES[
            dataset["source"]
        ]
        assert all(field["description"] for field in dataset["fields"])
        assert all(
            field["expression"]["dialects"][0]["dialect"] == "ANSI_SQL"
            for field in dataset["fields"]
        )

    assert len(model["relationships"]) == 8
    assert {metric["name"] for metric in model["metrics"]} == {
        "account_count",
        "client_count",
        "transaction_count",
        "transaction_volume",
        "transaction_inflow",
        "transaction_outflow",
        "net_cash_flow",
        "loan_count",
        "total_approved_loan_amount",
    }
    instructions = model["ai_context"]["instructions"]
    assert "currency" in instructions
    assert "PRIJEM" in instructions
    assert "VYDAJ" in instructions
