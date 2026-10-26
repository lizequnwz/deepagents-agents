"""Atomic dashboard revisions over the existing local metadata store."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from uuid import uuid4

from data_analytics_agent.dashboard.schemas import (
    DashboardAction,
    DashboardActionRecord,
    DashboardCandidate,
    DashboardRevision,
    DashboardSpec,
)
from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.persistence import LocalStorage


class DashboardConflict(ValueError):
    """The requested revision or idempotency key is no longer usable."""


def _hash(value):
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DashboardStore:
    def __init__(self, storage: LocalStorage | None = None):
        self.storage = storage or LocalStorage()
        self._lock = RLock()

    def _write(self, connection, kind, key, value):
        payload = (
            value.model_dump_json()
            if hasattr(value, "model_dump_json")
            else json.dumps(value)
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata VALUES (?,?,?)", (kind, key, payload)
        )

    def _read(self, connection, kind, key, model=None):
        row = connection.execute(
            "SELECT payload FROM metadata WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        if not row:
            return None
        return model.model_validate_json(row[0]) if model else json.loads(row[0])

    def _scope(self, revision, thread_id, source_id):
        if (
            revision is None
            or revision.thread_id != thread_id
            or revision.source_id != source_id
        ):
            raise StoreNotFound("Unknown dashboard in this conversation.")
        return revision

    def get(self, dashboard_id, thread_id, *, source_id):
        with self.storage.connect() as connection:
            head = self._read(connection, "dashboard_heads", dashboard_id)
            revision = (
                self._read(
                    connection,
                    "dashboard_revisions",
                    head["revision_id"],
                    DashboardRevision,
                )
                if head
                else None
            )
        return self._scope(revision, thread_id, source_id)

    def get_revision(self, revision_id, thread_id, *, source_id):
        revision = self.storage.get(
            "dashboard_revisions", revision_id, DashboardRevision
        )
        return self._scope(revision, thread_id, source_id)

    def list_for_conversation(self, thread_id, *, source_id):
        with self.storage.connect() as connection:
            heads = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload FROM metadata WHERE kind='dashboard_heads'"
                )
            ]
            revisions = [
                self._read(
                    connection,
                    "dashboard_revisions",
                    h["revision_id"],
                    DashboardRevision,
                )
                for h in heads
            ]
        return sorted(
            [
                r
                for r in revisions
                if r and r.thread_id == thread_id and r.source_id == source_id
            ],
            key=lambda r: r.created_at,
            reverse=True,
        )

    def history(self, dashboard_id, thread_id, *, source_id):
        self.get(dashboard_id, thread_id, source_id=source_id)
        return sorted(
            [
                r
                for r in self.storage.load(
                    "dashboard_revisions", DashboardRevision
                ).values()
                if r.dashboard_id == dashboard_id
                and r.thread_id == thread_id
                and r.source_id == source_id
            ],
            key=lambda r: r.version,
        )

    def create_candidate(
        self,
        spec: DashboardSpec,
        *,
        thread_id,
        source_id,
        run_id,
        question,
        dashboard_id=None,
        expected_revision=None,
        request_id=None,
        applied_filters=None,
        saved_filter_values=None,
    ):
        with self._lock:
            previous = (
                self.get(dashboard_id, thread_id, source_id=source_id)
                if dashboard_id
                else None
            )
            if previous and previous.revision_id != expected_revision:
                raise DashboardConflict(
                    "The dashboard changed. Reload before updating it."
                )
            if not previous and expected_revision:
                raise DashboardConflict(
                    "A new dashboard cannot declare a previous revision."
                )
            if request_id:
                existing = [
                    c
                    for c in self.storage.load(
                        "dashboard_candidates", DashboardCandidate
                    ).values()
                    if c.revision.run_id == run_id and c.request_id == request_id
                ]
                if existing:
                    candidate = existing[0]
                    if (
                        candidate.revision.spec != spec
                        or candidate.revision.applied_filters != (applied_filters or {})
                    ):
                        raise DashboardConflict(
                            "The dashboard request ID was reused with different content."
                        )
                    return candidate.revision
            pending = [
                c
                for c in self.storage.load(
                    "dashboard_candidates", DashboardCandidate
                ).values()
                if c.revision.run_id == run_id and c.status == "preparing"
            ]
            for candidate in pending:
                if (
                    candidate.revision.spec == spec
                    and candidate.revision.applied_filters == (applied_filters or {})
                ):
                    return candidate.revision
                self.storage.put(
                    "dashboard_candidates",
                    candidate.revision.revision_id,
                    candidate.model_copy(
                        update={
                            "status": "failed",
                            "error": "Superseded by a revised dashboard candidate in the same run.",
                        }
                    ),
                )
            revision = DashboardRevision(
                dashboard_id=dashboard_id or str(uuid4()),
                revision_id=str(uuid4()),
                version=previous.version + 1 if previous else 1,
                thread_id=thread_id,
                source_id=source_id,
                run_id=run_id,
                question=question,
                spec=spec,
                applied_filters=applied_filters or {},
                saved_filter_values=saved_filter_values
                if saved_filter_values is not None
                else applied_filters or {},
                created_at=datetime.now(timezone.utc),
            )
            self.storage.put(
                "dashboard_candidates",
                revision.revision_id,
                DashboardCandidate(
                    revision=revision,
                    expected_revision=expected_revision,
                    request_id=request_id,
                ),
            )
            return revision

    def candidate_for_run(self, run_id):
        candidates = [
            c
            for c in self.storage.load(
                "dashboard_candidates", DashboardCandidate
            ).values()
            if c.revision.run_id == run_id and c.status != "failed"
        ]
        return (
            max(candidates, key=lambda c: c.revision.created_at).revision
            if candidates
            else None
        )

    def finalize_for_run(self, run_id, report_id):
        if not report_id:
            raise ValueError(
                "Dashboard publication requires the completed HTML report."
            )
        candidates = [
            c
            for c in self.storage.load(
                "dashboard_candidates", DashboardCandidate
            ).values()
            if c.revision.run_id == run_id
        ]
        finalized = []
        for candidate in candidates:
            if candidate.status == "failed":
                continue
            revision = candidate.revision.model_copy(update={"report_id": report_id})
            try:
                with self._lock, self.storage.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    if candidate.status == "committed":
                        saved = self._read(
                            connection,
                            "dashboard_revisions",
                            revision.revision_id,
                            DashboardRevision,
                        )
                        if saved:
                            finalized.append(saved)
                            continue
                    head = self._read(
                        connection, "dashboard_heads", revision.dashboard_id
                    )
                    actual = head["revision_id"] if head else None
                    if actual != candidate.expected_revision:
                        raise DashboardConflict(
                            "The dashboard changed while this action ran. Its candidate was not applied."
                        )
                    self._write(
                        connection,
                        "dashboard_revisions",
                        revision.revision_id,
                        revision,
                    )
                    self._write(
                        connection,
                        "dashboard_heads",
                        revision.dashboard_id,
                        {
                            "revision_id": revision.revision_id,
                            "thread_id": revision.thread_id,
                            "source_id": revision.source_id,
                        },
                    )
                    self._write(
                        connection,
                        "dashboard_candidates",
                        revision.revision_id,
                        candidate.model_copy(
                            update={"revision": revision, "status": "committed"}
                        ),
                    )
                    for action in self._actions(connection):
                        if (
                            action.run_id == run_id
                            and action.dashboard_id == revision.dashboard_id
                        ):
                            self._write(
                                connection,
                                "dashboard_actions",
                                action.action_id,
                                action.model_copy(
                                    update={
                                        "status": "completed",
                                        "result_revision_id": revision.revision_id,
                                        "error": None,
                                    }
                                ),
                            )
                finalized.append(revision)
            except DashboardConflict as exc:
                self.storage.put(
                    "dashboard_candidates",
                    revision.revision_id,
                    candidate.model_copy(
                        update={"status": "failed", "error": str(exc)}
                    ),
                )
                self.fail_for_run(run_id, str(exc))
                raise
        return finalized

    def commit_view(
        self,
        previous: DashboardRevision,
        spec: DashboardSpec,
        *,
        request_id,
        saved_filter_values=None,
        report_id=None,
    ):
        request = {
            "spec": spec.model_dump(mode="json"),
            "saved_filter_values": saved_filter_values,
            "expected_revision": previous.revision_id,
        }
        if report_id is not None:
            request["report_id"] = report_id
        key = f"{previous.dashboard_id}:{request_id}"
        with self._lock, self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            saved = self._read(connection, "dashboard_view_requests", key)
            if saved:
                if saved["request_hash"] != _hash(request):
                    raise DashboardConflict(
                        "The request ID was reused with different content."
                    )
                return self._read(
                    connection,
                    "dashboard_revisions",
                    saved["revision_id"],
                    DashboardRevision,
                )
            if any(
                action.dashboard_id == previous.dashboard_id
                and action.status in {"queued", "running"}
                for action in self._actions(connection)
            ):
                raise DashboardConflict(
                    "Finish or resume the pending dashboard action before saving its view."
                )
            head = self._read(connection, "dashboard_heads", previous.dashboard_id)
            if not head or head["revision_id"] != previous.revision_id:
                raise DashboardConflict(
                    "The dashboard changed. Reload before saving the view."
                )
            if report_id is not None:
                report = self._read(connection, "reports", report_id)
                original_report = self._read(connection, "reports", previous.report_id)
                if (
                    not report
                    or not original_report
                    or (report["thread_id"], report["source_id"])
                    != (previous.thread_id, previous.source_id)
                    or report.get("previous_report_id") != previous.report_id
                    or set(report["input_result_ids"])
                    != set(original_report["input_result_ids"])
                    or set(report["input_analysis_ids"])
                    != set(original_report["input_analysis_ids"])
                ):
                    raise ValueError(
                        "The presentation report must revise the same scoped saved evidence."
                    )
            revised = previous.model_copy(
                update={
                    "revision_id": str(uuid4()),
                    "version": previous.version + 1,
                    "spec": spec,
                    "report_id": report_id
                    if report_id is not None
                    else previous.report_id,
                    "saved_filter_values": saved_filter_values
                    if saved_filter_values is not None
                    else previous.saved_filter_values,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            self._write(connection, "dashboard_revisions", revised.revision_id, revised)
            self._write(
                connection,
                "dashboard_heads",
                revised.dashboard_id,
                {
                    "revision_id": revised.revision_id,
                    "thread_id": revised.thread_id,
                    "source_id": revised.source_id,
                },
            )
            self._write(
                connection,
                "dashboard_view_requests",
                key,
                {
                    "request_hash": _hash(request),
                    "revision_id": revised.revision_id,
                    "thread_id": revised.thread_id,
                    "source_id": revised.source_id,
                },
            )
            return revised

    def _actions(self, connection):
        return [
            DashboardActionRecord.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT payload FROM metadata WHERE kind='dashboard_actions'"
            )
        ]

    def begin_action(
        self, dashboard_id, thread_id, *, source_id, action: DashboardAction
    ):
        with self._lock, self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = next(
                (
                    a
                    for a in self._actions(connection)
                    if a.dashboard_id == dashboard_id
                    and a.request_id == action.request_id
                ),
                None,
            )
            if previous:
                revision = self._read(
                    connection,
                    "dashboard_revisions",
                    previous.revision_id,
                    DashboardRevision,
                )
                self._scope(revision, thread_id, source_id)
                if previous.request_hash != _hash(action):
                    raise DashboardConflict(
                        "The request ID was reused with different content."
                    )
                return previous
            head = self._read(connection, "dashboard_heads", dashboard_id)
            revision = (
                self._read(
                    connection,
                    "dashboard_revisions",
                    head["revision_id"],
                    DashboardRevision,
                )
                if head
                else None
            )
            self._scope(revision, thread_id, source_id)
            if revision.revision_id != action.expected_revision:
                raise DashboardConflict(
                    "The dashboard changed. Reload before applying the action."
                )
            if any(
                a.dashboard_id == dashboard_id and a.status in {"queued", "running"}
                for a in self._actions(connection)
            ):
                raise DashboardConflict("This dashboard already has an active action.")
            record = DashboardActionRecord(
                action_id=str(uuid4()),
                dashboard_id=dashboard_id,
                revision_id=revision.revision_id,
                request_id=action.request_id,
                request_hash=_hash(action),
                action=action,
                created_at=datetime.now(timezone.utc),
            )
            self._write(connection, "dashboard_actions", record.action_id, record)
            return record

    def attach_action_run(self, action_id, run_id):
        with self._lock:
            action = self.storage.get(
                "dashboard_actions", action_id, DashboardActionRecord
            )
            if action is None:
                raise StoreNotFound(action_id)
            if action.run_id and action.run_id != run_id:
                raise DashboardConflict("This action already belongs to another run.")
            action = action.model_copy(update={"run_id": run_id, "status": "running"})
            self.storage.put("dashboard_actions", action_id, action)
            return action

    def action_for_run(self, run_id):
        return next(
            (
                a
                for a in self.storage.load(
                    "dashboard_actions", DashboardActionRecord
                ).values()
                if a.run_id == run_id
            ),
            None,
        )

    def latest_action(self, dashboard_id, thread_id, *, source_id):
        self.get(dashboard_id, thread_id, source_id=source_id)
        actions = [
            a
            for a in self.storage.load(
                "dashboard_actions", DashboardActionRecord
            ).values()
            if a.dashboard_id == dashboard_id
        ]
        return max(actions, key=lambda a: a.created_at) if actions else None

    def fail_for_run(self, run_id, error):
        for action in self.storage.load(
            "dashboard_actions", DashboardActionRecord
        ).values():
            if action.run_id == run_id and action.status in {"queued", "running"}:
                self.storage.put(
                    "dashboard_actions",
                    action.action_id,
                    action.model_copy(update={"status": "failed", "error": error}),
                )

    def fail_action(self, action_id, error):
        action = self.storage.get("dashboard_actions", action_id, DashboardActionRecord)
        if action is None:
            raise StoreNotFound(action_id)
        if action.status in {"queued", "running"}:
            action = action.model_copy(update={"status": "failed", "error": error})
            self.storage.put("dashboard_actions", action_id, action)
        return action

    def forget_conversations(self, thread_ids):
        with self._lock, self.storage.connect() as connection:
            revisions = [
                DashboardRevision.model_validate_json(r[0])
                for r in connection.execute(
                    "SELECT payload FROM metadata WHERE kind='dashboard_revisions'"
                )
            ]
            dashboard_ids = {
                r.dashboard_id for r in revisions if r.thread_id in thread_ids
            }
            candidates = [
                DashboardCandidate.model_validate_json(r[0])
                for r in connection.execute(
                    "SELECT payload FROM metadata WHERE kind='dashboard_candidates'"
                )
            ]
            dashboard_ids.update(
                c.revision.dashboard_id
                for c in candidates
                if c.revision.thread_id in thread_ids
            )
            for revision in revisions:
                if revision.dashboard_id in dashboard_ids:
                    connection.execute(
                        "DELETE FROM metadata WHERE kind='dashboard_revisions' AND id=?",
                        (revision.revision_id,),
                    )
            for candidate in candidates:
                if candidate.revision.dashboard_id in dashboard_ids:
                    connection.execute(
                        "DELETE FROM metadata WHERE kind='dashboard_candidates' AND id=?",
                        (candidate.revision.revision_id,),
                    )
            for dashboard_id in dashboard_ids:
                connection.execute(
                    "DELETE FROM metadata WHERE kind='dashboard_heads' AND id=?",
                    (dashboard_id,),
                )
            for action in self._actions(connection):
                if action.dashboard_id in dashboard_ids:
                    connection.execute(
                        "DELETE FROM metadata WHERE kind='dashboard_actions' AND id=?",
                        (action.action_id,),
                    )
            for (key,) in connection.execute(
                "SELECT id FROM metadata WHERE kind='dashboard_view_requests'"
            ).fetchall():
                if key.split(":", 1)[0] in dashboard_ids:
                    connection.execute(
                        "DELETE FROM metadata WHERE kind='dashboard_view_requests' AND id=?",
                        (key,),
                    )

    def recover(self, runs):
        """Repair interrupted action reservations without resuming computation."""
        for action in self.storage.load(
            "dashboard_actions", DashboardActionRecord
        ).values():
            if action.status not in {"queued", "running"}:
                continue
            error = None
            if action.run_id is None:
                error = "The application stopped before this action started. Apply the action again."
            else:
                try:
                    run = runs.get(action.run_id)
                    if run.status == "failed":
                        error = run.error or "The dashboard action failed."
                except StoreNotFound:
                    error = "The dashboard action run is unavailable."
            if error:
                self.storage.put(
                    "dashboard_actions",
                    action.action_id,
                    action.model_copy(update={"status": "failed", "error": error}),
                )
