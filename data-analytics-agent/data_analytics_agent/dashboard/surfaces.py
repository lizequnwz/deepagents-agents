"""Compile governed dashboard evidence into a bounded A2UI surface.

The wire describes references and layout. Values remain in DashboardView, whose
evidence has already been resolved by DashboardService. This is a presentation
compiler; it cannot execute an analysis, create values, or commit a revision.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from data_analytics_agent.dashboard.schemas import (
    DashboardModel,
    DashboardView,
)


ANALYTICAL_CATALOG_ID = "analytics-workspace:analytical-evidence-v1"
A2UI_VERSION = "v0.9.1"


class EvidencePanel(DashboardModel):
    id: str
    component: Literal["EvidencePanel"] = "EvidencePanel"
    children: list[str]


class AnalyticalReference(DashboardModel):
    id: str
    component: Literal["MetricRef", "ChartRef", "TableRef"]
    componentId: str
    resultId: str


class InspectContext(DashboardModel):
    resultId: str
    revisionId: str


class InspectEvent(DashboardModel):
    name: Literal["inspect_evidence"] = "inspect_evidence"
    context: InspectContext


class InspectAction(DashboardModel):
    event: InspectEvent


class EvidenceReference(DashboardModel):
    id: str
    component: Literal["EvidenceRef"] = "EvidenceRef"
    resultId: str
    inspect: InspectAction


SurfaceComponent = Annotated[
    EvidencePanel | AnalyticalReference | EvidenceReference,
    Field(discriminator="component"),
]


class CreateSurface(DashboardModel):
    surfaceId: str
    catalogId: Literal[ANALYTICAL_CATALOG_ID] = ANALYTICAL_CATALOG_ID
    sendDataModel: Literal[False] = False


class CreateSurfaceMessage(DashboardModel):
    version: Literal[A2UI_VERSION] = A2UI_VERSION
    createSurface: CreateSurface


class UpdateComponents(DashboardModel):
    surfaceId: str
    components: list[SurfaceComponent]


class UpdateComponentsMessage(DashboardModel):
    version: Literal[A2UI_VERSION] = A2UI_VERSION
    updateComponents: UpdateComponents


class AnalyticalSurface(DashboardModel):
    protocol: Literal["a2ui"] = "a2ui"
    version: Literal[A2UI_VERSION] = A2UI_VERSION
    dashboard_id: str
    revision_id: str
    surface_id: str
    messages: tuple[CreateSurfaceMessage, UpdateComponentsMessage]


def compile_dashboard_surface(view: DashboardView) -> AnalyticalSurface:
    """Return one read-only evidence panel for this exact resolved revision.

    Refuse inconsistent view/spec pairs. This also prevents a caller from
    attaching evidence from a different revision to an otherwise valid surface.
    Authorization and evidence resolution remain with the calling service.
    """
    revision = view.revision
    declarations = {component.id: component for component in revision.spec.components}
    resolved = {component.id: component for component in view.components}
    if len(resolved) != len(view.components) or resolved.keys() != declarations.keys():
        raise ValueError("Surface components must match the saved dashboard revision.")

    components: list[SurfaceComponent] = []
    result_ids: set[str] = set()
    reference_types = {"metric": "MetricRef", "chart": "ChartRef", "table": "TableRef"}
    for index, declaration in enumerate(revision.spec.components):
        component = resolved[declaration.id]
        if component.type != declaration.type:
            raise ValueError("Surface component type differs from the saved revision.")
        if component.type == "text":
            continue
        if declaration.type == "metric":
            expected_result = declaration.metric.result_id
        elif declaration.type == "table":
            expected_result = declaration.result_id
        else:
            expected_result = declaration.empty_result_id
            if declaration.chart_id != component.chart_id:
                raise ValueError("Surface chart differs from the saved revision.")
        if not component.result_id or (
            expected_result is not None and component.result_id != expected_result
        ):
            raise ValueError("Surface evidence differs from the saved revision.")
        components.append(
            AnalyticalReference(
                id=f"panel-{index}",
                component=reference_types[component.type],
                componentId=component.id,
                resultId=component.result_id,
            )
        )
        result_ids.add(component.analysis_result_id or component.result_id)
        result_ids.add(component.result_id)

    # Presentation snapshots can be referenced by components but have no source
    # completeness claim. Their analytical source is included above as well.
    # Only component evidence is exposed, so 60 cards need at most 120 sources.
    for index, result_id in enumerate(sorted(result_ids)):
        components.append(
            EvidenceReference(
                id=f"evidence-{index}",
                resultId=result_id,
                inspect=InspectAction(
                    event=InspectEvent(
                        context=InspectContext(
                            resultId=result_id, revisionId=revision.revision_id
                        )
                    )
                ),
            )
        )
    root = EvidencePanel(id="root", children=[item.id for item in components])
    surface_id = f"evidence-{revision.revision_id}"
    return AnalyticalSurface(
        dashboard_id=revision.dashboard_id,
        revision_id=revision.revision_id,
        surface_id=surface_id,
        messages=(
            CreateSurfaceMessage(createSurface=CreateSurface(surfaceId=surface_id)),
            UpdateComponentsMessage(
                updateComponents=UpdateComponents(
                    surfaceId=surface_id, components=[root, *components]
                )
            ),
        ),
    )
