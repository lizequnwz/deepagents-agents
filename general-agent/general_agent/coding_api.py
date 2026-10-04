"""Loopback repository routes, always bound to the selected corporation."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.routing import APIRoute

from general_agent.coding.schemas import (
    ApplyRequest, DecisionResponse, DeliveryPrepare, DeliveryPublish, DocumentOpen, DocumentUpdate, GitHubConnect,
    InlineAcceptance, InlineCancel, InlineRequest, InputResponse, ProjectCreate, SetupRequest, SnowflakeEnable, SnowflakeRead, SteeringRequest, TaskCreate,
)
from general_agent.coding.store import CodingConflict
from general_agent.coding.snowflake import SnowflakeError
from general_agent.workspace import validate_corp_id


class CodingRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def scoped_handler(request):
            try:
                return await original(request)
            except CodingConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except KeyError as exc:
                raise HTTPException(404, "Coding record not found.") from exc
            except SnowflakeError as exc:
                raise HTTPException(400, {"error": str(exc), "provenance": exc.provenance}) from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

        return scoped_handler


router = APIRouter(route_class=CodingRoute)


def scoped(request: Request):
    corp = validate_corp_id(request.headers.get("X-Corp-ID") or request.app.state.settings.default_corp_id)
    return request.app.state.coding, corp


@router.get("/coding/readiness")
async def readiness(request: Request):
    service, _ = scoped(request)
    return await service.readiness()


@router.get("/projects")
async def projects(request: Request):
    service, corp = scoped(request)
    return service.store.projects(corp)


@router.post("/projects", status_code=201)
async def register(request: Request, body: ProjectCreate):
    service, corp = scoped(request)
    return await service.register(corp, body.root, body.name, body.checks, body.documentation_domains)


@router.get("/projects/{project_id}")
async def project(request: Request, project_id: str):
    service, corp = scoped(request)
    return service.store.project(corp, project_id)


@router.get("/projects/{project_id}/github")
async def github_status(request: Request, project_id: str):
    service, corp = scoped(request)
    return await service.github.status(corp, project_id)


@router.post("/projects/{project_id}/github")
async def github_connect(request: Request, project_id: str, body: GitHubConnect):
    service, corp = scoped(request)
    return await service.github.connect(corp, project_id, body.owner, body.repository)


@router.get("/projects/{project_id}/snowflake")
async def snowflake_status(request: Request, project_id: str):
    service, corp = scoped(request)
    return service.snowflake.status(corp, project_id)


@router.post("/projects/{project_id}/snowflake")
async def snowflake_enable(request: Request, project_id: str, body: SnowflakeEnable):
    service, corp = scoped(request)
    return service.snowflake.enable(corp, project_id, body.enabled, body.expected_digest)


@router.get("/projects/{project_id}/snowflake/schema")
async def snowflake_schema(request: Request, project_id: str, table: str):
    service, corp = scoped(request)
    return await service.snowflake.read(corp, project_id, "schema", table=table)


@router.get("/projects/{project_id}/snowflake/reads")
async def snowflake_reads(request: Request, project_id: str):
    service, corp = scoped(request)
    return service.store.connector_queries(corp, project_id)


@router.post("/projects/{project_id}/snowflake/rows")
async def snowflake_rows(request: Request, project_id: str, body: SnowflakeRead):
    service, corp = scoped(request)
    return await service.snowflake.read(corp, project_id, "rows", table=body.table, columns=body.columns,
                                       limit=body.limit, filters=body.filters)


@router.get("/projects/{project_id}/github/issues")
async def github_issues(request: Request, project_id: str, page: int = Query(1, ge=1, le=3),
                        state: Literal["open", "closed", "all"] = "open"):
    service, corp = scoped(request)
    return await service.github.read(corp, project_id, "issues", page=page, state=state)


@router.get("/projects/{project_id}/github/issues/{number}")
async def github_issue(request: Request, project_id: str, number: int):
    service, corp = scoped(request)
    return await service.github.read(corp, project_id, "issue", number=number)


@router.get("/projects/{project_id}/github/pulls/{number}")
async def github_pull(request: Request, project_id: str, number: int):
    service, corp = scoped(request)
    return await service.github.read(corp, project_id, "pull", number=number)


@router.post("/changes/{change_id}/deliveries", status_code=201)
async def delivery_prepare(request: Request, change_id: str, body: DeliveryPrepare):
    service, corp = scoped(request)
    return await service.github.prepare(corp, change_id, body.title, body.body, body.base)


@router.get("/sessions/{session_id}/deliveries")
async def deliveries(request: Request, session_id: str):
    service, corp = scoped(request)
    return service.store.deliveries(corp, session_id)


@router.get("/deliveries/{delivery_id}")
async def delivery(request: Request, delivery_id: str):
    service, corp = scoped(request)
    return service.store.delivery(corp, delivery_id)


@router.post("/deliveries/{delivery_id}/publish")
async def delivery_publish(request: Request, delivery_id: str, body: DeliveryPublish):
    service, corp = scoped(request)
    return await service.github.publish(corp, delivery_id, body.expected_digest)


@router.post("/projects/{project_id}/sessions", status_code=201)
async def create_session(request: Request, project_id: str):
    service, corp = scoped(request)
    return await service.create_session(corp, project_id)


@router.get("/sessions")
async def sessions(request: Request):
    service, corp = scoped(request)
    return service.store.sessions(corp)


@router.get("/sessions/{session_id}")
async def session(request: Request, session_id: str):
    service, corp = scoped(request)
    return await service.session(corp, session_id)


@router.get("/sessions/{session_id}/editor")
async def editor_context(request: Request, session_id: str):
    service, corp = scoped(request)
    session = service.store.session(corp, session_id)
    project = service.store.project(corp, session["project_id"])
    service.projects.source_root(corp, project["id"])
    return {"id": session_id, "project": {"id": project["id"], "root": project["root"]}}


@router.post("/sessions/{session_id}/tasks", status_code=202)
async def task(request: Request, session_id: str, body: TaskCreate):
    service, corp = scoped(request)
    return await service.submit(corp, session_id, body.message, body.mode,
                                plan_id=body.plan_id, parent_id=body.parent_id)


@router.get("/sessions/{session_id}/setup")
async def setup_status(request: Request, session_id: str):
    service, corp = scoped(request)
    return await service.setup_status(corp, session_id)


@router.post("/sessions/{session_id}/setup", status_code=202)
async def prepare(request: Request, session_id: str, body: SetupRequest):
    service, corp = scoped(request)
    return await service.prepare(corp, session_id, body.kind, body.manifest_identity)


@router.get("/coding/runs/{run_id}")
async def run(request: Request, run_id: str, after: int = Query(0, ge=0),
              limit: int = Query(200, ge=1, le=500)):
    service, corp = scoped(request)
    return {**await service.attempt(corp, run_id), **service.store.events(corp, run_id, after, limit)}


@router.post("/coding/runs/{run_id}/stop")
async def stop(request: Request, run_id: str):
    service, corp = scoped(request)
    return await service.stop(corp, run_id)


@router.post("/coding/runs/{run_id}/steer", status_code=202)
async def steer(request: Request, run_id: str, body: SteeringRequest):
    service, corp = scoped(request)
    return await service.steer(corp, run_id, body.message)


@router.get("/coding/runs/{run_id}/processes")
async def processes(request: Request, run_id: str):
    service, corp = scoped(request)
    return service.process_records(corp, run_id)


@router.get("/coding/runs/{run_id}/processes/{process_id}")
async def process_output(request: Request, run_id: str, process_id: str, cursor: int = Query(0, ge=0)):
    service, corp = scoped(request)
    return service.process_output(corp, run_id, process_id, cursor)


@router.post("/coding/runs/{run_id}/processes/{process_id}/stop")
async def stop_process(request: Request, run_id: str, process_id: str):
    service, corp = scoped(request)
    return await service.stop_process(corp, run_id, process_id)


@router.get("/coding/runs/{run_id}/browser/{check_id}/image")
async def browser_image(request: Request, run_id: str, check_id: str):
    service, corp = scoped(request)
    data = service.browser_image(corp, run_id, check_id)
    return Response(data, media_type="image/png", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/runs/{run_id}/changes")
async def changes(request: Request, run_id: str):
    service, corp = scoped(request)
    attempt = service.store.attempt(corp, run_id)
    return service.store.change(corp, attempt["change_id"]) if attempt.get("change_id") else None


@router.get("/runs/{run_id}/checks")
async def checks(request: Request, run_id: str):
    service, corp = scoped(request)
    return (await service.attempt(corp, run_id))["checks"]


@router.get("/runs/{run_id}/checks/{check_id}/evidence")
async def check_evidence(request: Request, run_id: str, check_id: str):
    service, corp = scoped(request)
    attempt = service.store.attempt(corp, run_id)
    check = next((record for record in attempt.get("check_evidence", []) if record["id"] == check_id), None)
    if check is None:
        raise HTTPException(404, "Check evidence not found.")
    return service.evidence.get(corp, attempt["session_id"], check["evidence_id"], check["evidence_sha256"])


@router.get("/changes/{change_id}/diff")
async def diff(request: Request, change_id: str):
    service, corp = scoped(request)
    return await service.diff(corp, change_id)


@router.get("/changes/{change_id}/files")
async def version(request: Request, change_id: str, path: str,
                  side: Literal["before", "after"] = "after"):
    service, corp = scoped(request)
    change = service.store.change(corp, change_id)
    entry = next((entry for entry in change["files"] if entry["path"] == path), None)
    if entry is None or entry[side] is None:
        raise HTTPException(404, "Source version not found.")
    content = await asyncio.to_thread(service.changes.blob, corp, change["session_id"], entry[side]["sha256"])
    return Response(content, media_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})


@router.post("/changes/{change_id}/apply")
async def apply(request: Request, change_id: str, body: ApplyRequest):
    service, corp = scoped(request)
    return await service.apply(corp, change_id, body.expected_revision, body.paths)


@router.post("/changes/{change_id}/revert")
async def revert(request: Request, change_id: str, body: ApplyRequest):
    service, corp = scoped(request)
    if body.paths is not None:
        raise HTTPException(400, "Revert restores the complete recorded application.")
    return await service.revert(corp, change_id, body.expected_revision)


@router.post("/changes/{change_id}/reject")
async def reject(request: Request, change_id: str, body: ApplyRequest):
    service, corp = scoped(request)
    if body.paths is not None:
        raise HTTPException(400, "Reject restores the complete unapplied proposal.")
    return await service.discard(corp, change_id, body.expected_revision)


@router.post("/decisions/{decision_id}/respond")
async def respond(request: Request, decision_id: str, body: DecisionResponse):
    service, corp = scoped(request)
    return await service.respond(corp, decision_id, body.response)


@router.get("/decisions/{decision_id}")
async def decision(request: Request, decision_id: str):
    service, corp = scoped(request)
    return service.store.decision(corp, decision_id)


@router.post("/decisions/{decision_id}/input", status_code=202)
async def input_response(request: Request, decision_id: str, body: InputResponse):
    service, corp = scoped(request)
    return await service.answer_input(corp, decision_id, body.message)


@router.get("/sessions/{session_id}/attempts")
async def history(request: Request, session_id: str, before: str | None = None,
                  limit: int = Query(50, ge=1, le=200)):
    service, corp = scoped(request)
    records = service.store.attempts(corp, session_id, limit=limit + 1, before=before)
    page = records[-limit:]
    return {"attempts": page, "next_cursor": page[0]["id"] if page else None,
            "has_more": len(records) > limit}


@router.get("/coding/inline/status")
async def inline_status(request: Request):
    service, corp = scoped(request)
    return {"enabled": service.inline.enabled, "statistics": service.store.inline_statistics(corp)}


@router.post("/sessions/{session_id}/documents", status_code=201)
async def document_open(request: Request, session_id: str, body: DocumentOpen):
    service, corp = scoped(request)
    return service.inline.open(corp, session_id, body.path, body.content, body.version)


@router.put("/sessions/{session_id}/documents/{document_id}")
async def document_update(request: Request, session_id: str, document_id: str, body: DocumentUpdate):
    service, corp = scoped(request)
    return service.inline.update(corp, session_id, document_id, body.content, body.version)


@router.delete("/sessions/{session_id}/documents/{document_id}", status_code=204)
async def document_close(request: Request, session_id: str, document_id: str):
    service, corp = scoped(request)
    await service.inline.close_document(corp, session_id, document_id)


@router.post("/sessions/{session_id}/documents/{document_id}/complete")
async def inline_complete(request: Request, session_id: str, document_id: str, body: InlineRequest):
    service, corp = scoped(request)
    return await service.inline.complete(corp, session_id, document_id, body.version, body.offset_utf16, body.request_id)


@router.post("/sessions/{session_id}/documents/{document_id}/cancel")
async def inline_cancel(request: Request, session_id: str, document_id: str, body: InlineCancel | None = None):
    service, corp = scoped(request)
    return await service.inline.cancel(corp, session_id, document_id, body.request_id if body else None)


@router.post("/sessions/{session_id}/documents/{document_id}/accepted")
async def inline_accepted(request: Request, session_id: str, document_id: str, body: InlineAcceptance):
    service, corp = scoped(request)
    return service.inline.accepted(corp, session_id, document_id, body.suggestion_id)
