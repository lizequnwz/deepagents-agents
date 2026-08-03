from __future__ import annotations

import logging
import re
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from general_agent.api import create_app
from general_agent.observability import (
    configure_logging,
    log_event,
    shutdown_logging,
)
from tests.fakes import FakeGraph


class ImmediateTimeoutGraph:
    async def astream_events(self, value, config, *, version):
        del value, config, version
        raise TimeoutError


def _start_text_run(client: TestClient, text: str = "work") -> str:
    conversation_id = client.post("/conversations", json={}).json()[
        "conversation_id"
    ]
    return client.post(
        f"/conversations/{conversation_id}/messages",
        data={"text": text},
    ).json()["run_id"]


def _wait_for_terminal_run(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        current = client.get(f"/runs/{run_id}").json()
        if current["status"] not in {"running", "stopping"}:
            return current
        time.sleep(0.01)
    return current


def test_human_readable_log_redacts_secrets_and_exception_messages(
    settings, monkeypatch
) -> None:
    secret = "SENSITIVE-API-SECRET-123"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    configure_logging(settings)
    test_logger = logging.getLogger("general_agent.test")
    try:
        log_event(
            test_logger,
            logging.INFO,
            "test.operation.completed",
            run_id="run_test",
            duration_ms=12,
            note="two words",
        )
        try:
            raise RuntimeError(f"private advisor value {secret}")
        except RuntimeError:
            log_event(
                test_logger,
                logging.ERROR,
                "test.operation.failed",
                exception_type="RuntimeError",
                exc_info=True,
            )
    finally:
        shutdown_logging()

    contents = settings.api_log.read_text(encoding="utf-8")
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} INFO\s+"
        r"test\.operation\.completed run_id=run_test duration_ms=12",
        contents,
    )
    assert "note='two words'" in contents
    assert "Traceback (most recent call last):" in contents
    assert contents.rstrip().endswith("RuntimeError")
    assert "private advisor value" not in contents
    assert secret not in contents


def test_log_file_rotates(settings) -> None:
    configured = replace(settings, log_max_bytes=300, log_backup_count=2)
    configure_logging(configured)
    test_logger = logging.getLogger("general_agent.test")
    try:
        for index in range(30):
            log_event(
                test_logger,
                logging.INFO,
                "test.rotation.record",
                index=index,
                duration_ms=index,
            )
    finally:
        shutdown_logging()

    assert configured.api_log.is_file()
    assert configured.api_log.with_name("api.log.1").is_file()
    assert len(list(configured.logs_root.glob("api.log*"))) <= 3


def test_api_and_agent_lifecycle_share_safe_correlated_log(settings) -> None:
    graph = FakeGraph()
    app = create_app(settings=settings, graph_override=graph)
    sensitive_prompt = "PRIVATE ADVISOR PROMPT 991"
    sensitive_filename = "private-advisors-991.csv"

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.headers["X-Request-ID"].startswith("req_")
        conversation_response = client.post("/conversations", json={})
        request_id = conversation_response.headers["X-Request-ID"]
        conversation_id = conversation_response.json()["conversation_id"]
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"text": sensitive_prompt},
            files=[
                (
                    "files",
                    (
                        sensitive_filename,
                        b"FIRST_NAME,LAST_NAME\nAvery,Stone\n",
                        "text/csv",
                    ),
                )
            ],
        )
        run_id = sent.json()["run_id"]
        for _ in range(100):
            current = client.get(f"/runs/{run_id}").json()
            if current["status"] != "running":
                break
            time.sleep(0.01)
        assert current["status"] == "completed"

    contents = settings.api_log.read_text(encoding="utf-8")
    assert f"api.request.completed request_id={request_id}" in contents
    assert "method=POST route=/conversations status=200" in contents
    assert f"agent.run.started" in contents
    assert f"run_id={run_id}" in contents
    assert "agent.model.started" in contents
    assert "agent.model.completed" in contents
    assert "agent.tool.started" in contents
    assert "agent.tool.completed" in contents
    assert "api.request.completed" in contents
    assert "route=/health" not in contents
    assert "route=/runs/{run_id}" not in contents
    assert sensitive_prompt not in contents
    assert sensitive_filename not in contents
    assert "att_test" not in contents
    assert "ams_test" not in contents


