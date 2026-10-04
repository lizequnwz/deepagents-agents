"""Document versions, UTF-16 offsets, cancellation, source drift and metrics."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from general_agent.api import create_app
from general_agent.coding.inline import InlineService
from general_agent.coding.service import CodingService
from general_agent.coding.store import CodingConflict, CodingStore
from tests.fakes import FakeGraph
from tests.test_coding_api import FixtureRuntime, fixture_project, open_session


class Model:
    def __init__(self, *, wait=False, content=" + 2"):
        self.wait, self.content = wait, content
        self.started, self.finish = asyncio.Event(), asyncio.Event()
        self.inputs = []

    async def ainvoke(self, messages):
        self.inputs.append(messages)
        self.started.set()
        if self.wait:
            await self.finish.wait()
        return AIMessage(content=self.content, usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})


@pytest.fixture
async def inline(settings):
    root = fixture_project(settings)
    store = CodingStore(settings.coding_db)
    coding = CodingService(settings, store, InMemorySaver(), runtime_factory=FixtureRuntime)
    model = Model()
    coding.inline = InlineService(coding, model=model)
    project = await coding.register("A123456", str(root), "Fixture", {})
    session = await coding.create_session("A123456", project["id"])
    try:
        yield coding, session, model
    finally:
        await coding.close()
        store.close()


async def test_versioned_completion_and_single_use_editor_reported_acceptance(inline):
    coding, session, model = inline
    service = coding.inline
    opened = service.open("A123456", session["id"], "increment.py", "return value", 1)
    result = await service.complete("A123456", session["id"], opened["document_id"], 1, 12)
    assert result["items"] == [{"start_utf16": 12, "end_utf16": 12, "text": " + 2"}]
    assert model.inputs[0][0]["role"] == "system"
    assert (coding.projects.repository("A123456", session["id"]) / "increment.py").read_text().endswith("value + 1\n")
    service.accepted("A123456", session["id"], opened["document_id"], result["suggestion_id"])
    with pytest.raises(CodingConflict):
        service.accepted("A123456", session["id"], opened["document_id"], result["suggestion_id"])
    stats = coding.store.inline_statistics("A123456")
    assert stats["offered"] == 1 and stats["editor_reported_acceptances"] == 1
    assert stats["reported_tokens"] == 13
    assert coding.store.inline_statistics("OTHER_CORP")["offered"] == 0


async def test_stale_versions_paths_unicode_and_scope(inline):
    coding, session, _ = inline
    service = coding.inline
    opened = service.open("A123456", session["id"], "increment.py", "😀x", 3)
    document_id = opened["document_id"]
    with pytest.raises(CodingConflict):
        service.update("A123456", session["id"], document_id, "old", 2)
    with pytest.raises(CodingConflict):
        service.update("A123456", session["id"], document_id, "inconsistent", 3)
    with pytest.raises(ValueError, match="Unicode"):
        await service.complete("A123456", session["id"], document_id, 3, 1)
    result = await service.complete("A123456", session["id"], document_id, 3, 2)
    assert result["items"][0]["start_utf16"] == 2
    with pytest.raises(KeyError):
        service.update("OTHER_CORP", session["id"], document_id, "foreign", 4)
    for path in ["../increment.py", ".env", ".git/config", "missing.py"]:
        with pytest.raises(ValueError):
            service.open("A123456", session["id"], path, "secret", 1)


async def test_document_updates_cancel_inference_and_source_drift_rejects_it(inline):
    coding, session, _ = inline
    model = Model(wait=True)
    service = coding.inline = InlineService(coding, model=model)
    opened = service.open("A123456", session["id"], "increment.py", "return value", 1)
    task = asyncio.create_task(service.complete("A123456", session["id"], opened["document_id"], 1, 12))
    await model.started.wait()
    service.update("A123456", session["id"], opened["document_id"], "new", 2)
    assert (await task)["status"] == "cancelled"
    model.started.clear()
    task = asyncio.create_task(service.complete("A123456", session["id"], opened["document_id"], 2, 3))
    await model.started.wait()
    (coding.projects.repository("A123456", session["id"]) / "increment.py").write_text("changed\n")
    model.finish.set()
    with pytest.raises(CodingConflict, match="changed"):
        await task
    assert not service._active["A123456"]


async def test_superseding_request_does_not_cancel_new_generation(inline):
    coding, session, _ = inline
    model = Model(wait=True)
    service = coding.inline = InlineService(coding, model=model)
    opened = service.open("A123456", session["id"], "increment.py", "x", 1)
    document_id = opened["document_id"]
    first = asyncio.create_task(service.complete("A123456", session["id"], document_id, 1, 1, "a" * 32))
    await model.started.wait()
    model.started.clear()
    second = asyncio.create_task(service.complete("A123456", session["id"], document_id, 1, 1, "b" * 32))
    await model.started.wait()
    assert (await first)["status"] == "cancelled"
    assert await service.cancel("A123456", session["id"], document_id, "a" * 32) == {"status": "superseded"}
    model.finish.set()
    assert (await second)["status"] == "completed"


async def test_inference_deadline_and_invalid_output(inline):
    coding, session, _ = inline
    service = coding.inline = InlineService(coding, model=Model(wait=True), timeout=0.01)
    opened = service.open("A123456", session["id"], "increment.py", "x", 1)
    assert (await service.complete("A123456", session["id"], opened["document_id"], 1, 1))["status"] == "timed_out"
    service.model = Model(content="x" * 2049)
    with pytest.raises(ValueError, match="oversized"):
        await service.complete("A123456", session["id"], opened["document_id"], 1, 1)


async def test_responses_content_blocks_supply_plain_inline_text(inline):
    coding, session, model = inline
    model.content = [{"type": "text", "text": " + 2"}]
    document = coding.inline.open("A123456", session["id"], "increment.py", "return value", 1)
    result = await coding.inline.complete("A123456", session["id"], document["document_id"], 1, 12)
    assert result["items"][0]["text"] == " + 2"


def test_document_api_requires_opt_in_and_scopes_buffers(settings):
    root = fixture_project(settings)
    app = create_app(settings=settings, graph_override=FakeGraph(), coding_runtime_factory=FixtureRuntime)
    with TestClient(app) as client:
        session = open_session(client, root)
        endpoint = f"/sessions/{session['id']}/documents"
        body = {"path": "increment.py", "content": "return value", "version": 1}
        assert client.post(endpoint, json=body).status_code == 409
        app.state.coding.inline.model = Model()
        opened = client.post(endpoint, json=body)
        assert opened.status_code == 201, opened.text
        document_id = opened.json()["document_id"]
        assert client.post(endpoint, json={**body, "version": True}).status_code == 422
        assert client.get(f"/sessions/{session['id']}/editor").json()["project"]["root"] == str(root)
        foreign = {"X-Corp-ID": "OTHER_CORP"}
        assert client.put(endpoint + "/" + document_id, headers=foreign, json={"content": "x", "version": 2}).status_code == 404
        completion = client.post(endpoint + "/" + document_id + "/complete", json={"version": 1, "offset_utf16": 12})
        assert completion.status_code == 200, completion.text
        assert client.delete(endpoint + "/" + document_id).status_code == 204
