import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from data_analytics_agent import api, source_routing
from data_analytics_agent.schemas import CoordinatorResponse
from tests.test_run_manager import Graph, Stream


@pytest.fixture
def routing_model(monkeypatch):
    model = Mock()
    invoke = AsyncMock()
    model.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(source_routing, "_build_chat_model", Mock(return_value=model))
    return model, invoke


@pytest.mark.parametrize(
    ("message", "source_id"),
    [
        ("Which artists have the most line revenue?", "chinook"),
        ("How many loans were approved?", "financial"),
    ],
)
async def test_router_sends_question_and_business_metadata_once(
    test_settings, routing_model, message, source_id
):
    model, invoke = routing_model
    invoke.return_value = {"source_id": source_id}
    candidates = [
        {
            "source_id": "chinook",
            "name": "Chinook",
            "description": "Music store",
            "examples": ["Which artists have the most line revenue?"],
            "datasets": ["artists"],
            "metrics": ["line_revenue"],
        },
        {
            "source_id": "financial",
            "name": "Financial services",
            "description": "Retail banking",
            "examples": ["How many loans were approved?"],
            "datasets": ["loans"],
            "metrics": ["loan_count"],
        },
    ]

    assert (
        await source_routing.select_source(test_settings, message, candidates)
        == source_id
    )

    model.with_structured_output.assert_called_once()
    assert model.with_structured_output.call_args.kwargs == {
        "method": "function_calling"
    }
    invoke.assert_awaited_once()
    system, payload = invoke.call_args.args[0]
    assert isinstance(system, SystemMessage)
    assert isinstance(payload, HumanMessage)
    assert json.loads(payload.content) == {
        "question": message,
        "ready_sources": candidates,
    }


@pytest.mark.parametrize(
    "result", [None, {}, {"source_id": "unlisted"}, {"source_id": 5}]
)
async def test_router_rejects_invalid_or_unlisted_results(
    test_settings, routing_model, result
):
    _, invoke = routing_model
    invoke.return_value = result

    with pytest.raises(
        source_routing.SourceRoutingError, match="Choose a data source manually"
    ):
        await source_routing.select_source(
            test_settings, "Question", [{"source_id": "test"}]
        )


async def test_router_times_out(test_settings, routing_model, monkeypatch):
    _, invoke = routing_model
    monkeypatch.setattr(source_routing, "_ROUTING_TIMEOUT_SECONDS", 0.01)

    async def stall(_messages):
        await asyncio.Event().wait()

    invoke.side_effect = stall
    with pytest.raises(source_routing.SourceRoutingError) as error:
        await source_routing.select_source(
            test_settings, "Question", [{"source_id": "test"}]
        )
    assert isinstance(error.value.__cause__, TimeoutError)


def test_auto_start_binds_source_and_reuses_it_on_follow_up(
    test_settings, routing_model
):
    _, invoke = routing_model
    invoke.return_value = {"source_id": "test_alt"}
    graph = Graph([Stream(CoordinatorResponse(answer="Answer")) for _ in range(2)])
    services = api.Services(settings=test_settings, agent=graph)
    question = "Which artists are in the alternate catalog?"

    with TestClient(api.create_app(services)) as client:
        start = client.post("/api/conversations/start", json={"message": question})
        assert start.status_code == 202, start.text
        started = start.json()
        assert started["status"] == "started"
        assert started["source_id"] == "test_alt"
        thread = started["thread_id"]
        run = client.get(f"/api/runs/{started['run_id']}").json()
        assert (run["source_id"], run["question"], run["status"]) == (
            "test_alt",
            question,
            "completed",
        )

        follow_up = client.post(
            f"/api/conversations/{thread}/messages",
            json={"message": "And their names?"},
        )
        assert follow_up.status_code == 202, follow_up.text
        conversation = client.get(f"/api/conversations/{thread}").json()
        assert conversation["source_id"] == "test_alt"
        assert [turn["user_message"] for turn in conversation["turns"]] == [
            question,
            "And their names?",
        ]
        invoke.assert_awaited_once()

    routing_payload = json.loads(invoke.call_args.args[0][1].content)
    candidates = {
        candidate["source_id"]: candidate
        for candidate in routing_payload["ready_sources"]
    }
    assert candidates.keys() == {"test", "test_alt"}
    assert candidates["test_alt"] == {
        "source_id": "test_alt",
        "name": "Alternate test source",
        "description": "Second source for conversation binding tests.",
        "examples": [],
        "datasets": ["artists"],
        "metrics": ["artist_count"],
    }


