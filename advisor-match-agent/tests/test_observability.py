from __future__ import annotations

import logging
import re

from fastapi.testclient import TestClient

from general_agent.api import create_app
from general_agent.observability import configure_logging, log_event, shutdown_logging
from tests.fakes import FakeGraph


def test_human_readable_log_redacts_exception_messages(settings, monkeypatch) -> None:
    secret = "SENSITIVE-API-SECRET-123"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    configure_logging(settings)
    logger = logging.getLogger("general_agent.test")
    try:
        log_event(logger, logging.INFO, "test.operation.completed", run_id="run_test")
        try:
            raise RuntimeError(f"private advisor value {secret}")
        except RuntimeError:
            log_event(
                logger,
                logging.ERROR,
                "test.operation.failed",
                exception_type="RuntimeError",
                exc_info=True,
            )
    finally:
        shutdown_logging()
    contents = settings.api_log.read_text(encoding="utf-8")
    assert re.search(r"INFO\s+test\.operation\.completed", contents)
    assert secret not in contents
    assert "private advisor value" not in contents


def test_api_request_logs_do_not_include_user_payload(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    sensitive = "PRIVATE ADVISOR PROMPT 991"
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={}).json()["conversation_id"]
        response = client.post(
            f"/conversations/{conversation_id}/messages", data={"text": sensitive}
        )
        assert response.status_code == 200
    contents = settings.api_log.read_text(encoding="utf-8")
    assert "api.request.completed" in contents
    assert sensitive not in contents


def test_unexpected_api_error_is_safely_logged(settings) -> None:
    app = create_app(settings=settings, graph_override=FakeGraph())
    with TestClient(app) as client:
        def fail(_corp_id):
            raise RuntimeError("PRIVATE FAILURE")

        client.app.state.store.list_conversations = fail
        response = client.get("/conversations")
        assert response.status_code == 500
    contents = settings.api_log.read_text(encoding="utf-8")
    assert "api.request.failed" in contents
    assert "PRIVATE FAILURE" not in contents
