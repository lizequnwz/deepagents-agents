"""Cross-module contracts that protect the meaning of interactive changes."""

import pytest

from data_analytics_agent.agents.text_to_sql.dashboard_queries import (
    QueryDefinition,
    execute_dashboard_query,
)
from data_analytics_agent.dashboard.schemas import DashboardAction, DashboardFilter
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.dashboard.store import DashboardStore
from tests.test_dashboard_presentation import (
    saved_dashboard as saved_dashboard,  # noqa: PLC0414
)


def test_receipt_cannot_certify_an_unrequested_population_filter(workspace):
    w = workspace
    population = w.results.save(
        columns=["region", "sales"],
        rows=[{"region": "North", "sales": 10}, {"region": "North", "sales": 5}],
        thread_id=w.thread, source_id="test",
    )
    definition = QueryDefinition(
        input_result_id=population.result_id,
        measures=[{"name": "total", "aggregation": "sum", "column": "sales"}],
        filters=[{"id": "region", "column": "region"}, {"id": "hidden", "column": "sales"}],
    )
    narrowed = execute_dashboard_query(
        definition, {"region": ["North"], "hidden": [10]},
        results=w.results, runs=w.runs, thread_id=w.thread, source_id="test",
        run_id=w.run, purpose="Unexpected extra narrowing",
    )
    assert narrowed.read_rows(1) == [{"total": 10}]  # Requested region totals 15.
    service = DashboardService(w.results, w.analyses, w.runs, w.reports, DashboardStore(w.storage))
    declared = DashboardFilter(id="region", label="Region", bindings=[{"component_id": "total", "column": "region"}])
    with pytest.raises(ValueError):
        service._validate_population(narrowed, [(declared, "region", ["North"])])
    # Resetting the visible filters must not preserve the hidden constraint.
    with pytest.raises(ValueError):
        service._validate_population(narrowed, [])


def test_dashboard_filter_values_preserve_source_whitespace():
    action = DashboardAction(
        action="filter", expected_revision="revision", request_id="select-region",
        filter_values={"region": [" North "]},
    )
    assert action.filter_values == {"region": [" North "]}
    filtering = DashboardFilter(
        id="region", label="Region", default_values=[" North "],
        bindings=[{"component_id": "total", "column": "region"}],
    )
    assert filtering.default_values == [" North "]


@pytest.mark.parametrize("number_format", ["0.00", "1001f"])
def test_new_dashboard_api_specs_validate_formats_before_rendering(
    saved_dashboard, number_format
):
    from fastapi.testclient import TestClient

    from data_analytics_agent.api import create_app

    w = saved_dashboard
    spec = w.revision.spec.model_dump(mode="json")
    spec["components"][0]["metric"]["number_format"] = number_format
    before = w.services.storage.load("dashboard_revisions", dict)
    with TestClient(create_app(w.services)) as client:
        response = client.post(
            f"/api/conversations/{w.thread}/dashboards",
            json={"run_id": w.run, "spec": spec, "request_id": "invalid-format"},
        )
    assert response.status_code == 422, response.json().get("detail", "Created dashboard")
    assert w.services.storage.load("dashboard_revisions", dict) == before


@pytest.mark.parametrize("kind,orientation,expected", [
    ("waterfall", "horizontal", "y"),
    ("waterfall", "vertical", "x"),
    ("funnel", "horizontal", "y"),
    ("funnel", "vertical", "x"),
])
def test_process_chart_selection_uses_the_label_axis(kind, orientation, expected):
    from data_analytics_agent.dashboard.schemas import DashboardSpec
    from data_analytics_agent.visualization.schemas import ChartSpec

    chart = ChartSpec(
        result_id="saved", chart_type=kind, title="Process", x="stage", y=["value"],
        orientation=orientation,
        **({"waterfall_measure": "measure"} if kind == "waterfall" else {"stage_order": ["Started", "Finished"]}),
    )
    spec = DashboardSpec.model_validate({
        "title": "Process", "components": [{"type": "chart", "id": "process", "chart_id": "chart"}],
        "filters": [{"id": "stage", "label": "Stage", "bindings": [{"component_id": "process", "column": "stage"}]}],
    })
    assert DashboardService.selection_fields(spec, "process", chart) == [
        {"column": "stage", "label": "Stage", "point_key": expected}
    ]
