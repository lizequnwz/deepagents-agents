"""Reproduce review findings against metadata only; no warehouse or LLM calls.

Run from the repository root:
PYTHONPATH=. .venv/bin/python doc/reviews/semantic-discovery-probes-2026-09-21.py
These assertions describe the reviewed defects, not desired regression behavior.
"""

from dataclasses import replace
import json
from pathlib import Path

from data_analytics_agent.semantic import (
    SemanticField,
    SemanticMetric,
    load_semantic_catalog,
)
from data_analytics_agent.semantic_context import build_semantic_context


ROOT = Path(__file__).resolve().parents[2]
catalog = load_semantic_catalog(
    ROOT / "semantic/chinook.osi.yaml", dialect="sqlite"
).catalog
assert catalog is not None
observations = []


def inspect(label, selected_catalog=catalog, **kwargs):
    result = build_semantic_context(
        selected_catalog,
        source_id="semantic-review",
        dialect="sqlite",
        include_physical=True,
        **kwargs,
    )
    observations.append(
        {
            "case": label,
            "complete": result["complete"],
            "datasets": [d["name"] for d in result.get("datasets", [])],
            "metrics": [m["name"] for m in result.get("metrics", [])],
            "relationships": [r["name"] for r in result.get("relationships", [])],
            "fields": {
                d["name"]: [f["name"] for f in d["fields"]]
                for d in result.get("datasets", [])
            },
            "ambiguities": result.get("ambiguities", []),
            "unresolved": result.get("unresolved_references", []),
            "omissions": result.get("omissions", []),
        }
    )
    return observations[-1]


r = inspect("revenue by country", question="revenue by country")
assert r["complete"] and r["metrics"] == ["line_revenue"]
assert "employees" in r["datasets"] and not r["ambiguities"]

r = inspect("monthly revenue by genre", question="monthly revenue by genre")
assert r["complete"] and not r["metrics"]

r = inspect("employee-manager self relationship", dataset_names=["employees"])
assert r["complete"] and not r["relationships"]
assert any(r.from_dataset == r.to_dataset == "employees" for r in catalog.relationships)

r = inspect("explicit dataset ignores question", question="revenue by genre", dataset_names=["invoices"])
assert r["complete"] and r["datasets"] == ["invoices"] and not r["metrics"]

r = inspect("ambiguity coexists with complete", question="revenue")
assert r["complete"] and r["ambiguities"]

r = inspect("ordinary question exceeds budget", question="sales by artist")
assert not r["complete"] and not r["datasets"] and r["omissions"]

fields = dict(catalog.datasets["invoices"].fields)
fields.update({
    f"extra_{i}": SemanticField(f"extra_{i}", "Unrelated metadata " * 15, f"Extra{i}")
    for i in range(80)
})
datasets = dict(catalog.datasets)
datasets["invoices"] = replace(datasets["invoices"], fields=fields)
wide = replace(catalog, datasets=datasets, content_hash="review-wide-v1")
r = inspect("wide dataset metric", wide, metric_names=["total_revenue"])
assert not r["complete"] and not r["datasets"]
r = inspect("same metric with explicit field projection", wide, metric_names=["total_revenue"], field_names={"invoices": []})
assert r["complete"] and set(r["fields"]["invoices"]) == {"total", "invoice_id"}

metrics = dict(catalog.metrics)
metrics["row_count"] = SemanticMetric("row_count", "Invoice row count", "COUNT(*)")
count_catalog = replace(catalog, metrics=metrics, content_hash="review-count-v1")
r = inspect("unbound row-count metric", count_catalog, metric_names=["row_count"])
assert r["complete"] and not r["datasets"]

metrics = dict(catalog.metrics)
metrics["derived"] = SemanticMetric("derived", "Derived measure", "SUM(invoices.adjusted)")
fields = dict(catalog.datasets["invoices"].fields)
fields["net_amount"] = SemanticField("net_amount", "Logical amount", "Total")
fields["adjusted"] = SemanticField("adjusted", "Adjusted total", "net_amount * 0.9")
datasets = dict(catalog.datasets)
datasets["invoices"] = replace(datasets["invoices"], fields=fields)
derived_catalog = replace(catalog, metrics=metrics, datasets=datasets, content_hash="review-derived-v1")
r = inspect("nonrecursive logical field dependency", derived_catalog, metric_names=["derived"], field_names={"invoices": []})
assert r["complete"] and "adjusted" in r["fields"]["invoices"]
assert "net_amount" not in r["fields"]["invoices"]

print(json.dumps(observations, indent=2))
