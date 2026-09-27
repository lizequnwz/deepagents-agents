from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError

from data_analytics_agent import transcription
from data_analytics_agent.api import Services, create_app


def provider(monkeypatch, *, text=" Sales by month? ", error=None):
    create = AsyncMock(return_value=SimpleNamespace(text=text), side_effect=error)
    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    factory = AsyncMock()
    factory.__aenter__.return_value = client
    monkeypatch.setattr(transcription, "AsyncOpenAI", lambda **kw: factory)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return create, factory


async def test_transcription_sends_wav_and_closes_client(monkeypatch):
    create, client = provider(monkeypatch)
    response = await transcription.transcribe_audio(b"recorded wav", "whisper-1")
    assert response.text == "Sales by month?"
    create.assert_awaited_once_with(
        model="whisper-1", file=("question.wav", b"recorded wav", "audio/wav")
    )
    client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("text", ["", "   "])
async def test_no_speech(monkeypatch, text):
    provider(monkeypatch, text=text)
    with pytest.raises(HTTPException) as error:
        await transcription.transcribe_audio(b"wav", "whisper-1")
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "exception,status",
    [
        (APITimeoutError(request=httpx.Request("POST", "https://example.com")), 504),
        (APIConnectionError(request=httpx.Request("POST", "https://example.com")), 502),
    ],
)
async def test_provider_errors(monkeypatch, exception, status):
    _, client = provider(monkeypatch, error=exception)
    with pytest.raises(HTTPException) as error:
        await transcription.transcribe_audio(b"wav", "whisper-1")
    assert error.value.status_code == status
    client.__aexit__.assert_awaited_once()


def test_transcription_endpoint_does_not_start_agent_or_save_audio(
    test_settings, monkeypatch
):
    create, _ = provider(monkeypatch)
    services = Services(settings=test_settings)
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/transcriptions", content=b"wav", headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 200 and response.json() == {
            "text": "Sales by month?"
        }
        assert client.post("/api/transcriptions", content=b"").status_code == 422
        monkeypatch.setattr("data_analytics_agent.api.MAX_AUDIO_BYTES", 3)
        assert (
            client.post("/api/transcriptions", content=b"too long").status_code == 413
        )
        monkeypatch.delenv("OPENAI_API_KEY")
        assert client.post("/api/transcriptions", content=b"wav").status_code == 503
    create.assert_awaited_once()
    assert services.conversations.list() == []
    assert not list(services.storage.artifacts.rglob("*.wav"))


@pytest.mark.parametrize("with_attachment", [False, True])
def test_voice_populates_composer_once_without_submitting(monkeypatch, with_attachment):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from data_analytics_agent.ui.api_client import AgentAPIClient

    calls = []
    attachment = SimpleNamespace(name="sales.csv")
    native = st.chat_input

    def recorded(*args, **kwargs):
        value = native(*args, **kwargs)
        if not st.session_state.get("recording_delivered"):
            st.session_state["recording_delivered"] = True
            return SimpleNamespace(
                audio=SimpleNamespace(getvalue=lambda: b"recorded wav"),
                text="Keep this context" if with_attachment else "",
                files=[attachment] if with_attachment else [],
            )
        return value

    monkeypatch.setattr(st, "chat_input", recorded)
    monkeypatch.setattr(
        AgentAPIClient,
        "transcribe",
        lambda self, content: calls.append(content) or "Sales by month?",
    )
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.api_client import AgentAPIClient
from data_analytics_agent.ui.uploads import chat_submission
submission = chat_submission("Question", key="question", max_bytes=1000, client=AgentAPIClient("http://test"))
if submission:
    st.session_state["sent"] = submission.text
    st.session_state["sent_files"] = [file.name for file in submission.files]
""").run()
    assert not app.exception
    assert calls == [b"recorded wav"]
    assert app.chat_input[0].proto.accept_audio
    assert not app.get("audio_input")
    assert app.chat_input[0].proto.value == (
        "Keep this context\n\nSales by month?" if with_attachment else "Sales by month?"
    )
    assert "sent" not in app.session_state
    app.run()
    assert calls == [b"recorded wav"]
    app.chat_input[0].set_value("Edited question").run()
    assert app.session_state["sent"] == "Edited question"
    assert app.session_state["sent_files"] == (["sales.csv"] if with_attachment else [])
    assert "voice_question_pending" not in app.session_state
    assert "voice_question_files" not in app.session_state
    assert not any(
        isinstance(value, bytes) for value in app.session_state.filtered_state.values()
    )


def test_voice_failure_requires_explicit_retry(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from data_analytics_agent.ui.api_client import AgentAPIClient, APIError

    attempts = []
    native = st.chat_input

    def recorded(*args, **kwargs):
        value = native(*args, **kwargs)
        if not st.session_state.get("recording_delivered"):
            st.session_state["recording_delivered"] = True
            return SimpleNamespace(
                audio=SimpleNamespace(getvalue=lambda: b"wav"),
                text="",
                files=[],
            )
        return value

    def transcribe(self, content):
        attempts.append(content)
        if len(attempts) == 1:
            raise APIError("Transcription failed. Try again.")
        return "Recovered question"

    monkeypatch.setattr(st, "chat_input", recorded)
    monkeypatch.setattr(AgentAPIClient, "transcribe", transcribe)
    app = AppTest.from_string("""
from data_analytics_agent.ui.api_client import AgentAPIClient
from data_analytics_agent.ui.uploads import chat_submission
chat_submission("Question", key="question", max_bytes=1000, client=AgentAPIClient("http://test"))
""").run()
    assert not app.exception and app.error
    app.run()
    assert len(attempts) == 1
    app.button[0].click().run()
    assert not app.exception and not app.error, (
        attempts,
        app.session_state.filtered_state,
        [e.value for e in app.error],
    )
    assert len(attempts) == 2
    assert app.chat_input[0].proto.value == "Recovered question"


async def test_whisper_runnable_supports_langchain_binding_and_callbacks(monkeypatch):
    from langchain_core.callbacks import AsyncCallbackHandler

    create, _ = provider(monkeypatch)
    events = []

    class Observer(AsyncCallbackHandler):
        async def on_chain_start(self, serialized, inputs, **kwargs):
            events.append(kwargs.get("name"))

        async def on_chain_end(self, outputs, **kwargs):
            events.append(outputs)

    result = await transcription.whisper_transcriber.bind(
        model="custom-whisper"
    ).ainvoke(b"wav", config={"callbacks": [Observer()]})
    assert result == "Sales by month?"
    assert events == ["whisper_transcription", "Sales by month?"]
    assert create.call_args.kwargs["model"] == "custom-whisper"


async def test_cancelling_transcription_closes_provider_client(monkeypatch):
    import asyncio

    create, client = provider(monkeypatch)
    started = asyncio.Event()

    async def pending(**kwargs):
        started.set()
        await asyncio.Event().wait()

    create.side_effect = pending
    task = asyncio.create_task(transcription.transcribe_audio(b"wav", "whisper-1"))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.__aexit__.assert_awaited_once()
