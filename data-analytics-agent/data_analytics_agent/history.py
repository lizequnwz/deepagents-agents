"""Delete conversation workspaces and their application-owned artifacts."""

import json
from pathlib import Path

from fastapi import HTTPException
from data_analytics_agent.schemas import RunStatus


async def delete_history(services, thread_ids: set[str]) -> dict:
    conversations = [services.conversations.get(key) for key in thread_ids]
    if thread_ids & services.deleting_conversations:
        raise HTTPException(409, "History deletion is already in progress.")
    run_ids = {key for conversation in conversations for key in conversation.run_ids}
    for key in run_ids:
        run = services.runs.get(key)
        task = services._manager.tasks.get(key) if services._manager else None
        if (
            run.status in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.STOPPING}
            or services.runs.workers_active(key)
            or (task and not task.done())
        ):
            raise HTTPException(
                409,
                "Stop active work and wait for it to pause before deleting history.",
            )
    services.deleting_conversations.update(thread_ids)
    try:
        storage = services.storage
        records = []
        paths = set()

        def collect_paths(kind, value):
            candidates = []
            if kind == "datasets":
                candidates.append(value.get("parquet_path"))
            elif kind == "reports":
                candidates.append(value.get("html_path"))
            executions = (
                value.get("python_executions", [])
                if kind == "runs"
                else value.get("analysis", {}).get("executions", [])
                if kind == "analyses"
                else []
            )
            candidates.extend(
                output.get("image_path")
                for execution in executions
                for output in execution.get("outputs", [])
            )
            for candidate in candidates:
                if candidate:
                    path = Path(candidate).resolve()
                    if path.is_relative_to(storage.artifacts.resolve()):
                        paths.add(path)

        with storage.connect() as connection:
            for kind, key, payload in connection.execute(
                "SELECT kind,id,payload FROM metadata"
            ):
                value = json.loads(payload)
                if value.get("thread_id") in thread_ids or (
                    kind == "investigations" and key in thread_ids
                ):
                    records.append((kind, key))
                    collect_paths(kind, value)
                    if kind == "runs":
                        run_ids.add(key)
        # Use the maintained saver API; checkpoint identities are run IDs.
        if services.checkpointer:
            for key in run_ids:
                await services.checkpointer.adelete_thread(key)
        for path in paths:
            path.unlink(missing_ok=True)
        with storage.connect() as connection:
            connection.executemany(
                "DELETE FROM metadata WHERE kind=? AND id=?", records
            )
            connection.executemany(
                "DELETE FROM tool_commits WHERE run_id=?", [(key,) for key in run_ids]
            )
        for store in (
            services.conversations,
            services.runs,
            services.results,
            services.analyses,
            services.reports,
        ):
            store.forget_conversations(thread_ids)
        return {"deleted_conversations": len(thread_ids)}
    finally:
        services.deleting_conversations.difference_update(thread_ids)
