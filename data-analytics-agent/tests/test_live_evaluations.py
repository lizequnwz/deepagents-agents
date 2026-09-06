"""Opt-in model evaluations. All supplied source data is generated here.

RUN_LIVE_EVALUATIONS=1 authorizes sending these synthetic fixtures, the prompts,
and repository-authored skills to the configured model provider. No business
source is configured in this harness. Grade answer/method, never exact SQL.
"""

import os
import json
import math
import shutil
import sqlite3
from dataclasses import replace
import pytest
import yaml
from data_analytics_agent.api import Services
from data_analytics_agent.config import Settings
from data_analytics_agent.persistence import LocalStorage

QUESTIONS = {
    "descriptive": "Show total revenue across all months and the number of monthly observations. Include the report.",
    "forecasting": "Forecast revenue for the next 12 months. Use an initial Python step to inspect and compare against a seasonal-naive baseline on a temporal holdout. Examine those outputs before a separate Python step produces the final forecast. Check uncertainty against holdout errors and include a chart.",
    "seasonality": "Analyze trend and seasonality in revenue. Determine the seasonal period and explain the evidence and uncertainty.",
    "predictive": "Predict target from predictor. Compare a simple baseline using held-out evaluation; report errors, limitations and useful predictions.",
    "refinement": "Show monthly revenue as a line chart with the required report.",
}


def fixture_services(tmp_path):
    settings = Settings()
    project = tmp_path / "project"
    project.mkdir()
    (project / "semantic").mkdir()
    (project / "db").mkdir()
    shutil.copy(settings.project_root / "AGENTS.md", project / "AGENTS.md")
    shutil.copytree(settings.project_root / "skills", project / "skills")
    with sqlite3.connect(project / "db" / "fixture.sqlite") as db:
        db.execute(
            "CREATE TABLE facts (month TEXT, revenue REAL, predictor REAL, target REAL)"
        )
        db.executemany(
            "INSERT INTO facts VALUES (?,?,?,?)",
            [
                (
                    f"{2015 + i // 12}-{i % 12 + 1:02d}-01",
                    100 + 2 * i + 20 * math.sin(2 * math.pi * i / 12),
                    i,
                    10 + 3 * i + math.sin(i),
                )
                for i in range(120)
            ],
        )
    fields = [
        {
            "name": name,
            "description": description,
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": name}]},
        }
        for name, description in [
            ("month", "Monthly observation date"),
            ("revenue", "Monthly revenue in dollars"),
            ("predictor", "Observed predictor available before target"),
            ("target", "Numeric outcome for predictive modeling"),
        ]
    ]
    semantic = {
        "version": "0.1.1",
        "semantic_model": [
            {
                "name": "synthetic",
                "description": "Generated, non-sensitive analytical evaluation fixture.",
                "datasets": [
                    {
                        "name": "facts",
                        "source": "facts",
                        "description": "120 complete monthly observations. Each row is one month.",
                        "fields": fields,
                    }
                ],
                "relationships": [],
                "metrics": [],
            }
        ],
    }
    (project / "semantic" / "fixture.osi.yaml").write_text(yaml.safe_dump(semantic))
    registry = {
        "version": 1,
        "default_source": "fixture",
        "backends": {"sqlite": {"type": "sqlite"}},
        "sources": {
            "fixture": {
                "name": "Synthetic evaluation",
                "description": "Generated seasonal revenue and predictive observations.",
                "backend": "sqlite",
                "semantic_model": "semantic/fixture.osi.yaml",
                "dialect": "sqlite",
                "target": {"path": "db/fixture.sqlite"},
                "examples": [],
            }
        },
    }
    config = project / "data_sources.yaml"
    config.write_text(yaml.safe_dump(registry))
    return Services(
        settings=replace(
            settings,
            project_root=project,
            data_sources_config_path=config,
            require_sql_approval=False,
            require_python_approval=False,
        ),
        storage=LocalStorage(tmp_path / "workspace"),
    )


@pytest.mark.live
@pytest.mark.parametrize("case", list(QUESTIONS))
async def test_live_analytical_capability(case, tmp_path):
    if os.getenv("RUN_LIVE_EVALUATIONS") != "1":
        pytest.skip("Explicitly enable model invocation with RUN_LIVE_EVALUATIONS=1.")
    services = fixture_services(tmp_path)
    thread = services.conversations.create("fixture")

    async def ask(question):
        run = services.runs.create(thread, "fixture", question)
        services.conversations.begin_run(thread, run)
        await services.manager().start(run)
        state = services.runs.get(run)
        (tmp_path / f"{case}-{run}-trace.json").write_text(
            state.model_dump_json(indent=2)
        )
        assert state.status == "completed", state.error
        assert state.answer and state.answer.report and not state.answer.partial
        return state.answer

    answer = await ask(QUESTIONS[case])
    executions = [e for a in answer.analyses for e in a.executions if not e.error]
    # Save a human-reviewable methodology record; source SQL is evidence, not a target string.
    (tmp_path / f"{case}-evaluation.json").write_text(answer.model_dump_json(indent=2))
    if case == "descriptive":
        assert not executions
        values = [
            float(v)
            for ref in answer.results
            for row in services.results.get_unscoped(ref.result_id).rows
            for v in row.values()
            if isinstance(v, (int, float))
        ]
        assert any(abs(value - 26280) < 0.01 for value in values)
    elif case == "refinement":
        before = len(
            services.results.list_for_conversation(thread, source_id="fixture")
        )
        revised = await ask(
            "Keep that same saved evidence and revise the chart title to Revenue over time. Update the HTML report."
        )
        assert (
            len(services.results.list_for_conversation(thread, source_id="fixture"))
            == before
        )
        assert (
            revised.charts and revised.charts[0].chart_id != answer.charts[0].chart_id
        )
    else:
        assert executions
        # A rubric records inspectable method evidence, not exact generated programs.
        body = json.dumps([a.model_facing() for a in answer.analyses]).lower()
        required = {
            "forecasting": [
                ("baseline", "naive"),
                ("holdout", "hold-out", "test", "rolling"),
                ("interval", "uncertainty"),
            ],
            "seasonality": [("12", "annual", "yearly"), ("season", "decompos")],
            "predictive": [
                ("baseline", "dummy", "mean"),
                ("test", "holdout", "cross-validation"),
                ("mae", "rmse", "mean_absolute_error", "mean_squared_error"),
            ],
        }[case]
        assert all(
            any(term in body for term in alternatives) for alternatives in required
        ), body
        if case == "forecasting":
            assert len(executions) >= 2


def test_live_fixture_is_ready_without_model_invocation(tmp_path):
    services = fixture_services(tmp_path)
    source = services.source_summary("fixture")
    assert source.ready, source
