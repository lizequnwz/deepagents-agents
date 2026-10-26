"""A2UI surfaces contain saved evidence references, never generated values."""

import json

import pytest
from pydantic import ValidationError

from data_analytics_agent.dashboard.surfaces import (
    ANALYTICAL_CATALOG_ID,
    AnalyticalSurface,
    compile_dashboard_surface,
)
from tests.test_dashboards import dashboard as dashboard


def test_surface_compiles_only_current_saved_references(dashboard):
    w = dashboard
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    surface = compile_dashboard_surface(view)
    payload = surface.model_dump(mode="json")
    assert payload["revision_id"] == w.revision.revision_id
    assert payload["messages"][0] == {
        "version": "v0.9.1",
        "createSurface": {
            "surfaceId": surface.surface_id,
            "catalogId": ANALYTICAL_CATALOG_ID,
            "sendDataModel": False,
        },
    }
    components = payload["messages"][1]["updateComponents"]["components"]
    root, metric, chart, table, *evidence_refs = components
    evidence = next(item for item in evidence_refs if item["resultId"] == w.dataset.result_id)
    assert root == {
        "id": "root",
        "component": "EvidencePanel",
        "children": [component["id"] for component in components[1:]],
    }
    assert (metric["component"], metric["componentId"], metric["resultId"]) == (
        "MetricRef", "sales", w.dataset.result_id,
    )
    assert chart["component"] == "ChartRef"
    assert table["component"] == "TableRef"
    assert evidence["inspect"]["event"] == {
        "name": "inspect_evidence",
        "context": {
            "resultId": w.dataset.result_id,
            "revisionId": w.revision.revision_id,
        },
    }
    encoded = json.dumps(payload)
    for forbidden in ('"value"', '"formatted_value"', '"rows"', '"figure"', '"body"'):
        assert forbidden not in encoded
    assert compile_dashboard_surface(view) == surface
    assert AnalyticalSurface.model_validate(payload) == surface


@pytest.mark.parametrize("change", ["missing", "duplicate", "type", "result", "chart"])
def test_surface_rejects_inconsistent_resolved_evidence(dashboard, change):
    w = dashboard
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    components = list(view.components)
    if change == "missing":
        components.pop()
    elif change == "duplicate":
        components.append(components[0])
    elif change == "type":
        components[0] = components[0].model_copy(update={"type": "table"})
    elif change == "result":
        components[0] = components[0].model_copy(update={"result_id": "other-result"})
    else:
        components[1] = components[1].model_copy(update={"chart_id": "other-chart"})
    with pytest.raises(ValueError, match="saved"):
        compile_dashboard_surface(view.model_copy(update={"components": components}))


def test_surface_contract_rejects_executable_or_inline_data(dashboard):
    w = dashboard
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    payload = compile_dashboard_surface(view).model_dump(mode="json")
    payload["messages"][1]["updateComponents"]["components"][1]["value"] = 999_999
    with pytest.raises(ValidationError):
        AnalyticalSurface.model_validate(payload)
    payload = compile_dashboard_surface(view).model_dump(mode="json")
    payload["messages"][1]["updateComponents"]["components"][1]["component"] = "HTML"
    with pytest.raises(ValidationError):
        AnalyticalSurface.model_validate(payload)


def test_surface_keeps_explicit_empty_evidence(dashboard):
    w = dashboard
    empty = w.results.save(
        columns=["region", "day", "sales"], rows=[],
        thread_id=w.thread, source_id="test", executed_sql="SELECT * FROM facts WHERE FALSE",
    )
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    declaration = view.revision.spec.components[1].model_copy(
        update={"chart_id": None, "empty_result_id": empty.result_id}
    )
    revision = view.revision.model_copy(update={
        "spec": view.revision.spec.model_copy(update={
            "components": [view.revision.spec.components[0], declaration, view.revision.spec.components[2]]
        })
    })
    empty_chart = view.components[1].model_copy(update={
        "chart_id": None, "result_id": empty.result_id,
        "analysis_result_id": empty.result_id, "figure": None, "row_count": 0,
    })
    surface = compile_dashboard_surface(view.model_copy(update={
        "revision": revision, "components": [view.components[0], empty_chart, view.components[2]]
    }))
    chart = surface.messages[1].updateComponents.components[2]
    assert chart.component == "ChartRef" and chart.resultId == empty.result_id
