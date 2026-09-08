"""Durable input, publication races, and clarification on the real harness."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from tests.test_agent_workflow import AnalystModel
from data_analytics_agent.api import Services, create_app
from data_analytics_agent.stores import RunStore
from data_analytics_agent.schemas import FinalAnswer
from data_analytics_agent.steering import PendingCorrections


def test_corrections_are_ordered_durable_and_block_publication(tmp_path):
    from data_analytics_agent.persistence import LocalStorage

    runs = RunStore(LocalStorage(tmp_path))
    run = runs.create("thread", "test", "Original")
    first = runs.accept_correction(run, "Only August")
    second = runs.accept_correction(run, "Use net revenue")
    reloaded = RunStore(LocalStorage(tmp_path))
    assert [c.message_id for c in reloaded.get(run).corrections] == [
        first.message_id,
        second.message_id,
    ]
    with pytest.raises(PendingCorrections):
        reloaded.publish(run, FinalAnswer(answer="Old answer"))
    reloaded.mark_corrections_applied(
        run, [first.message_id, second.message_id], "coordinator"
    )
    reloaded.publish(run, FinalAnswer(answer="Updated answer"))
    assert reloaded.accept_correction(run, "Next month") is None
    assert reloaded.get(run).question == "Original"


def test_correction_publication_race_has_explicit_outcome():
    runs = RunStore()
    run = runs.create("thread", "test", "Original")
    barrier = Barrier(2)

    def publish():
        barrier.wait()
        try:
            runs.publish(run, FinalAnswer(answer="Published"))
            return "published"
        except PendingCorrections:
            return "pending"

    def correct():
        barrier.wait()
        return runs.accept_correction(run, "Correction")

    with ThreadPoolExecutor(2) as pool:
        publication, correction = pool.submit(publish), pool.submit(correct)
        outcome, accepted = publication.result(), correction.result()
    assert (outcome == "pending" and accepted is not None) or (
        outcome == "published" and accepted is None
    )


class ClarifyingModel(AnalystModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        answers = [
            m
            for m in messages
            if isinstance(m, ToolMessage) and m.name == "request_clarification"
        ]
        if not answers:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_clarification",
                        "args": {
                            "question": "Which revenue definition?",
                            "choices": ["Net", "Gross"],
                        },
                        "id": "clarify",
                    }
                ],
            )
        else:
            assert "Net" in str(answers[-1].content)
            message = AIMessage(
                content=json.dumps({"answer": "I will use net revenue."})
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_clarification_api_resumes_same_run(test_settings, monkeypatch):
    from data_analytics_agent import coordinator

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *a, **k: ClarifyingModel()
    )
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    with TestClient(create_app(services)) as api:
        response = api.post(
            f"/api/conversations/{thread}/messages", json={"message": "Explain revenue"}
        )
        run = response.json()["run_id"]
        snapshot = api.get(f"/api/runs/{run}").json()
        assert snapshot["status"] == "clarification_required", snapshot.get("error")
        assert snapshot["clarification"]["question"] == "Which revenue definition?"
        assert not snapshot["findings"] and not snapshot["approval"]
        answered = api.post(f"/api/runs/{run}/clarification", json={"message": "Net"})
        assert answered.status_code == 202
        snapshot = api.get(f"/api/runs/{run}").json()
        assert snapshot["status"] == "completed", snapshot.get("error")
        assert snapshot["answer"]["answer"] == "I will use net revenue."
        assert snapshot["corrections"][0]["message"] == "Net"
        assert (
            api.post(
                f"/api/runs/{run}/clarification", json={"message": "Gross"}
            ).status_code
            == 409
        )


def test_correction_api_acknowledges_pending_and_follow_up(test_settings):
    from tests.test_run_manager import Graph, Stream
    from data_analytics_agent.schemas import CoordinatorResponse

    services = Services(
        settings=test_settings,
        agent=Graph([Stream(CoordinatorResponse(answer="Follow-up"))]),
    )
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Original")
    services.conversations.begin_run(thread, run)
    with TestClient(create_app(services)) as api:
        response = api.post(
            f"/api/runs/{run}/corrections", json={"message": "Corrected"}
        )
        assert response.status_code == 202
        assert response.json()["disposition"] == "pending"
        assert (
            response.json()["message_id"]
            == services.runs.get(run).corrections[0].message_id
        )
        services.runs.mark_corrections_applied(
            run, [response.json()["message_id"]], "coordinator"
        )
        services.runs.publish(run, FinalAnswer(answer="Saved findings"))
        response = api.post(
            f"/api/runs/{run}/corrections", json={"message": "Follow-up"}
        )
        assert response.status_code == 202
        follow_up = response.json()["run_id"]
        assert response.json()["disposition"] == "follow_up" and follow_up != run
        assert services.runs.get(follow_up).question == "Follow-up"
        assert services.runs.get(run).findings.answer == "Saved findings"


def test_resuming_with_changed_catalog_is_rejected(tmp_path):
    from data_analytics_agent.persistence import LocalStorage

    runs = RunStore(LocalStorage(tmp_path))
    run = runs.create("thread", "test", "Original")
    runs.bind_catalog(run, "original-hash")
    reloaded = RunStore(LocalStorage(tmp_path))
    with pytest.raises(ValueError, match="semantic catalog changed"):
        reloaded.bind_catalog(run, "new-hash")


class CorrectableSQLModel(AnalystModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import SystemMessage, HumanMessage

        system = " ".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )
        if "You are the text-to-SQL specialist" not in system:
            return super()._generate(messages, stop, run_manager, **kwargs)
        evidence = None
        for message in messages:
            if isinstance(message, ToolMessage) and message.name == "execute_sql":
                try:
                    candidate = json.loads(message.content)
                    if candidate.get("result_id"):
                        evidence = candidate
                except (ValueError, AttributeError):
                    pass
        corrected = any(
            "above 10" in str(m.content)
            for m in messages
            if isinstance(m, HumanMessage)
        )
        if evidence:
            name, arguments, identifier = (
                "SQLAnalysisResponse",
                {
                    "answer": "There are no artists in the selected population.",
                    "sql": evidence["executed_sql"],
                    "result_id": evidence["result_id"],
                },
                "sql-answer",
            )
        else:
            name, arguments, identifier = (
                "execute_sql",
                {
                    "query": "SELECT COUNT(*) AS artists FROM Artist"
                    + (" WHERE ArtistId > 10" if corrected else ""),
                    "purpose": "Count the selected artists",
                },
                "revised" if corrected else "original",
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": name, "args": arguments, "id": identifier}
                        ],
                    )
                )
            ]
        )


def test_correction_invalidates_pending_sql_approval(test_settings, monkeypatch):
    from dataclasses import replace
    from data_analytics_agent import coordinator

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *a, **k: CorrectableSQLModel()
    )
    services = Services(settings=replace(test_settings, require_sql_approval=True))
    thread = services.conversations.create("test")
    with TestClient(create_app(services)) as api:
        run = api.post(
            f"/api/conversations/{thread}/messages", json={"message": "Count artists"}
        ).json()["run_id"]
        assert services.runs.get(run).status == "approval_required"
        response = api.post(
            f"/api/runs/{run}/corrections", json={"message": "Only artist IDs above 10"}
        )
        assert response.status_code == 202
        snapshot = services.runs.get(run)
        assert snapshot.status == "approval_required", snapshot.error
        assert "WHERE ArtistId > 10" in snapshot.approval.query
        assert not services.results.list_for_conversation(thread, source_id="test")
        api.post(
            f"/api/runs/{run}/decisions", json={"decisions": [{"action": "approve"}]}
        )
        snapshot = services.runs.get(run)
        assert snapshot.status == "completed", snapshot.error
        evidence = services.results.list_for_conversation(thread, source_id="test")
        assert len(evidence) == 1 and "WHERE ArtistId > 10" in evidence[0].executed_sql
        assert "above 10" in evidence[0].originating_question
        assert set(snapshot.corrections[0].delivered_to) == {
            "text-to-sql",
            "coordinator",
        }


def test_corrections_and_nested_approval_survive_service_restart(
    test_settings, monkeypatch
):
    from dataclasses import replace
    from data_analytics_agent import coordinator

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *a, **k: CorrectableSQLModel()
    )
    settings = replace(test_settings, require_sql_approval=True)
    first = Services(settings=settings)
    thread = first.conversations.create("test")
    with TestClient(create_app(first)) as api:
        run = api.post(
            f"/api/conversations/{thread}/messages", json={"message": "Count artists"}
        ).json()["run_id"]
        one = api.post(
            f"/api/runs/{run}/corrections", json={"message": "Only artist IDs above 10"}
        ).json()["message_id"]
        two = api.post(
            f"/api/runs/{run}/corrections",
            json={"message": "Keep that threshold and count distinct IDs"},
        ).json()["message_id"]
        assert first.runs.get(run).status == "approval_required"
    second = Services(settings=settings)
    assert [c.message_id for c in second.runs.get(run).corrections] == [one, two]
    with TestClient(create_app(second)) as api:
        response = api.post(
            f"/api/runs/{run}/decisions", json={"decisions": [{"action": "approve"}]}
        )
        assert response.status_code == 202
        snapshot = second.runs.get(run)
        assert snapshot.status == "completed", snapshot.error
        assert len(second.results.list_for_conversation(thread, source_id="test")) == 1
        assert [c.message_id for c in snapshot.corrections] == [one, two]
        assert all("coordinator" in c.delivered_to for c in snapshot.corrections)
