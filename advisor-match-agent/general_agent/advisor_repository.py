"""Durable, corporation-scoped advisor evidence and audit repository."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from general_agent.schemas import Artifact, Attachment, utc_now
from general_agent.workspace import validate_corp_id


class AdvisorRepository:
    """SQLite repository containing no transient conversations or graph state."""

    def __init__(self, path: Path, default_corp_id: str = "A123456") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.default_corp_id = validate_corp_id(default_corp_id)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _corp(self, corp_id: str | None) -> str:
        return validate_corp_id(corp_id or self.default_corp_id)

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS advisor_attachments (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    protected_path TEXT NOT NULL,
                    derived_from_attachment_id TEXT,
                    transformation_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS advisor_attachments_scope_idx
                    ON advisor_attachments(corp_id, conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS advisor_reference_snapshots (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    source_attachment_id TEXT,
                    manifest_json TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    consumed_by_session_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS advisor_reference_attachment_idx
                    ON advisor_reference_snapshots(
                        corp_id, conversation_id, source_attachment_id
                    ) WHERE source_attachment_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS advisor_match_sessions (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    source_attachment_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    mapping_json TEXT NOT NULL,
                    input_summary_json TEXT NOT NULL,
                    source_transformation_json TEXT NOT NULL DEFAULT '{}',
                    reference_json TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    output_artifact_id TEXT,
                    policy_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS advisor_match_sessions_scope_idx
                    ON advisor_match_sessions(corp_id, conversation_id, updated_at);

                CREATE TABLE IF NOT EXISTS advisor_match_review_audits (
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

                CREATE TABLE IF NOT EXISTS advisor_override_proposals (
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

                CREATE TABLE IF NOT EXISTS advisor_artifacts (
                    id TEXT PRIMARY KEY,
                    corp_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    match_session_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(corp_id, match_session_id, revision)
                );
                """
            )

    def add_attachment(
        self,
        *,
        corp_id: str,
        conversation_id: str,
        run_id: str,
        attachment: Attachment,
        protected_path: Path,
    ) -> None:
        corp = self._corp(corp_id)
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO advisor_attachments(
                    id, corp_id, conversation_id, run_id, original_name,
                    content_type, size_bytes, sha256, protected_path,
                    derived_from_attachment_id, transformation_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attachment.attachment_id,
                    corp,
                    conversation_id,
                    run_id,
                    attachment.original_name,
                    attachment.content_type,
                    attachment.size_bytes,
                    attachment.sha256,
                    str(protected_path),
                    attachment.derived_from_attachment_id,
                    json.dumps(attachment.transformation, ensure_ascii=False),
                    _iso(attachment.created_at),
                ),
            )

    def attachment_path(
        self,
        attachment_id: str,
        *,
        corp_id: str,
        conversation_id: str | None = None,
    ) -> tuple[Path, str, str]:
        corp = self._corp(corp_id)
        query = "SELECT * FROM advisor_attachments WHERE id=? AND corp_id=?"
        values: list[Any] = [attachment_id, corp]
        if conversation_id is not None:
            query += " AND conversation_id=?"
            values.append(conversation_id)
        with self._lock:
            row = self._connection.execute(query, values).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        return Path(row["protected_path"]), row["original_name"], row["sha256"]

    def attachment_metadata(
        self,
        attachment_id: str,
        *,
        corp_id: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        corp = self._corp(corp_id)
        query = "SELECT * FROM advisor_attachments WHERE id=? AND corp_id=?"
        values: list[Any] = [attachment_id, corp]
        if conversation_id is not None:
            query += " AND conversation_id=?"
            values.append(conversation_id)
        with self._lock:
            row = self._connection.execute(query, values).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        result = dict(row)
        result["transformation"] = json.loads(result.pop("transformation_json"))
        return result

    def create_advisor_reference_snapshot(
        self,
        *,
        snapshot_id: str,
        corp_id: str,
        conversation_id: str,
        source_attachment_id: str | None,
        manifest: Mapping[str, Any],
        snapshot_path: Path,
    ) -> None:
        corp = self._corp(corp_id)
        with self._lock, self._connection:
            if source_attachment_id is not None and not self._connection.execute(
                """SELECT 1 FROM advisor_attachments
                WHERE id=? AND corp_id=? AND conversation_id=?""",
                (source_attachment_id, corp, conversation_id),
            ).fetchone():
                raise KeyError(source_attachment_id)
            self._connection.execute(
                """INSERT INTO advisor_reference_snapshots(
                    id, corp_id, conversation_id, source_attachment_id,
                    manifest_json, snapshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    corp,
                    conversation_id,
                    source_attachment_id,
                    json.dumps(manifest, ensure_ascii=False, default=str),
                    str(snapshot_path),
                    _iso(utc_now()),
                ),
            )

    def get_advisor_reference_snapshot_for_attachment(
        self, attachment_id: str, *, corp_id: str, conversation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM advisor_reference_snapshots
                WHERE source_attachment_id=? AND corp_id=? AND conversation_id=?""",
                (attachment_id, self._corp(corp_id), conversation_id),
            ).fetchone()
        return _snapshot(row, attachment_id)

    def get_advisor_reference_snapshot(
        self,
        snapshot_id: str,
        *,
        corp_id: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        query = "SELECT * FROM advisor_reference_snapshots WHERE id=? AND corp_id=?"
        values: list[Any] = [snapshot_id, self._corp(corp_id)]
        if conversation_id is not None:
            query += " AND conversation_id=?"
            values.append(conversation_id)
        with self._lock:
            row = self._connection.execute(query, values).fetchone()
        return _snapshot(row, snapshot_id)

    def create_advisor_match_session(
        self,
        *,
        corp_id: str,
        conversation_id: str,
        source_attachment_id: str,
        source_name: str,
        source_sha256: str,
        mapping: Mapping[str, Any],
        input_summary: Mapping[str, Any],
        source_transformation: Mapping[str, Any],
        reference: Mapping[str, Any],
        decisions: list[Mapping[str, Any]],
        counts: Mapping[str, Any],
        policy_version: str,
    ) -> str:
        corp = self._corp(corp_id)
        session_id = "ams_" + uuid.uuid4().hex
        now = _iso(utc_now())
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE advisor_reference_snapshots
                SET consumed_by_session_id=COALESCE(consumed_by_session_id, ?)
                WHERE id=? AND corp_id=? AND conversation_id=? AND source_attachment_id=?""",
                (
                    session_id,
                    str(reference["reference_snapshot_id"]),
                    corp,
                    conversation_id,
                    source_attachment_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("The reference snapshot does not belong to this attachment.")
            self._connection.execute(
                """INSERT INTO advisor_match_sessions(
                    id, corp_id, conversation_id, source_attachment_id, source_name,
                    source_sha256, mapping_json, input_summary_json,
                    source_transformation_json, reference_json, decisions_json,
                    counts_json, policy_version, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Reviewing', ?, ?)""",
                (
                    session_id,
                    corp,
                    conversation_id,
                    source_attachment_id,
                    source_name,
                    source_sha256,
                    _json(mapping),
                    _json(input_summary),
                    _json(source_transformation),
                    _json(reference),
                    _json(decisions),
                    _json(counts),
                    policy_version,
                    now,
                    now,
                ),
            )
        return session_id

    def get_advisor_match_session(
        self,
        session_id: str,
        *,
        corp_id: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        query = "SELECT * FROM advisor_match_sessions WHERE id=? AND corp_id=?"
        values: list[Any] = [session_id, self._corp(corp_id)]
        if conversation_id is not None:
            query += " AND conversation_id=?"
            values.append(conversation_id)
        with self._lock:
            row = self._connection.execute(query, values).fetchone()
        return _session(row, session_id)

    def get_latest_advisor_match_session(
        self, conversation_id: str, *, corp_id: str
    ) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM advisor_match_sessions
                WHERE conversation_id=? AND corp_id=?
                ORDER BY updated_at DESC, created_at DESC LIMIT 1""",
                (conversation_id, self._corp(corp_id)),
            ).fetchone()
        return _session(row, conversation_id)

    def update_advisor_match_session(
        self,
        session_id: str,
        *,
        corp_id: str,
        decisions: list[Mapping[str, Any]],
        counts: Mapping[str, Any],
        status: str | None = None,
        audits: list[Mapping[str, Any]] | None = None,
        proposal_ids: list[str] | None = None,
    ) -> None:
        corp = self._corp(corp_id)
        assignments = "decisions_json=?, counts_json=?, updated_at=?, revision=revision+1"
        values: list[Any] = [_json(decisions), _json(counts), _iso(utc_now())]
        if status is not None:
            assignments += ", status=?"
            values.append(status)
        values.extend((session_id, corp))
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE advisor_match_sessions SET {assignments} WHERE id=? AND corp_id=?",
                values,
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)
            for audit in audits or []:
                self._connection.execute(
                    """INSERT INTO advisor_match_review_audits(
                        id, corp_id, session_id, review_item_id, action, crd_number,
                        note, prior_decision_json, new_decision_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "amd_" + uuid.uuid4().hex,
                        corp,
                        session_id,
                        audit["review_item_id"],
                        audit["action"],
                        audit.get("crd_number"),
                        audit.get("note", ""),
                        _json(audit["prior"]),
                        _json(audit["new"]),
                        _iso(utc_now()),
                    ),
                )
            for proposal_id in proposal_ids or []:
                changed = self._connection.execute(
                    """UPDATE advisor_override_proposals SET status='Applied'
                    WHERE id=? AND corp_id=? AND status='Pending'""",
                    (proposal_id, corp),
                )
                if changed.rowcount == 0:
                    raise KeyError(proposal_id)

    def create_advisor_override_proposal(
        self,
        *,
        corp_id: str,
        session_id: str,
        review_item_id: str,
        crd_number: str,
        advisor: Mapping[str, Any],
        reference_sha256: str,
        created_run_id: str,
    ) -> str:
        proposal_id = "amp_" + uuid.uuid4().hex
        corp = self._corp(corp_id)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM advisor_match_sessions WHERE id=? AND corp_id=?",
                (session_id, corp),
            ).fetchone():
                raise KeyError(session_id)
            self._connection.execute(
                """INSERT INTO advisor_override_proposals(
                    id, corp_id, session_id, review_item_id, crd_number,
                    advisor_json, reference_sha256, created_run_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)""",
                (
                    proposal_id,
                    corp,
                    session_id,
                    review_item_id,
                    crd_number,
                    _json(advisor),
                    reference_sha256,
                    created_run_id,
                    _iso(utc_now()),
                ),
            )
        return proposal_id

    def get_advisor_override_proposal(self, proposal_id: str, *, corp_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM advisor_override_proposals WHERE id=? AND corp_id=?",
                (proposal_id, self._corp(corp_id)),
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        value = dict(row)
        value["advisor"] = json.loads(value.pop("advisor_json"))
        return value

    def cancel_advisor_override_proposal(
        self, proposal_id: str, *, corp_id: str
    ) -> bool:
        corp = self._corp(corp_id)
        with self._lock, self._connection:
            changed = self._connection.execute(
                """UPDATE advisor_override_proposals SET status='Cancelled'
                WHERE id=? AND corp_id=? AND status='Pending'""",
                (proposal_id, corp),
            )
        return changed.rowcount > 0

    def add_artifact(
        self,
        artifact: Artifact,
        snapshot_path: Path,
        *,
        corp_id: str,
        conversation_id: str,
    ) -> None:
        corp = self._corp(corp_id)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM advisor_match_sessions WHERE id=? AND corp_id=?",
                (artifact.match_session_id, corp),
            ).fetchone():
                raise KeyError(artifact.match_session_id)
            self._connection.execute(
                """INSERT INTO advisor_artifacts(
                    id, corp_id, conversation_id, run_id, match_session_id,
                    revision, relative_path, size_bytes, sha256, snapshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    corp,
                    conversation_id,
                    artifact.run_id,
                    artifact.match_session_id,
                    artifact.revision,
                    artifact.relative_path,
                    artifact.size_bytes,
                    artifact.sha256,
                    str(snapshot_path),
                    _iso(artifact.created_at),
                ),
            )

    def set_advisor_match_artifact(
        self, session_id: str, artifact_id: str, *, corp_id: str
    ) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE advisor_match_sessions SET output_artifact_id=? WHERE id=? AND corp_id=?",
                (artifact_id, session_id, self._corp(corp_id)),
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)

    def artifact_path(self, artifact_id: str, *, corp_id: str) -> tuple[Path, str]:
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_path, relative_path FROM advisor_artifacts WHERE id=? AND corp_id=?",
                (artifact_id, self._corp(corp_id)),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return Path(row["snapshot_path"]), Path(row["relative_path"]).name


def _snapshot(row: sqlite3.Row | None, key: str) -> dict[str, Any]:
    if row is None:
        raise KeyError(key)
    value = dict(row)
    value["manifest"] = json.loads(value.pop("manifest_json"))
    return value


def _session(row: sqlite3.Row | None, key: str) -> dict[str, Any]:
    if row is None:
        raise KeyError(key)
    value = dict(row)
    for field in (
        "mapping_json",
        "input_summary_json",
        "source_transformation_json",
        "reference_json",
        "decisions_json",
        "counts_json",
    ):
        value[field.removesuffix("_json")] = json.loads(value.pop(field))
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _iso(value) -> str:
    return value.isoformat()
