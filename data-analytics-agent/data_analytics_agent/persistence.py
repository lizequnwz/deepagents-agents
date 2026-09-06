"""Local, typed metadata persistence shared by application stores."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import sqlite3
from tempfile import mkdtemp
from typing import Any

from pydantic import TypeAdapter


class LocalStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or mkdtemp(prefix="analytics-test-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.database = self.root / "metadata.sqlite"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (kind TEXT, id TEXT, payload BLOB NOT NULL, PRIMARY KEY(kind,id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tool_commits (run_id TEXT, call_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,call_id))"
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def load(self, kind: str, model: Any) -> dict[str, Any]:
        adapter = TypeAdapter(model)
        with self.connect() as connection:
            return {
                key: adapter.validate_json(payload)
                for key, payload in connection.execute(
                    "SELECT id,payload FROM metadata WHERE kind=?", (kind,)
                )
            }

    def put(self, kind: str, key: str, value: Any, model: Any = None):
        payload = TypeAdapter(model or type(value)).dump_json(value)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES (?,?,?)", (kind, key, payload)
            )

    def committed(self, run_id: str, call_id: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM tool_commits WHERE run_id=? AND call_id=?",
                (run_id, call_id),
            ).fetchone()
        return row[0] if row else None

    def commit(self, run_id: str, call_id: str, payload: str):
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO tool_commits VALUES (?,?,?)",
                (run_id, call_id, payload),
            )


def persist_run(method):
    """Persist a run mutation while retaining the store's reentrant lock."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            value = method(self, *args, **kwargs)
            key = (
                value
                if method.__name__ == "create"
                else args[0]
                if args
                else kwargs["run_id"]
            )
            self._items[key].last_saved_at = self._clock()
            self.storage.put("runs", key, self._items[key])
            return value

    return wrapped
