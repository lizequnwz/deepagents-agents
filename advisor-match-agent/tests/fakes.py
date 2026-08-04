from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any


class FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class FakeGraph:
    def __init__(self, *, blocked: bool = False, failure: Exception | None = None) -> None:
        self.blocked = blocked
        self.failure = failure
        self.started = asyncio.Event()
        self.calls: list[tuple[Any, Any, str]] = []
        self.checkpointer = FakeCheckpointer()

    async def astream(self, value, config, *, stream_mode):
        self.calls.append((value, config, stream_mode))
        self.started.set()
        if self.failure:
            raise self.failure
        if self.blocked:
            await asyncio.Event().wait()
        if isinstance(stream_mode, list):
            yield ("tasks", {"id": "task-1", "name": "capabilities", "input": {}})
            yield ("updates", {"capabilities": {"response": "Finished"}})
            yield (
                "tasks",
                {
                    "id": "task-1",
                    "name": "capabilities",
                    "error": None,
                    "result": {"response": "Finished"},
                    "interrupts": [],
                },
            )
        else:
            yield {"capabilities": {"response": "Finished"}}

    async def aget_state(self, _config):
        return SimpleNamespace(tasks=[])
