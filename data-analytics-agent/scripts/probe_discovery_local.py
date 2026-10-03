"""Probe synthetic catalog metadata locally; no provider or application server.

Run from the project root and redirect stdout to a JSON observation record.
Timings cover warmed metadata tools only, never live SQL-generation performance.
"""

import json
import math
from pathlib import Path
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from data_analytics_agent.evaluation import file_hash
from data_analytics_agent.semantic import load_semantic_catalog
from data_analytics_agent.semantic_sql import validate_semantic_sql
from data_analytics_agent.semantic_tools import (
    create_browse_semantic_tool,
    create_semantic_context_tool,
)
from scripts.prepare_ablation_fixtures import prepare_project


def probe(project):
    roles = {
        "measure": "revenue",
        "dimension": "region name",
        "filter": "region name",
        "time": "",
    }
    expected = {
        "measure": "total_revenue",
        "dimension": "regions.name",
        "filter": "regions.name",
        "time": "facts.month",
    }
    observations, date_choices = [], []
    for repetition in range(1, 4):
        for size, filename in [(2, "fixture"), (102, "wide")]:
            loaded = load_semantic_catalog(
                project / f"semantic/{filename}.osi.yaml", dialect="sqlite"
            )
            if loaded.diagnostics.errors:
                raise ValueError(loaded.diagnostics.errors)
            catalog = loaded.catalog
            catalog.search("revenue", entity_kinds=["metric"])
            tool = create_semantic_context_tool(
                catalog,
                source_id=f"local-{size}-{repetition}",
                dialect="sqlite",
                include_physical=True,
            )
            for variant in ["separate_roles", "batched_roles"]:
                requests = (
                    [{role: query} for role, query in roles.items()]
                    if variant == "separate_roles"
                    else [roles]
                )
                elapsed = []
                for sample in range(11):
                    start = perf_counter()
                    payloads = [
                        tool.func(
                            question="Revenue by region over the complete monthly population",
                            role_queries=request,
                            candidate_dataset_names=["facts", "regions"],
                        )
                        for request in requests
                    ]
                    duration = (perf_counter() - start) * 1000
                    if sample:
                        elapsed.append(duration)
                hits = {}
                for payload in payloads:
                    for role, candidates in payload["candidates"].items():
                        identities = [
                            (
                                candidate.get("dataset") + "."
                                if candidate.get("dataset")
                                else ""
                            )
                            + candidate["name"]
                            for candidate in candidates
                        ]
                        hits[role] = expected[role] in identities
                observations.append(
                    {
                        "catalog_datasets": size,
                        "repetition": repetition,
                        "variant": variant,
                        "requests_per_lookup": len(requests),
                        "role_hits": hits,
                        "role_candidate_recall": sum(hits.values()) / len(expected),
                        "response_characters": sum(
                            len(
                                json.dumps(
                                    payload, ensure_ascii=False, separators=(",", ":")
                                )
                            )
                            for payload in payloads
                        ),
                        "warmed_metadata_ms": elapsed,
                        "median_warmed_metadata_ms": median(elapsed),
                    }
                )
            browse = create_browse_semantic_tool(catalog, include_physical=True)
            broad = browse.func(
                entity_kind="field", query="date", time_only=True, limit=5
            )
            narrow = browse.func(
                entity_kind="field",
                query="date",
                time_only=True,
                dataset_name="facts",
                limit=5,
            )
            date_choices.append(
                {
                    "catalog_datasets": size,
                    "repetition": repetition,
                    "broad": [
                        f"{item['dataset']}.{item['name']}" for item in broad["items"]
                    ],
                    "narrow": [
                        f"{item['dataset']}.{item['name']}" for item in narrow["items"]
                    ],
                }
            )
            query = "SELECT r.name, SUM(f.revenue) AS revenue FROM facts f JOIN regions r ON f.region_id=r.region_id GROUP BY r.name"
            validate_semantic_sql(
                query,
                catalog,
                metric_names=["total_revenue"],
                relationship_names=["facts_to_regions"],
            )
            with sqlite3.connect(project / "db/fixture.sqlite") as db:
                actual = dict(db.execute(query))
            oracle = {
                region: sum(
                    100 + 2 * i + 20 * math.sin(2 * math.pi * i / 12)
                    for i in range(120)
                    if i % 3 == index
                )
                for index, region in enumerate(["North", "South", "West"])
            }
            if not all(
                math.isclose(actual[region], value, rel_tol=1e-10)
                for region, value in oracle.items()
            ):
                raise AssertionError(
                    "Manual fixture SQL disagrees with independent formula sums."
                )
    return {
        "verification": "local synthetic metadata and hand-authored SQL only",
        "provider_calls": 0,
        "limitations": [
            "Three fresh catalog instances in one process; caches are warmed before timed samples.",
            "These timings exclude model work and do not establish the live 15% completion gate.",
            "Candidate recall for declared role phrases is not independently graded question coverage or SQL-generation accuracy.",
        ],
        "fixture": json.loads((project / "fixture-manifest.json").read_text()),
        "code_hashes": {
            str(path): file_hash(path)
            for path in [
                Path(__file__),
                Path("data_analytics_agent/semantic_context.py"),
                Path("data_analytics_agent/semantic_tools.py"),
            ]
        },
        "observations": observations,
        "date_choices": date_choices,
        "manual_sql_reference": {
            "query": query,
            "actual": actual,
            "independent_formula": oracle,
        },
    }


if __name__ == "__main__":
    with TemporaryDirectory(prefix="analytics-local-discovery-") as folder:
        project = Path(folder) / "fixture"
        prepare_project(project)
        print(json.dumps(probe(project), indent=2))