def test_unexpected_api_error_is_logged_without_its_message(settings) -> None:
    secret = "PRIVATE API FAILURE 223"
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        def fail(_corp_id):
            raise RuntimeError(secret)

        client.app.state.store.list_conversations = fail
        response = client.get("/conversations")
        request_id = response.headers["X-Request-ID"]
        assert response.status_code == 500

    contents = settings.api_log.read_text(encoding="utf-8")
    assert "api.request.failed" in contents
    assert f"request_id={request_id}" in contents
    assert "route=/conversations status=500" in contents
    assert "exception_type=RuntimeError" in contents
    assert secret not in contents


def test_validation_failure_is_logged_as_warning(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={}).json()[
            "conversation_id"
        ]
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"text": ""},
        )
        request_id = response.headers["X-Request-ID"]
        assert response.status_code == 400

    contents = settings.api_log.read_text(encoding="utf-8")
    assert (
        f"WARNING api.request.completed request_id={request_id} "
        "method=POST route=/conversations/{conversation_id}/messages status=400"
        in contents
    )


def test_debug_log_includes_polling_and_cancellation(settings) -> None:
    configured = replace(settings, log_level="DEBUG")
    graph = FakeGraph(blocked=True)
    app = create_app(settings=configured, graph_override=graph)
    with TestClient(app) as client:
        client.get("/health")
        conversation_id = client.post("/conversations", json={}).json()[
            "conversation_id"
        ]
        run_id = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"text": "wait"},
        ).json()["run_id"]
        for _ in range(100):
            client.get(f"/runs/{run_id}")
            if graph.streams:
                break
            time.sleep(0.01)
        assert graph.streams
        stopped = client.post(f"/runs/{run_id}/stop")
        assert stopped.status_code == 200
        for _ in range(100):
            current = client.get(f"/runs/{run_id}").json()
            if current["status"] == "stopped":
                break
            time.sleep(0.01)
        assert current["status"] == "stopped"

    contents = configured.api_log.read_text(encoding="utf-8")
    assert "DEBUG api.request.completed" in contents
    assert "route=/health status=200" in contents
    assert "route=/runs/{run_id} status=200" in contents
    assert "agent.run.stop_requested" in contents
    assert "agent.run.cancelled" in contents
    assert "agent.stream.aborted" in contents


def test_timeout_and_token_budget_failures_are_logged(settings) -> None:
    timeout_app = create_app(
        settings=settings,
        graph_override=ImmediateTimeoutGraph(),
    )
    with TestClient(timeout_app) as client:
        timeout_run_id = _start_text_run(client, "timeout safely")
        timeout_run = _wait_for_terminal_run(client, timeout_run_id)
        assert timeout_run["status"] == "failed"

    timeout_log = settings.api_log.read_text(encoding="utf-8")
    assert "agent.run.timed_out" in timeout_log
    assert f"run_id={timeout_run_id}" in timeout_log

    budget_settings = replace(settings, max_run_tokens=5)
    budget_app = create_app(
        settings=budget_settings,
        graph_override=FakeGraph(),
    )
    with TestClient(budget_app) as client:
        budget_run_id = _start_text_run(client, "budget safely")
        budget_run = _wait_for_terminal_run(client, budget_run_id)
        assert budget_run["status"] == "failed"

    budget_log = budget_settings.api_log.read_text(encoding="utf-8")
    assert "agent.token_budget.exceeded" in budget_log
    assert f"run_id={budget_run_id}" in budget_log
    assert "reported_tokens=10 max_tokens=5" in budget_log
