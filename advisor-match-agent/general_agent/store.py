"""SQLite persistence for conversations, runs, events, usage, and files."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from general_agent.schemas import (
    AgentUsage,
    Artifact,
    Attachment,
    Conversation,
    ConversationSummary,
    Run,
    RunDiagnostics,
    RunEvent,
    RunStatus,
    TokenUsage,
    Turn,
    utc_now,
)
from general_agent.workspace import corp_storage_key, validate_corp_id


class ActiveRunError(RuntimeError):
    """Raised when a user's single-run invariant is occupied."""


class Store:
    """Small synchronous SQLite store guarded for async/background callers."""

    def __init__(
        self, path: Path, data_root: Path, default_corp_id: str = "A123456"
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.data_root = data_root
        self.default_corp_id = validate_corp_id(default_corp_id)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._create_schema()
        self._migrate_legacy_snapshot_paths()
        self.recover_abandoned_runs()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    question TEXT NOT NULL,
                    assistant_text TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS runs_conversation_idx ON runs(conversation_id, started_at);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    run_id TEXT UNIQUE NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    user_message TEXT NOT NULL,
                    assistant_message TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    corp_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    label TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    protected_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_usage (
                    corp_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    agent TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER,
                    reasoning_output_tokens INTEGER,
                    model_calls INTEGER NOT NULL DEFAULT 0,
                    missing_usage INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(run_id, agent)
                );
                CREATE TABLE IF NOT EXISTS advisor_match_sessions (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    source_relative_path TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    mapping_json TEXT NOT NULL,
                    reference_json TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    output_relative_path TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS advisor_match_review_decisions (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES advisor_match_sessions(id) ON DELETE CASCADE,
                    review_item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    crd_number TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    prior_decision_json TEXT NOT NULL,
                    new_decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS advisor_match_override_proposals (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES advisor_match_sessions(id) ON DELETE CASCADE,
                    review_item_id TEXT NOT NULL,
                    crd_number TEXT NOT NULL,
                    advisor_json TEXT NOT NULL,
                    reference_sha256 TEXT NOT NULL,
                    created_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            for table in (
                "conversations",
                "runs",
                "turns",
                "events",
                "attachments",
                "artifacts",
                "agent_usage",
            ):
                columns = {
                    row["name"]
                    for row in self._connection.execute(f"PRAGMA table_info({table})")
                }
                if "corp_id" not in columns:
                    self._connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN corp_id TEXT NOT NULL "
                        f"DEFAULT '{self.default_corp_id}'"
                    )
            proposal_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(advisor_match_override_proposals)"
                )
            }
            if "created_run_id" not in proposal_columns:
                self._connection.execute(
                    "ALTER TABLE advisor_match_override_proposals "
                    "ADD COLUMN created_run_id TEXT NOT NULL DEFAULT ''"
                )
            self._connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS conversations_corp_idx
                    ON conversations(corp_id, updated_at);
                CREATE INDEX IF NOT EXISTS runs_corp_status_idx
                    ON runs(corp_id, status);
                CREATE INDEX IF NOT EXISTS turns_corp_conversation_idx
                    ON turns(corp_id, conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS attachments_corp_idx
                    ON attachments(corp_id, id);
                CREATE INDEX IF NOT EXISTS artifacts_corp_idx
                    ON artifacts(corp_id, id);
                CREATE INDEX IF NOT EXISTS advisor_match_sessions_corp_idx
                    ON advisor_match_sessions(corp_id, conversation_id, updated_at);
                CREATE INDEX IF NOT EXISTS advisor_review_decisions_corp_idx
                    ON advisor_match_review_decisions(corp_id, session_id, created_at);
                """
            )

    def _corp(self, corp_id: str | None) -> str:
        return validate_corp_id(corp_id or self.default_corp_id)

    def _migrate_legacy_snapshot_paths(self) -> None:
        """Move pre-tenant protected files under the default user's data root."""

        corp_id = self.default_corp_id
        destination_root = self.data_root / "users" / corp_storage_key(corp_id)
        destination_root.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection:
            for table, column, category in (
                ("attachments", "protected_path", "attachments"),
                ("artifacts", "snapshot_path", "artifacts"),
            ):
                rows = self._connection.execute(
                    f"SELECT id, {column} AS path FROM {table} WHERE corp_id=?",
                    (corp_id,),
                ).fetchall()
                old_root = (self.data_root / category).resolve()
                for row in rows:
                    source = Path(row["path"])
                    if not source.exists():
                        continue
                    try:
                        relative = source.resolve().relative_to(old_root)
                    except ValueError:
                        continue
                    destination = destination_root / category / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        shutil.move(str(source), str(destination))
                    self._connection.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=? AND corp_id=?",
                        (str(destination), row["id"], corp_id),
                    )
            old_baselines = self.data_root / "baselines"
            new_baselines = destination_root / "baselines"
            if old_baselines.is_dir():
                new_baselines.mkdir(parents=True, exist_ok=True)
                for child in list(old_baselines.iterdir()):
                    shutil.move(str(child), str(new_baselines / child.name))

    def recover_abandoned_runs(self) -> None:
        now = _iso(utc_now())
        message = "The backend restarted before this run finished."
        with self._lock, self._connection:
            run_ids = [
                row["id"]
                for row in self._connection.execute(
                    "SELECT id FROM runs WHERE status IN (?, ?)",
                    (RunStatus.RUNNING, RunStatus.STOPPING),
                )
            ]
            for run_id in run_ids:
                self._connection.execute(
                    "UPDATE runs SET status=?, error=?, completed_at=? WHERE id=?",
                    (RunStatus.FAILED, message, now, run_id),
                )
                self._connection.execute(
                    "UPDATE turns SET status=?, error=?, completed_at=? WHERE run_id=?",
                    (RunStatus.FAILED, message, now, run_id),
                )

    def create_conversation(
        self, title: str | None = None, *, corp_id: str | None = None
    ) -> ConversationSummary:
        corp_id = self._corp(corp_id)
        conversation_id = uuid.uuid4().hex
        now = utc_now()
        safe_title = (title or "New chat").strip()[:120] or "New chat"
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO conversations(id, corp_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, corp_id, safe_title, _iso(now), _iso(now)),
            )
        return ConversationSummary(
            conversation_id=conversation_id,
            title=safe_title,
            created_at=now,
            updated_at=now,
        )

    def list_conversations(
        self, corp_id: str | None = None
    ) -> list[ConversationSummary]:
        corp_id = self._corp(corp_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM conversations WHERE corp_id=? ORDER BY updated_at DESC",
                (corp_id,),
            ).fetchall()
            return [self._conversation_summary(row) for row in rows]

    def rename_conversation(
        self, conversation_id: str, title: str, *, corp_id: str | None = None
    ) -> None:
        corp_id = self._corp(corp_id)
        safe = title.strip()[:120]
        if not safe:
            raise ValueError("Conversation title cannot be empty.")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND corp_id=?",
                (safe, _iso(utc_now()), conversation_id, corp_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(conversation_id)

    def delete_conversation(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> list[str]:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            active = self._connection.execute(
                "SELECT 1 FROM runs WHERE conversation_id=? AND corp_id=? AND status IN (?, ?)",
                (conversation_id, corp_id, RunStatus.RUNNING, RunStatus.STOPPING),
            ).fetchone()
            if active:
                raise ActiveRunError("Stop the active run before deleting its conversation.")
            run_ids = [
                row["id"]
                for row in self._connection.execute(
                    "SELECT id FROM runs WHERE conversation_id=? AND corp_id=?",
                    (conversation_id, corp_id),
                )
            ]
            protected_paths = [
                Path(row["protected_path"])
                for row in self._connection.execute(
                    """SELECT protected_path FROM attachments
                    WHERE run_id IN (
                        SELECT id FROM runs WHERE conversation_id=? AND corp_id=?
                    )""",
                    (conversation_id, corp_id),
                )
            ]
            cursor = self._connection.execute(
                "DELETE FROM conversations WHERE id=? AND corp_id=?",
                (conversation_id, corp_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(conversation_id)
        for run_id in run_ids:
            for directory in (
                self.data_root / "users" / corp_storage_key(corp_id) / "artifacts" / run_id,
                self.data_root / "users" / corp_storage_key(corp_id) / "baselines" / run_id,
            ):
                if directory.exists():
                    shutil.rmtree(directory)
        for protected_path in protected_paths:
            directory = protected_path.parent
            attachment_root = (
                self.data_root / "users" / corp_storage_key(corp_id) / "attachments"
            )
            if directory.is_relative_to(attachment_root) and directory.exists():
                shutil.rmtree(directory)
        return run_ids

    def create_run(
        self,
        conversation_id: str,
        question: str,
        *,
        corp_id: str | None = None,
    ) -> tuple[str, str]:
        corp_id = self._corp(corp_id)
        run_id = uuid.uuid4().hex
        turn_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                conversation = self._connection.execute(
                    "SELECT title FROM conversations WHERE id=? AND corp_id=?",
                    (conversation_id, corp_id),
                ).fetchone()
                if conversation is None:
                    raise KeyError(conversation_id)
                active = self._connection.execute(
                    "SELECT id FROM runs WHERE corp_id=? AND status IN (?, ?) LIMIT 1",
                    (corp_id, RunStatus.RUNNING, RunStatus.STOPPING),
                ).fetchone()
                if active:
                    raise ActiveRunError(
                        "Another run is active. Stop or finish it before sending a message."
                    )
                self._connection.execute(
                    "INSERT INTO runs(id, corp_id, conversation_id, status, question, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (run_id, corp_id, conversation_id, RunStatus.RUNNING, question, _iso(now)),
                )
                self._connection.execute(
                    "INSERT INTO turns(id, corp_id, run_id, conversation_id, user_message, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (turn_id, corp_id, run_id, conversation_id, question, RunStatus.RUNNING, _iso(now)),
                )
                title = conversation["title"]
                if title == "New chat":
                    title = _derive_title(question)
                self._connection.execute(
                    "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND corp_id=?",
                    (title, _iso(now), conversation_id, corp_id),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return run_id, turn_id

    def add_attachment(
        self,
        run_id: str,
        attachment: Attachment,
        protected_path: Path,
        *,
        corp_id: str | None = None,
    ) -> None:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM runs WHERE id=? AND corp_id=?", (run_id, corp_id)
            ).fetchone():
                raise KeyError(run_id)
            self._connection.execute(
                """INSERT INTO attachments(
                    id, corp_id, run_id, original_name, relative_path, content_type,
                    size_bytes, created_at, protected_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attachment.attachment_id,
                    corp_id,
                    run_id,
                    attachment.original_name,
                    attachment.relative_path,
                    attachment.content_type,
                    attachment.size_bytes,
                    _iso(attachment.created_at),
                    str(protected_path),
                ),
            )

    def create_advisor_match_session(
        self,
        *,
        corp_id: str,
        conversation_id: str,
        source_relative_path: str,
        source_name: str,
        source_sha256: str,
        mapping: Mapping[str, Any],
        reference: Mapping[str, Any],
        decisions: list[Mapping[str, Any]],
        counts: Mapping[str, Any],
        output_relative_path: str,
        policy_version: str,
    ) -> str:
        """Persist structured decisions without placing the workbook in model state."""

        corp_id = self._corp(corp_id)
        session_id = "ams_" + uuid.uuid4().hex
        now = _iso(utc_now())
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM conversations WHERE id=? AND corp_id=?",
                (conversation_id, corp_id),
            ).fetchone():
                raise KeyError(conversation_id)
            self._connection.execute(
                """INSERT INTO advisor_match_sessions(
                    id, corp_id, conversation_id, source_relative_path, source_name,
                    source_sha256, mapping_json, reference_json, decisions_json,
                    counts_json, output_relative_path, policy_version, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Reviewing', ?, ?)""",
                (
                    session_id, corp_id, conversation_id, source_relative_path,
                    source_name, source_sha256,
                    json.dumps(mapping, ensure_ascii=False, default=str),
                    json.dumps(reference, ensure_ascii=False, default=str),
                    json.dumps(decisions, ensure_ascii=False, default=str),
                    json.dumps(counts, ensure_ascii=False, default=str),
                    output_relative_path, policy_version, now, now,
                ),
            )
        return session_id

    def get_advisor_match_session(
        self, session_id: str, *, corp_id: str
    ) -> dict[str, Any]:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM advisor_match_sessions WHERE id=? AND corp_id=?",
                (session_id, corp_id),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _advisor_match_session(row)

    def get_latest_advisor_match_session(
        self, conversation_id: str, *, corp_id: str
    ) -> dict[str, Any]:
        """Return the most recently updated match session in one conversation."""

        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM advisor_match_sessions
                WHERE conversation_id=? AND corp_id=?
                ORDER BY updated_at DESC, created_at DESC LIMIT 1""",
                (conversation_id, corp_id),
            ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return _advisor_match_session(row)

    def update_advisor_match_session(
        self,
        session_id: str,
        *,
        corp_id: str,
        decisions: list[Mapping[str, Any]],
        counts: Mapping[str, Any],
        status: str | None = None,
    ) -> None:
        corp_id = self._corp(corp_id)
        assignments = "decisions_json=?, counts_json=?, updated_at=?, revision=revision+1"
        parameters: list[Any] = [
            json.dumps(decisions, ensure_ascii=False, default=str),
            json.dumps(counts, ensure_ascii=False, default=str),
            _iso(utc_now()),
        ]
        if status is not None:
            assignments += ", status=?"
            parameters.append(status)
        parameters.extend((session_id, corp_id))
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE advisor_match_sessions SET {assignments} WHERE id=? AND corp_id=?",
                parameters,
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)

    def add_advisor_review_decision(
        self,
        *,
        corp_id: str,
        session_id: str,
        review_item_id: str,
        action: str,
        crd_number: str | None,
        note: str,
        prior: Mapping[str, Any],
        new: Mapping[str, Any],
    ) -> None:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM advisor_match_sessions WHERE id=? AND corp_id=?",
                (session_id, corp_id),
            ).fetchone():
                raise KeyError(session_id)
            self._connection.execute(
                """INSERT INTO advisor_match_review_decisions(
                    id, corp_id, session_id, review_item_id, action, crd_number,
                    note, prior_decision_json, new_decision_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "amd_" + uuid.uuid4().hex, corp_id, session_id, review_item_id,
                    action, crd_number, note,
                    json.dumps(prior, ensure_ascii=False, default=str),
                    json.dumps(new, ensure_ascii=False, default=str), _iso(utc_now()),
                ),
            )

    def create_advisor_override_proposal(
        self, *, corp_id: str, session_id: str, review_item_id: str,
        crd_number: str, advisor: Mapping[str, Any], reference_sha256: str,
        created_run_id: str,
    ) -> str:
        corp_id = self._corp(corp_id)
        proposal_id = "amp_" + uuid.uuid4().hex
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO advisor_match_override_proposals(
                    id, corp_id, session_id, review_item_id, crd_number,
                    advisor_json, reference_sha256, created_run_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)""",
                (proposal_id, corp_id, session_id, review_item_id, crd_number,
                 json.dumps(advisor, ensure_ascii=False, default=str), reference_sha256,
                 created_run_id, _iso(utc_now())),
            )
        return proposal_id

    def get_advisor_override_proposal(self, proposal_id: str, *, corp_id: str) -> dict[str, Any]:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM advisor_match_override_proposals WHERE id=? AND corp_id=?",
                (proposal_id, corp_id),
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        result = dict(row)
        result["advisor"] = json.loads(result.pop("advisor_json"))
        return result

    def apply_advisor_override_proposal(self, proposal_id: str, *, corp_id: str) -> None:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE advisor_match_override_proposals SET status='Applied' WHERE id=? AND corp_id=? AND status='Pending'",
                (proposal_id, corp_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(proposal_id)

    def add_artifact(
        self,
        artifact: Artifact,
        snapshot_path: Path,
        *,
        corp_id: str | None = None,
    ) -> None:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM runs WHERE id=? AND corp_id=?",
                (artifact.run_id, corp_id),
            ).fetchone():
                raise KeyError(artifact.run_id)
            self._connection.execute(
                """INSERT INTO artifacts(
                    id, corp_id, run_id, relative_path, change_type, size_bytes,
                    sha256, created_at, snapshot_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    corp_id,
                    artifact.run_id,
                    artifact.relative_path,
                    artifact.change_type,
                    artifact.size_bytes,
                    artifact.sha256,
                    _iso(artifact.created_at),
                    str(snapshot_path),
                ),
            )

    def add_event(
        self,
        run_id: str,
        kind: str,
        phase: str,
        label: str,
        *,
        agent: str = "advisor-match-agent",
        data: Mapping[str, Any] | None = None,
        corp_id: str | None = None,
    ) -> RunEvent:
        corp_id = self._corp(corp_id)
        now = utc_now()
        safe_data = dict(data or {})
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM events WHERE run_id=? AND corp_id=?",
                (run_id, corp_id),
            ).fetchone()
            seq = int(row["seq"])
            self._connection.execute(
                """INSERT INTO events(
                    corp_id, run_id, seq, kind, phase, label, agent, created_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    corp_id,
                    run_id,
                    seq,
                    kind,
                    phase,
                    label,
                    agent,
                    _iso(now),
                    json.dumps(safe_data, ensure_ascii=False, default=str),
                ),
            )
        return RunEvent(
            id=seq,
            kind=kind,  # type: ignore[arg-type]
            phase=phase,  # type: ignore[arg-type]
            label=label,
            agent=agent,
            created_at=now,
            data=safe_data,
        )

    def increment_tool_calls(
        self, run_id: str, *, corp_id: str | None = None
    ) -> None:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE runs SET tool_calls=tool_calls+1 WHERE id=? AND corp_id=?",
                (run_id, corp_id),
            )

    def record_model_call(
        self,
        run_id: str,
        agent: str,
        usage: Mapping[str, Any] | None,
        *,
        corp_id: str | None = None,
    ) -> None:
        corp_id = self._corp(corp_id)
        parsed = _valid_usage(usage)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO agent_usage(corp_id, run_id, agent) VALUES (?, ?, ?)",
                (corp_id, run_id, agent),
            )
            if parsed is None:
                self._connection.execute(
                    "UPDATE agent_usage SET model_calls=model_calls+1, missing_usage=missing_usage+1 WHERE run_id=? AND agent=? AND corp_id=?",
                    (run_id, agent, corp_id),
                )
                return
            cached = _detail(parsed.get("input_token_details"), ("cache_read", "cached"))
            reasoning = _detail(parsed.get("output_token_details"), ("reasoning",))
            self._connection.execute(
                """UPDATE agent_usage SET
                    input_tokens=input_tokens+?, output_tokens=output_tokens+?,
                    total_tokens=total_tokens+?,
                    cached_input_tokens=COALESCE(cached_input_tokens, 0)+?,
                    reasoning_output_tokens=COALESCE(reasoning_output_tokens, 0)+?,
                    model_calls=model_calls+1
                    WHERE run_id=? AND agent=? AND corp_id=?""",
                (
                    parsed["input_tokens"],
                    parsed["output_tokens"],
                    parsed["total_tokens"],
                    cached or 0,
                    reasoning or 0,
                    run_id,
                    agent,
                    corp_id,
                ),
            )

    def request_stop(self, run_id: str, *, corp_id: str | None = None) -> bool:
        corp_id = self._corp(corp_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE runs SET status=? WHERE id=? AND corp_id=? AND status=?",
                (RunStatus.STOPPING, run_id, corp_id, RunStatus.RUNNING),
            )
            return cursor.rowcount > 0

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        assistant_text: str = "",
        error: str | None = None,
        corp_id: str | None = None,
    ) -> None:
        corp_id = self._corp(corp_id)
        now = utc_now()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT started_at, conversation_id FROM runs WHERE id=? AND corp_id=?",
                (run_id, corp_id),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            elapsed = int((now - _datetime(row["started_at"])).total_seconds() * 1000)
            self._connection.execute(
                "UPDATE runs SET status=?, assistant_text=?, error=?, completed_at=?, elapsed_ms=? WHERE id=? AND corp_id=?",
                (status, assistant_text, error, _iso(now), elapsed, run_id, corp_id),
            )
            self._connection.execute(
                "UPDATE turns SET status=?, assistant_message=?, error=?, completed_at=? WHERE run_id=? AND corp_id=?",
                (status, assistant_text, error, _iso(now), run_id, corp_id),
            )
            self._connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=? AND corp_id=?",
                (_iso(now), row["conversation_id"], corp_id),
            )

    def completed_history(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> list[dict[str, str]]:
        corp_id = self._corp(corp_id)
        with self._lock:
            rows = self._connection.execute(
                """SELECT user_message, assistant_message FROM turns
                WHERE conversation_id=? AND corp_id=? AND status=? ORDER BY created_at""",
                (conversation_id, corp_id, RunStatus.COMPLETED),
            ).fetchall()
        messages: list[dict[str, str]] = []
        for row in rows:
            messages.append({"role": "user", "content": row["user_message"]})
            messages.append({"role": "assistant", "content": row["assistant_message"]})
        return messages

    def get_run(
        self,
        run_id: str,
        *,
        after_event_id: int = 0,
        corp_id: str | None = None,
    ) -> Run:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE id=? AND corp_id=?", (run_id, corp_id)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            events = self._events(run_id, after_event_id, corp_id)
            next_id_row = self._connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id=? AND corp_id=?",
                (run_id, corp_id),
            ).fetchone()
            return Run(
                run_id=run_id,
                conversation_id=row["conversation_id"],
                status=RunStatus(row["status"]),
                question=row["question"],
                assistant_text=row["assistant_text"],
                error=row["error"],
                started_at=_datetime(row["started_at"]),
                completed_at=_optional_datetime(row["completed_at"]),
                events=events,
                next_event_id=int(next_id_row["seq"]),
                diagnostics=self._diagnostics(run_id, row, corp_id),
            )

    def get_conversation(
        self, conversation_id: str, *, corp_id: str | None = None
    ) -> Conversation:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM conversations WHERE id=? AND corp_id=?",
                (conversation_id, corp_id),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            turn_rows = self._connection.execute(
                "SELECT * FROM turns WHERE conversation_id=? AND corp_id=? ORDER BY created_at",
                (conversation_id, corp_id),
            ).fetchall()
            turns = [self._turn(turn_row, corp_id) for turn_row in turn_rows]
            active = self._connection.execute(
                "SELECT id FROM runs WHERE conversation_id=? AND corp_id=? AND status IN (?, ?) LIMIT 1",
                (conversation_id, corp_id, RunStatus.RUNNING, RunStatus.STOPPING),
            ).fetchone()
            diagnostics = _sum_diagnostics([turn.diagnostics for turn in turns])
            return Conversation(
                conversation_id=conversation_id,
                title=row["title"],
                created_at=_datetime(row["created_at"]),
                updated_at=_datetime(row["updated_at"]),
                active_run_id=active["id"] if active else None,
                turns=turns,
                diagnostics=diagnostics,
            )

    def attachment_path(
        self, attachment_id: str, *, corp_id: str | None = None
    ) -> tuple[Path, str]:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT protected_path, original_name FROM attachments WHERE id=? AND corp_id=?",
                (attachment_id, corp_id),
            ).fetchone()
            if row is None:
                raise KeyError(attachment_id)
            return Path(row["protected_path"]), row["original_name"]

    def artifact_path(
        self, artifact_id: str, *, corp_id: str | None = None
    ) -> tuple[Path, str]:
        corp_id = self._corp(corp_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_path, relative_path FROM artifacts WHERE id=? AND corp_id=?",
                (artifact_id, corp_id),
            ).fetchone()
            if row is None:
                raise KeyError(artifact_id)
            return Path(row["snapshot_path"]), Path(row["relative_path"]).name

    def _conversation_summary(self, row: sqlite3.Row) -> ConversationSummary:
        active = self._connection.execute(
            "SELECT id FROM runs WHERE conversation_id=? AND corp_id=? "
            "AND status IN (?, ?) LIMIT 1",
            (row["id"], row["corp_id"], RunStatus.RUNNING, RunStatus.STOPPING),
        ).fetchone()
        return ConversationSummary(
            conversation_id=row["id"],
            title=row["title"],
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            active_run_id=active["id"] if active else None,
        )

    def _turn(self, row: sqlite3.Row, corp_id: str) -> Turn:
        run_row = self._connection.execute(
            "SELECT * FROM runs WHERE id=? AND corp_id=?", (row["run_id"], corp_id)
        ).fetchone()
        if run_row is None:
            raise KeyError(row["run_id"])
        attachments = [
            Attachment(
                attachment_id=item["id"],
                original_name=item["original_name"],
                relative_path=item["relative_path"],
                content_type=item["content_type"],
                size_bytes=item["size_bytes"],
                created_at=_datetime(item["created_at"]),
            )
            for item in self._connection.execute(
                "SELECT * FROM attachments WHERE run_id=? AND corp_id=? ORDER BY created_at",
                (row["run_id"], corp_id),
            )
        ]
        artifacts = [
            Artifact(
                artifact_id=item["id"],
                run_id=item["run_id"],
                relative_path=item["relative_path"],
                change_type=item["change_type"],
                size_bytes=item["size_bytes"],
                sha256=item["sha256"],
                created_at=_datetime(item["created_at"]),
            )
            for item in self._connection.execute(
                "SELECT * FROM artifacts WHERE run_id=? AND corp_id=? ORDER BY created_at",
                (row["run_id"], corp_id),
            )
        ]
        return Turn(
            turn_id=row["id"],
            run_id=row["run_id"],
            user_message=row["user_message"],
            assistant_message=row["assistant_message"],
            status=RunStatus(row["status"]),
            error=row["error"],
            created_at=_datetime(row["created_at"]),
            completed_at=_optional_datetime(row["completed_at"]),
            attachments=attachments,
            artifacts=artifacts,
            events=self._events(row["run_id"], 0, corp_id),
            diagnostics=self._diagnostics(row["run_id"], run_row, corp_id),
        )

    def _events(self, run_id: str, after: int, corp_id: str) -> list[RunEvent]:
        rows = self._connection.execute(
            "SELECT * FROM events WHERE run_id=? AND corp_id=? AND seq>? ORDER BY seq",
            (run_id, corp_id, after),
        ).fetchall()
        return [
            RunEvent(
                id=row["seq"],
                kind=row["kind"],
                phase=row["phase"],
                label=row["label"],
                agent=row["agent"],
                created_at=_datetime(row["created_at"]),
                data=json.loads(row["data_json"]),
            )
            for row in rows
        ]

    def _diagnostics(
        self, run_id: str, run_row: sqlite3.Row, corp_id: str
    ) -> RunDiagnostics:
        rows = self._connection.execute(
            "SELECT * FROM agent_usage WHERE run_id=? AND corp_id=? ORDER BY agent",
            (run_id, corp_id),
        ).fetchall()
        agents = [_agent_usage(row) for row in rows]
        tokens = _sum_tokens([agent.tokens for agent in agents])
        missing = sum(agent.model_calls_missing_usage for agent in agents)
        status = RunStatus(run_row["status"])
        return RunDiagnostics(
            tokens=tokens,
            token_usage_partial=status in {RunStatus.RUNNING, RunStatus.STOPPING, RunStatus.STOPPED} or bool(missing),
            model_calls=sum(agent.model_calls for agent in agents),
            model_calls_missing_usage=missing,
            tool_calls=int(run_row["tool_calls"]),
            elapsed_ms=int(run_row["elapsed_ms"]),
            agents=agents,
        )


def _advisor_match_session(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for field in (
        "mapping_json",
        "reference_json",
        "decisions_json",
        "counts_json",
    ):
        result[field.removesuffix("_json")] = json.loads(result.pop(field))
    return result


def _agent_usage(row: sqlite3.Row) -> AgentUsage:
    cached = row["cached_input_tokens"]
    reasoning = row["reasoning_output_tokens"]
    return AgentUsage(
        agent=row["agent"],
        tokens=TokenUsage(
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            total_tokens=row["total_tokens"],
            cached_input_tokens=cached if cached not in (None, 0) else None,
            reasoning_output_tokens=reasoning if reasoning not in (None, 0) else None,
        ),
        model_calls=row["model_calls"],
        model_calls_missing_usage=row["missing_usage"],
    )


def _valid_usage(usage: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not usage:
        return None
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if not isinstance(usage.get(key), int) or int(usage[key]) < 0:
            return None
    return usage


def _detail(value: Any, keys: tuple[str, ...]) -> int | None:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
    return None


def _sum_tokens(values: list[TokenUsage]) -> TokenUsage:
    cached = [value.cached_input_tokens for value in values if value.cached_input_tokens is not None]
    reasoning = [value.reasoning_output_tokens for value in values if value.reasoning_output_tokens is not None]
    return TokenUsage(
        input_tokens=sum(value.input_tokens for value in values),
        output_tokens=sum(value.output_tokens for value in values),
        total_tokens=sum(value.total_tokens for value in values),
        cached_input_tokens=sum(cached) if cached else None,
        reasoning_output_tokens=sum(reasoning) if reasoning else None,
    )


def _sum_diagnostics(values: list[RunDiagnostics]) -> RunDiagnostics:
    return RunDiagnostics(
        tokens=_sum_tokens([value.tokens for value in values]),
        token_usage_partial=any(value.token_usage_partial for value in values),
        model_calls=sum(value.model_calls for value in values),
        model_calls_missing_usage=sum(value.model_calls_missing_usage for value in values),
        tool_calls=sum(value.tool_calls for value in values),
        elapsed_ms=sum(value.elapsed_ms for value in values),
    )


def _derive_title(question: str) -> str:
    compact = " ".join(question.split())
    return (compact[:57] + "…") if len(compact) > 58 else (compact or "New chat")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
