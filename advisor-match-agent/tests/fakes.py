from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult


def completed_events() -> list[dict[str, Any]]:
    return [
        {
            "method": "messages",
            "params": {
                "namespace": [],
                "data": (
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "Finished"},
                    },
                    {"lc_agent_name": "advisor-match-agent", "run_id": "root-message"},
                ),
            },
        },
        {
            "method": "values",
            "params": {
                "namespace": [],
                "data": {
                    "todos": [{"content": "Inspect", "status": "completed"}],
                    "messages": [
                        AIMessage(
                            content="Finished",
                            id="root-message",
                            name="advisor-match-agent",
                            usage_metadata={
                                "input_tokens": 8,
                                "output_tokens": 2,
                                "total_tokens": 10,
                            },
                        )
                    ],
                },
            },
        },
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "data": {
                    "event": "tool-started",
                    "tool_name": "create_advisor_match",
                    "tool_call_id": "tool-one",
                    "input": {"input_virtual_path": "/uploads/advisors.csv"},
                },
            },
        },
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "data": {
                    "event": "tool-finished",
                    "tool_name": "create_advisor_match",
                    "tool_call_id": "tool-one",
                    "output": {"match_session_id": "ams_test"},
                },
            },
        },
    ]


class FakeEventStream:
    def __init__(self, *, blocked: bool = False, callbacks: list[Any] | None = None) -> None:
        self.blocked = blocked
        self.callbacks = callbacks or []
        self.aborted = asyncio.Event()

    async def __aiter__(self):
        if self.blocked:
            await self.aborted.wait()
            return
        for event in completed_events():
            data = (event.get("params") or {}).get("data") or {}
            namespace = (event.get("params") or {}).get("namespace") or []
            if event.get("method") == "values" and not namespace:
                message = data["messages"][0]
                response = LLMResult(
                    generations=[[ChatGeneration(message=message)]]
                )
                for callback in self.callbacks:
                    callback.on_llm_end(response, run_id="root-call")
            yield event

    async def output(self):
        return {"messages": [AIMessage(content="Finished")]}

    async def abort(self) -> None:
        self.aborted.set()


class FakeGraph:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.streams: list[FakeEventStream] = []
        self.calls: list[tuple[Any, Any, str]] = []

    async def astream_events(self, value, config, *, version):
        self.calls.append((value, config, version))
        callbacks = list(config.get("callbacks") or [])
        for callback in callbacks:
            callback.on_chat_model_start(
                {}, [[]], run_id="root-call", metadata={"lc_agent_name": "advisor-match-agent"}
            )
        stream = FakeEventStream(blocked=self.blocked, callbacks=callbacks)
        self.streams.append(stream)
        return stream
