"""Prepare a frozen synthetic source, or serve it with the existing application.

Preparation makes no provider calls. Serving uses the configured provider only
when questions are submitted; obtain authorization before running live trials.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sqlite3

import yaml

from data_analytics_agent.evaluation import file_hash

ROOT = Path(__file__).resolve().parents[1]


def prepare_project(project, instructions_root=ROOT):
    project.mkdir(parents=True, exist_ok=False)
    (project / "db").mkdir()
    (project / "semantic").mkdir()
    shutil.copy2(instructions_root / "AGENTS.md", project / "AGENTS.md")
    shutil.copytree(instructions_root / "skills", project / "skills")
    database = project / "db/fixture.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE regions (region_id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE facts (
                observation_id INTEGER PRIMARY KEY, month TEXT, revenue REAL,
                predictor REAL, target REAL, region_id INTEGER
            );
            INSERT INTO regions VALUES (1, 'North'), (2, 'South'), (3, 'West');
        """)
        db.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?)",
            [
                (
                    i + 1,
                    f"{2015 + i // 12}-{i % 12 + 1:02d}-01",
                    100 + 2 * i + 20 * math.sin(2 * math.pi * i / 12),
                    i,
                    10 + 3 * i + math.sin(i),
                    i % 3 + 1,
                )
                for i in range(120)
            ],
        )

    def field(name, description, time=False):
        return {
            "name": name,
            "description": description,
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": name}]},
            **({"dimension": {"is_time": True}} if time else {}),
        }

    semantic = {
        "version": "0.1.1",
        "semantic_model": [
            {
                "name": "synthetic",
                "description": "Generated analytical fixture; no business or personal data.",
                "datasets": [
                    {
                        "name": "facts",
                        "source": "facts",
                        "primary_key": ["observation_id"],
                        "description": "120 complete monthly observations, January 2015 through December 2024, one row per month. Revenue is an index in source units, not currency.",
                        "fields": [
                            field(
                                "observation_id",
                                "Unique monthly observation identifier",
                            ),
                            field(
                                "month",
                                "Monthly observation date; the population is explicitly complete",
                                True,
                            ),
                            field(
                                "revenue",
                                "Monthly revenue index in source units, not currency",
                            ),
                            field(
                                "predictor",
                                "Observed predictor available before target",
                            ),
                            field("target", "Numeric outcome for predictive modeling"),
                            field(
                                "region_id",
                                "Region assigned to the observation; foreign key to regions",
                            ),
                        ],
                    },
                    {
                        "name": "regions",
                        "source": "regions",
                        "primary_key": ["region_id"],
                        "description": "Unique named regions",
                        "fields": [
                            field("region_id", "Unique region identifier"),
                            field("name", "Region name"),
                        ],
                    },
                ],
                "relationships": [
                    {
                        "name": "facts_to_regions",
                        "from": "facts",
                        "to": "regions",
                        "from_columns": ["region_id"],
                        "to_columns": ["region_id"],
                    }
                ],
                "metrics": [
                    {
                        "name": name,
                        "description": description,
                        "expression": {
                            "dialects": [
                                {"dialect": "ANSI_SQL", "expression": expression}
                            ]
                        },
                    }
                    for name, description, expression in [
                        (
                            "total_revenue",
                            "Sum of the revenue index in source units",
                            "SUM(facts.revenue)",
                        ),
                        (
                            "observation_count",
                            "Number of monthly observations",
                            "COUNT(facts.observation_id)",
                        ),
                    ]
                ],
            }
        ],
    }
    (project / "semantic/fixture.osi.yaml").write_text(
        yaml.safe_dump(semantic, sort_keys=False)
    )
    registry = {
        "version": 1,
        "default_source": "fixture",
        "backends": {"sqlite": {"type": "sqlite"}},
        "sources": {
            "fixture": {
                "name": "Synthetic evaluation",
                "description": "Generated seasonal and predictive observations.",
                "backend": "sqlite",
                "semantic_model": "semantic/fixture.osi.yaml",
                "dialect": "sqlite",
                "target": {"path": "db/fixture.sqlite"},
                "examples": [],
            }
        },
    }
    registry["sources"]["capped_fixture"] = {
        **registry["sources"]["fixture"],
        "name": "Synthetic capped retrieval",
        "limits": {"max_result_rows": 12},
    }
    (project / "data_sources.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False)
    )
    (project / "fixture-manifest.json").write_text(
        json.dumps(
            {
                "prepared_at": datetime.now(timezone.utc).isoformat(),
                "origin": "generated synthetic observations; deterministic formula, no random sampling",
                "population": "120 complete months, 2015-01 through 2024-12",
                "independent_checks": {
                    "row_count": 120,
                    "total_revenue": 26280,
                    "seasonal_period": 12,
                },
                "files": {
                    str(path.relative_to(project)): file_hash(path)
                    for path in [
                        database,
                        project / "semantic/fixture.osi.yaml",
                        project / "data_sources.yaml",
                    ]
                },
            },
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="A fresh synthetic project directory"
    )
    parser.add_argument(
        "--serve", action="store_true", help="Serve an already prepared project"
    )
    parser.add_argument("--port", type=int, default=8018)
    args = parser.parse_args()
    project = args.output.resolve()
    if not args.serve:
        prepare_project(project)
        print(project)
        return
    manifest = json.loads((project / "fixture-manifest.json").read_text())
    if any(
        file_hash(project / name) != expected
        for name, expected in manifest["files"].items()
    ):
        raise ValueError("Synthetic fixture changed after preparation")
    # Set temporary storage before api.app is imported. No user's active workspace
    # is opened, and the default warehouse registry is not used.
    import os

    os.environ["ANALYTICS_STORAGE_DIR"] = str(project / "workspace")
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from dataclasses import replace
    import uvicorn
    from data_analytics_agent.api import Services, create_app
    from data_analytics_agent.config import Settings

    services = Services(
        settings=replace(
            Settings(),
            project_root=project,
            data_sources_config_path=project / "data_sources.yaml",
        )
    )
    uvicorn.run(create_app(services), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
