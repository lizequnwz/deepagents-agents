"""Corporation-scoped coding records and a durable, explicit attempt queue."""

from __future__ import annotations

import json
import fcntl
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from general_agent.workspace import validate_corp_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier() -> str:
    return uuid4().hex


class CodingConflict(ValueError):
    """The reviewed operation no longer matches current state."""


class CodingStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.owner_id = identifier()
        self._owner_fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._owner_fd)
            raise CodingConflict("Another application process owns the coding scheduler.") from exc
        self._closed = False
        try:
            self._initialize(path)
        except BaseException:
            if hasattr(self, "_db"):
                self._db.close()
            os.close(self._owner_fd)
            raise

    def _initialize(self, path: Path):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, root TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(corp_id,id), UNIQUE(root)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,project_id) REFERENCES projects(corp_id,id)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, session_id TEXT NOT NULL,
                status TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,session_id) REFERENCES sessions(corp_id,id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS session_writer
                ON attempts(corp_id,session_id) WHERE status IN ('running','stopping');
            CREATE INDEX IF NOT EXISTS attempt_queue ON attempts(status,created);
            CREATE TABLE IF NOT EXISTS coding_changes (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, session_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,session_id) REFERENCES sessions(corp_id,id),
                FOREIGN KEY(corp_id,attempt_id) REFERENCES attempts(corp_id,id)
            );
            CREATE TABLE IF NOT EXISTS coding_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, corp_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL, payload TEXT NOT NULL,
                FOREIGN KEY(corp_id,attempt_id) REFERENCES attempts(corp_id,id)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, session_id TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,session_id) REFERENCES sessions(corp_id,id)
            );
            CREATE TABLE IF NOT EXISTS scheduler_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                owner_id TEXT NOT NULL, heartbeat TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, session_id TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,session_id) REFERENCES sessions(corp_id,id)
            );
            CREATE TABLE IF NOT EXISTS inline_statistics (
                corp_id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connector_queries (
                corp_id TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(corp_id,id),
                FOREIGN KEY(corp_id,project_id) REFERENCES projects(corp_id,id)
            );
        """)
        self._db.commit()
        self.heartbeat()
        self.abandoned_attempt_ids: list[str] = []
        with self._lock, self._db:
            for row in self._db.execute(
                "SELECT * FROM attempts WHERE status IN ('running','stopping') OR json_extract(payload,'$.cleanup_pending')=1"
            ).fetchall():
                record = json.loads(row["payload"])
                self.abandoned_attempt_ids.append(row["id"])
                record.update(status="failed", outcome="not_verified", ended=now(),
                              error="Application restarted. Continue creates a new attempt.")
                self._update("attempts", row["corp_id"], record)
            for row in self._db.execute("SELECT * FROM deliveries WHERE status='publishing'").fetchall():
                record = json.loads(row["payload"])
                record.update(status="uncertain", ended=now(), error="Publication was interrupted. Inspect remote receipts before any new action.")
                self._update("deliveries", row["corp_id"], record)
            for row in self._db.execute("SELECT * FROM connector_queries WHERE json_extract(payload,'$.status')='submitted'").fetchall():
                record = json.loads(row["payload"])
                record.update(status="interrupted", cancellation="unconfirmed; server query timeout was ten seconds")
                self._db.execute("UPDATE connector_queries SET payload=? WHERE corp_id=? AND id=?", (json.dumps(record), row["corp_id"], row["id"]))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                with self._db:
                    self._db.execute("DELETE FROM scheduler_lease WHERE owner_id=?", (self.owner_id,))
            finally:
                self._db.close()
                os.close(self._owner_fd)

    def heartbeat(self) -> None:
        """The kernel lock owns recovery; this record makes its health inspectable."""
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO scheduler_lease VALUES (1,?,?)",
                             (self.owner_id, now()))

    def scheduler_health(self) -> dict[str, str]:
        with self._lock:
            row = self._db.execute("SELECT owner_id,heartbeat FROM scheduler_lease").fetchone()
        return dict(row)

    def mark_cleaned(self, attempt_id: str) -> None:
        with self._lock, self._db:
            for row in self._db.execute("SELECT corp_id,payload FROM attempts WHERE id=?", (attempt_id,)).fetchall():
                record = json.loads(row["payload"])
                record.pop("cleanup_pending", None)
                self._update("attempts", row["corp_id"], record)

    def register_project(self, corp_id: str, record: dict[str, Any]) -> dict[str, Any]:
        validate_corp_id(corp_id)
        root = Path(record["root"])
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for row in self._db.execute("SELECT corp_id,id,root,payload FROM projects"):
                    other = Path(row["root"])
                    if root == other and row["corp_id"] == corp_id:
                        self._db.rollback()
                        return json.loads(row["payload"])
                    if root == other or root in other.parents or other in root.parents:
                        raise CodingConflict("Repository roots may not overlap registered projects.")
                self._db.execute("INSERT INTO projects VALUES (?,?,?,?)",
                                 (corp_id, record["id"], str(root), json.dumps(record)))
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        return record

    def projects(self, corp_id: str) -> list[dict[str, Any]]:
        return self._list("projects", corp_id)

    def project(self, corp_id: str, project_id: str) -> dict[str, Any]:
        return self._get("projects", corp_id, project_id)

    def save_project(self, corp_id: str, record: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._update("projects", corp_id, record)

    def add_session(self, corp_id: str, record: dict[str, Any]) -> None:
        validate_corp_id(corp_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (
                corp_id, record["id"], record["project_id"], json.dumps(record)))

    def sessions(self, corp_id: str) -> list[dict[str, Any]]:
        return self._list("sessions", corp_id)

    def session(self, corp_id: str, session_id: str) -> dict[str, Any]:
        return self._get("sessions", corp_id, session_id)

    def save_session(self, corp_id: str, record: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._update("sessions", corp_id, record)

    def enqueue(self, corp_id: str, record: dict[str, Any]) -> None:
        validate_corp_id(corp_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?)", (
                corp_id, record["id"], record["session_id"], "queued", record["created"],
                json.dumps(record)))

    def claim(self, max_workers: int, max_corp_workers: int = 1) -> dict[str, Any] | None:
        """Atomically admit at most one writer per session, with a global cap."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                active = self._db.execute(
                    "SELECT count(*) FROM attempts WHERE status IN ('running','stopping')"
                ).fetchone()[0]
                if active >= max_workers:
                    self._db.rollback()
                    return None
                row = self._db.execute("""
                    SELECT * FROM attempts q WHERE q.status='queued' AND NOT EXISTS (
                        SELECT 1 FROM attempts a WHERE a.corp_id=q.corp_id
                        AND a.session_id=q.session_id AND a.status IN ('running','stopping','waiting_input')
                    ) AND (SELECT count(*) FROM attempts c WHERE c.corp_id=q.corp_id
                        AND c.status IN ('running','stopping')) < ?
                    ORDER BY q.created,q.id LIMIT 1
                """, (max_corp_workers,)).fetchone()
                if row is None:
                    self._db.rollback()
                    return None
                record = json.loads(row["payload"])
                record.update(status="running", corp_id=row["corp_id"])
                record.setdefault("started", now())
                self._update("attempts", row["corp_id"], record)
                self._db.commit()
                return record
            except BaseException:
                self._db.rollback()
                raise

    def attempt(self, corp_id: str, attempt_id: str) -> dict[str, Any]:
        return self._get("attempts", corp_id, attempt_id)

    def attempts(self, corp_id: str, session_id: str, *, limit: int = 50,
                 before: str | None = None) -> list[dict[str, Any]]:
        self.session(corp_id, session_id)
        if not 1 <= limit <= 201:
            raise ValueError("Attempt page size must be between one and 201.")
        parameters: list[Any] = [corp_id, session_id]
        boundary = ""
        if before:
            anchor = self.attempt(corp_id, before)
            if anchor["session_id"] != session_id:
                raise CodingConflict("History cursor belongs to a different session.")
            boundary = " AND (created,id) < (?,?)"
            parameters.extend([anchor["created"], anchor["id"]])
        parameters.append(limit)
        with self._lock:
            records = [json.loads(row[0]) for row in self._db.execute(
                "SELECT payload FROM attempts WHERE corp_id=? AND session_id=?" + boundary
                + " ORDER BY created DESC,id DESC LIMIT ?", parameters)]
        return list(reversed(records))

    def has_pending(self, corp_id: str, session_id: str) -> bool:
        self.session(corp_id, session_id)
        with self._lock:
            return self._db.execute("""SELECT 1 FROM attempts WHERE corp_id=? AND session_id=?
                AND status IN ('queued','running','stopping','waiting_input') LIMIT 1""",
                (corp_id, session_id)).fetchone() is not None

    def project_has_pending(self, corp_id: str, project_id: str) -> bool:
        self.project(corp_id, project_id)
        with self._lock:
            return self._db.execute("""SELECT 1 FROM attempts a JOIN sessions s
                ON a.corp_id=s.corp_id AND a.session_id=s.id WHERE s.corp_id=? AND s.project_id=?
                AND a.status IN ('queued','running','stopping','waiting_input') LIMIT 1""",
                (corp_id, project_id)).fetchone() is not None

    def delivery(self, corp_id: str, delivery_id: str) -> dict:
        return self._get("deliveries", corp_id, delivery_id)

    def inline_statistics(self, corp_id: str) -> dict:
        validate_corp_id(corp_id)
        with self._lock:
            row = self._db.execute("SELECT payload FROM inline_statistics WHERE corp_id=?", (corp_id,)).fetchone()
        return json.loads(row[0]) if row else {"requests": 0, "offered": 0, "editor_reported_acceptances": 0,
            "reported_tokens": 0, "missing_usage_calls": 0, "total_latency_ms": 0}

    def inline_observation(self, corp_id: str, *, offered: bool = False, accepted: bool = False,
                           tokens: int | None = None, latency_ms: int = 0):
        with self._lock, self._db:
            statistics = self.inline_statistics(corp_id)
            if accepted:
                statistics["editor_reported_acceptances"] += 1
            else:
                statistics["requests"] += 1
                statistics["offered"] += int(offered)
                statistics["reported_tokens"] += tokens or 0
                statistics["missing_usage_calls"] += int(tokens is None)
                statistics["total_latency_ms"] += latency_ms
            self._db.execute("INSERT OR REPLACE INTO inline_statistics VALUES (?,?)", (corp_id, json.dumps(statistics)))

    def record_connector_query(self, corp_id: str, project_id: str, provenance: dict):
        self.project(corp_id, project_id)
        with self._lock, self._db:
            existing = self._db.execute("SELECT project_id FROM connector_queries WHERE corp_id=? AND id=?",
                (corp_id, provenance["request_id"])).fetchone()
            if existing:
                if existing[0] != project_id:
                    raise CodingConflict("Connector query belongs to another project.")
                self._db.execute("UPDATE connector_queries SET payload=? WHERE corp_id=? AND id=?",
                    (json.dumps(provenance), corp_id, provenance["request_id"]))
            else:
                count = self._db.execute("SELECT count(*) FROM connector_queries WHERE corp_id=? AND project_id=?", (corp_id, project_id)).fetchone()[0]
                if count >= 500:
                    raise CodingConflict("Project connector query history limit reached; receipts are retained.")
                self._db.execute("INSERT INTO connector_queries VALUES (?,?,?,?)",
                    (corp_id, provenance["request_id"], project_id, json.dumps(provenance)))

    def connector_queries(self, corp_id: str, project_id: str):
        self.project(corp_id, project_id)
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT payload FROM connector_queries WHERE corp_id=? AND project_id=? ORDER BY rowid DESC LIMIT 50", (corp_id, project_id))]

    def deliveries(self, corp_id: str, session_id: str) -> list[dict]:
        self.session(corp_id, session_id)
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT payload FROM deliveries WHERE corp_id=? AND session_id=? ORDER BY rowid DESC LIMIT 50",
                (corp_id, session_id))]

    def record_delivery(self, corp_id: str, record: dict, event: str) -> None:
        """Single-use durable publication claim precedes every remote mutation."""
        validate_corp_id(corp_id)
        if record["corp_id"] != corp_id:
            raise KeyError(record["id"])
        with self._lock, self._db:
            self.session(corp_id, record["session_id"])
            if event == "prepared":
                count = self._db.execute("SELECT count(*) FROM deliveries WHERE corp_id=? AND session_id=?",
                                         (corp_id, record["session_id"])).fetchone()[0]
                if count >= 50:
                    raise CodingConflict("Session delivery history limit reached; receipts are retained.")
                if record["status"] != "prepared" or record.get("journal"):
                    raise CodingConflict("A fresh delivery proposal is required.")
                self._db.execute("INSERT INTO deliveries VALUES (?,?,?,?,?)", (
                    corp_id, record["id"], record["session_id"], record["status"], json.dumps(record)))
                return
            previous = self.delivery(corp_id, record["id"])
            if (previous["session_id"] != record["session_id"] or previous["digest"] != record["digest"]
                    or previous["proposal"] != record["proposal"]):
                raise CodingConflict("Delivery differs from its stored review.")
            if event == "claim":
                if previous["status"] != "prepared" or record["status"] != "publishing" or record["journal"]:
                    raise CodingConflict("Delivery authorization has already been used.")
            elif event != "progress" or previous["status"] != "publishing":
                raise CodingConflict("This publication is no longer active.")
            self._update("deliveries", corp_id, record)

    def save_attempt(self, corp_id: str, record: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._update("attempts", corp_id, record)

    def add_change(self, corp_id: str, session_id: str, record: dict[str, Any]) -> None:
        validate_corp_id(corp_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO coding_changes VALUES (?,?,?,?,?)", (
                corp_id, record["id"], session_id, record["attempt_id"], json.dumps(record)))

    def change(self, corp_id: str, change_id: str) -> dict[str, Any]:
        record = self._get("coding_changes", corp_id, change_id)
        with self._lock:
            row = self._db.execute("SELECT session_id FROM coding_changes WHERE corp_id=? AND id=?",
                                   (corp_id, change_id)).fetchone()
        return {**record, "session_id": row[0]}

    def save_change(self, corp_id: str, record: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._update("coding_changes", corp_id, record)

    def event(self, corp_id: str, attempt_id: str, event: dict[str, Any]) -> None:
        self.attempt(corp_id, attempt_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO coding_events(corp_id,attempt_id,payload) VALUES (?,?,?)",
                             (corp_id, attempt_id, json.dumps({"time": now(), **event})))

    def events(self, corp_id: str, attempt_id: str, after: int = 0,
               limit: int = 200) -> dict[str, Any]:
        self.attempt(corp_id, attempt_id)
        if after < 0 or not 1 <= limit <= 500:
            raise ValueError("Invalid event cursor or page size.")
        with self._lock:
            rows = self._db.execute("""SELECT seq,payload FROM coding_events
                WHERE corp_id=? AND attempt_id=? AND seq>? ORDER BY seq LIMIT ?""",
                (corp_id, attempt_id, after, limit + 1)).fetchall()
        page = rows[:limit]
        return {"events": [{"seq": row[0], **json.loads(row[1])} for row in page],
                "next_cursor": page[-1][0] if page else after, "has_more": len(rows) > limit}

    def add_decision(self, corp_id: str, record: dict[str, Any]) -> None:
        validate_corp_id(corp_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (
                corp_id, record["id"], record["session_id"], "pending", json.dumps(record)))

    def decision(self, corp_id: str, decision_id: str) -> dict[str, Any]:
        return self._get("decisions", corp_id, decision_id)

    def respond(self, corp_id: str, decision_id: str, response: str) -> dict[str, Any]:
        if response not in {"approve", "reject"}:
            raise ValueError("Response must be approve or reject.")
        with self._lock, self._db:
            record = self.decision(corp_id, decision_id)
            if record["status"] != "pending":
                raise CodingConflict("Decision already answered.")
            record.update(status=response, answered=now())
            self._update("decisions", corp_id, record)
            return record

    def approve_and_enqueue(self, corp_id: str, decision_id: str, attempt: dict[str, Any]) -> None:
        """Commit the single-use answer and its task together, including after a crash."""
        with self._lock, self._db:
            decision = self.decision(corp_id, decision_id)
            if decision["status"] != "pending":
                raise CodingConflict("Decision already answered.")
            if decision["session_id"] != attempt["session_id"]:
                raise CodingConflict("Decision belongs to a different session.")
            decision.update(status="approve", answered=now(), implementation_id=attempt["id"])
            self._update("decisions", corp_id, decision)
            self._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?)", (
                corp_id, attempt["id"], attempt["session_id"], "queued", attempt["created"],
                json.dumps(attempt)))

    def answer_and_resume(self, corp_id: str, decision_id: str, message: str) -> dict[str, Any]:
        with self._lock, self._db:
            decision = self.decision(corp_id, decision_id)
            attempt = self.attempt(corp_id, decision["attempt_id"])
            if decision["kind"] != "input" or decision["status"] != "pending" or attempt["status"] != "waiting_input":
                raise CodingConflict("This question is no longer waiting for an answer.")
            decision.update(status="answered", answered=now())
            attempt.update(status="queued", resume={decision["interrupt_id"]: message},
                           expected_revision=decision["revision"])
            self._update("decisions", corp_id, decision)
            self._update("attempts", corp_id, attempt)
            return attempt

    def _get(self, table: str, corp_id: str, record_id: str) -> dict[str, Any]:
        validate_corp_id(corp_id)
        with self._lock:
            row = self._db.execute(f"SELECT payload FROM {table} WHERE corp_id=? AND id=?",
                                   (corp_id, record_id)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return json.loads(row[0])

    def _list(self, table: str, corp_id: str) -> list[dict[str, Any]]:
        validate_corp_id(corp_id)
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute(
                f"SELECT payload FROM {table} WHERE corp_id=? ORDER BY rowid DESC LIMIT 200",
                (corp_id,))]

    def _update(self, table: str, corp_id: str, record: dict[str, Any]) -> None:
        validate_corp_id(corp_id)
        if table in {"attempts", "decisions", "deliveries"}:
            result = self._db.execute(f"UPDATE {table} SET payload=?,status=? WHERE corp_id=? AND id=?",
                                     (json.dumps(record), record["status"], corp_id, record["id"]))
        else:
            result = self._db.execute(f"UPDATE {table} SET payload=? WHERE corp_id=? AND id=?",
                                     (json.dumps(record), corp_id, record["id"]))
        if result.rowcount != 1:
            raise KeyError(record["id"])