def test_ambiguous_start_preserves_question_for_manual_selection(
    test_settings, routing_model
):
    _, invoke = routing_model
    invoke.return_value = {"source_id": None}
    services = api.Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Answer"))]),
    )
    question = "How many artists are there?"

    with TestClient(api.create_app(services)) as client:
        start = client.post("/api/conversations/start", json={"message": question})
        assert start.status_code == 200, start.text
        result = start.json()
        assert result["status"] == "needs_source"
        assert result["reason"] == "ambiguous"
        assert result["prompt"]
        assert {choice["source_id"] for choice in result["choices"]} == {
            "test",
            "test_alt",
        }
        assert not services.conversations.list()
        assert not services.storage.load("runs", dict)

        manual = client.post(
            "/api/conversations/start",
            json={"message": question, "source_id": "test_alt"},
        )
        assert manual.status_code == 202, manual.text
        run = client.get(f"/api/runs/{manual.json()['run_id']}").json()
        assert (run["source_id"], run["question"]) == ("test_alt", question)
        invoke.assert_awaited_once()


@pytest.mark.parametrize(
    "question",
    [
        "What data sources and questions I can ask?",
        "Which data source should I use for this question?",
        "List the available data sources and example questions.",
    ],
)
def test_source_guidance_works_without_a_model(
    test_settings, routing_model, monkeypatch, question
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _, invoke = routing_model
    services = api.Services(settings=replace(test_settings, model_provider="openai"))

    with TestClient(api.create_app(services)) as client:
        reply = client.post("/api/conversations/start", json={"message": question})

    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["status"] == "needs_source"
    assert result["reason"] == "guidance"
    assert "example question" in result["prompt"]
    assert result["choices"] == [
        {"source_id": "test", "label": "Test source"},
        {"source_id": "test_alt", "label": "Alternate test source"},
    ]
    assert not services.conversations.list()
    assert not services.storage.load("runs", dict)
    invoke.assert_not_awaited()


def test_source_guidance_offers_upload_when_no_source_is_ready(
    test_settings, routing_model
):
    _, invoke = routing_model
    catalog = test_settings.load_catalog()
    sources = {
        source_id: replace(source, target={"path": "db/missing.sqlite"})
        for source_id, source in catalog.sources.items()
    }
    services = api.Services(
        settings=test_settings, catalog=replace(catalog, sources=sources)
    )

    with TestClient(api.create_app(services)) as client:
        reply = client.post(
            "/api/conversations/start", json={"message": "Which sources are available?"}
        )

    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["reason"] == "guidance"
    assert "Attach a data table" in result["prompt"]
    assert result["choices"] == []
    assert not services.conversations.list()
    assert not services.storage.load("runs", dict)
    invoke.assert_not_awaited()


def test_source_guidance_does_not_match_analytical_question():
    assert not source_routing.is_source_guidance(
        "Which data source had the highest revenue last year?"
    )


@pytest.mark.parametrize("all_unready", [False, True])
def test_auto_start_rejects_unready_sources(test_settings, routing_model, all_unready):
    _, invoke = routing_model
    invoke.return_value = {"source_id": "test_alt"}
    catalog = test_settings.load_catalog()
    bad_source_ids = {"test", "test_alt"} if all_unready else {"test_alt"}
    sources = {
        source_id: replace(source, target={"path": "db/missing.sqlite"})
        if source_id in bad_source_ids
        else source
        for source_id, source in catalog.sources.items()
    }
    services = api.Services(
        settings=test_settings,
        agent=Graph([]),
        catalog=replace(catalog, sources=sources),
    )

    with TestClient(api.create_app(services)) as client:
        start = client.post("/api/conversations/start", json={"message": "Question"})
        assert start.status_code == 503, start.text
        assert not services.conversations.list()
        assert not services.storage.load("runs", dict)

    if all_unready:
        invoke.assert_not_awaited()
    else:
        invoke.assert_awaited_once()
        payload = json.loads(invoke.call_args.args[0][1].content)
        assert [source["source_id"] for source in payload["ready_sources"]] == ["test"]


def test_auto_start_provider_failure_is_safe_and_can_be_retried_manually(
    test_settings, routing_model
):
    _, invoke = routing_model
    invoke.side_effect = RuntimeError("private provider error")
    services = api.Services(settings=test_settings, agent=Graph([]))

    with TestClient(api.create_app(services)) as client:
        start = client.post("/api/conversations/start", json={"message": "Question"})
        assert start.status_code == 503, start.text
        assert "private provider error" not in start.text
        assert not services.conversations.list()
        assert not services.storage.load("runs", dict)
        assert client.post("/api/conversations", json={}).status_code == 422
        manual = client.post("/api/conversations", json={"source_id": "test"})
        assert manual.status_code == 201, manual.text
        invoke.assert_awaited_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "  "},
        {"message": "Question", "source_id": "unknown"},
        {"message": "Question", "source_id": "upload:other-chat"},
    ],
)
def test_start_rejects_invalid_input_without_routing(
    test_settings, routing_model, payload
):
    _, invoke = routing_model
    services = api.Services(settings=test_settings, agent=Graph([]))

    with TestClient(api.create_app(services)) as client:
        response = client.post("/api/conversations/start", json=payload)
        assert response.status_code == 422, response.text
        assert not services.conversations.list()
        invoke.assert_not_awaited()
