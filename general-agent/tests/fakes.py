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
                    {"lc_agent_name": "general-agent", "run_id": "root-message"},
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
                            name="general-agent",
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
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {"event": "started", "graph_name": "general-purpose"},
            },
        },
        {
            "method": "tools",
            "params": {
                "namespace": ["general-purpose:one"],
                "data": {
                    "event": "tool-started",
                    "tool_name": "execute",
                    "tool_call_id": "tool-one",
                    "input": {"command": "python work.py"},
                },
            },
        },
        {
            "method": "tools",
            "params": {
                "namespace": ["general-purpose:one"],
                "data": {
                    "event": "tool-finished",
                    "tool_name": "execute",
                    "tool_call_id": "tool-one",
                    "output": "ok\n[Command succeeded with exit code 0]",
                },
            },
        },
        {
            "method": "values",
            "params": {
                "namespace": ["general-purpose:one"],
                "data": {
                    "messages": [
                        AIMessage(
                            content="subagent result",
                            id="sub-message",
                            name="general-purpose",
                        )
                    ]
                },
            },
        },
        {
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {"event": "completed", "graph_name": "general-purpose"},
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
            if event.get("method") == "lifecycle" and data.get("event") == "started":
                for callback in self.callbacks:
                    callback.on_chat_model_start(
                        {}, [[]], run_id="sub-call", metadata={"lc_agent_name": "general-purpose"}
                    )
            if event.get("method") == "values" and not namespace:
                message = data["messages"][0]
                response = LLMResult(
                    generations=[[ChatGeneration(message=message)]]
                )
                for callback in self.callbacks:
                    callback.on_llm_end(response, run_id="root-call")
            if event.get("method") == "values" and namespace:
                message = data["messages"][0]
                response = LLMResult(
                    generations=[[ChatGeneration(message=message)]]
                )
                for callback in self.callbacks:
                    callback.on_llm_end(response, run_id="sub-call")
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
                {}, [[]], run_id="root-call", metadata={"lc_agent_name": "general-agent"}
            )
        stream = FakeEventStream(blocked=self.blocked, callbacks=callbacks)
        self.streams.append(stream)
        return stream
