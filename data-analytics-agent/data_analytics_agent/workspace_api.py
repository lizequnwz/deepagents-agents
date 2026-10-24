"""Same-origin workspace assets and scoped presentation endpoints."""

from dataclasses import replace
from pathlib import Path
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response

from data_analytics_agent.evidence import EvidenceResolver
from data_analytics_agent.visualization.renderer import PRODUCT_CHART_STYLE, build_chart


def workspace_router(services) -> APIRouter:
    router = APIRouter()

    @router.get("/api/conversations/{thread_id}/charts/{chart_id}/figure")
    def chart_figure(thread_id: str, chart_id: str):
        conversation = services.conversations.get(thread_id)
        resolver = EvidenceResolver(
            thread_id=thread_id,
            source_id=conversation.source_id,
            results=services.results,
            analyses=services.analyses,
            runs=services.runs,
        )
        chart = resolver.chart(chart_id)
        dataset = resolver.result(chart.result_id)
        if dataset.row_count > 5_000:
            raise HTTPException(422, "The chart needs bounded presentation data.")
        page = services.results.page(
            chart.result_id,
            thread_id,
            source_id=conversation.source_id,
            limit=5_000,
        )
        try:
            rendered = build_chart(
                chart, page.rows, style=replace(PRODUCT_CHART_STYLE, show_title=True)
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        figure = json.loads(rendered.figure.to_json())
        return {
            **figure,
            "warnings": list(rendered.warnings),
            "notes": list(rendered.notes),
        }

    @router.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/workspace/", status_code=307)

    @router.get("/workspace", include_in_schema=False)
    def workspace_redirect():
        return RedirectResponse("/workspace/", status_code=307)

    @router.get("/workspace/{asset_path:path}", include_in_schema=False)
    def workspace_asset(asset_path: str):
        root = (services.settings.project_root / "frontend" / "dist").resolve()
        index = root / "index.html"
        if not index.is_file():
            return Response(
                "The workspace has not been built. Run ./scripts/start.sh to build and start the application.",
                status_code=503,
                media_type="text/plain",
            )
        candidate = (root / asset_path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(404, "Resource not found.")
        if candidate.is_file():
            return FileResponse(
                candidate,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable"
                    if asset_path.startswith("assets/")
                    else "no-cache"
                },
            )
        if Path(asset_path).suffix:
            raise HTTPException(404, "Resource not found.")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return router
