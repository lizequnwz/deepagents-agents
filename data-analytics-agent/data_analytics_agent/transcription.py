"""LangChain Whisper runnable and HTTP boundary; audio stays in memory."""

import os

from openai import AsyncOpenAI, APIError, APITimeoutError, AuthenticationError
from fastapi import HTTPException
from pydantic import BaseModel
from langchain_core.runnables import RunnableLambda

MAX_AUDIO_BYTES = 24 * 1024 * 1024


class TranscriptionResponse(BaseModel):
    text: str


async def _whisper_transcription(content: bytes, *, model: str) -> str:
    """Native async provider call; failures propagate to the calling workflow."""
    async with AsyncOpenAI(timeout=60, max_retries=0) as client:
        transcript = await client.audio.transcriptions.create(
            model=model,
            file=("question.wav", content, "audio/wav"),
        )
    return transcript.text.strip()


# Whisper uses the audio endpoint, not a chat-model interface. RunnableLambda
# provides LangChain composition, callbacks, and async invocation without codecs.
whisper_transcriber = RunnableLambda(
    _whisper_transcription, name="whisper_transcription"
)


async def transcribe_audio(content: bytes, model: str) -> TranscriptionResponse:
    if not content:
        raise HTTPException(422, "Record a question before transcribing.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too large. Record a shorter question.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            503, "Voice input requires OPENAI_API_KEY on the API server."
        )
    try:
        text = await whisper_transcriber.ainvoke(content, model=model)
    except AuthenticationError as exc:
        raise HTTPException(
            503, "The transcription provider rejected the configured API key."
        ) from exc
    except APITimeoutError as exc:
        raise HTTPException(504, "Transcription timed out. Try again.") from exc
    except APIError as exc:
        raise HTTPException(
            502, "Transcription failed. Try again or type your question."
        ) from exc
    if not text:
        raise HTTPException(422, "No speech was recognized. Try recording again.")
    return TranscriptionResponse(text=text)
