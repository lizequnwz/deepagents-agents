"""Narrow LangChain tools for advisor profiling, matching, and review."""

from __future__ import annotations

import csv
import itertools
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.input_loader import load_input
from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.policy import POLICY_VERSION
from general_agent.advisor_matching.profiler import profile_advisor_file as profile_file
from general_agent.advisor_matching.schemas import (
    AdvisorRecord, InputMapping, MASTER_COLUMNS, MatchCandidate, MatchCounts,
    MatchDecision, MatchRunResult, MatchStatus, ReferenceSnapshotManifest,
    ReviewDecision,
)
from general_agent.advisor_matching.source import AdvisorReferenceSource, sha256_file
from general_agent.advisor_matching.workbook import write_match_workbook
from general_agent.config import Settings
from general_agent.store import Store
from general_agent.workspace import Workspace, current_conversation_id, current_corp_id


def build_advisor_tools(
    *, settings: Settings, workspace: Workspace, backend: AdvisorWorkspaceBackend,
    store: Store, advisor_source: AdvisorReferenceSource,
) -> list[BaseTool]:
    def current_context() -> tuple[str, str]:
        corp_id, conversation_id = current_corp_id(), current_conversation_id()
        if not corp_id or not conversation_id:
            raise RuntimeError("The active corporation and conversation context is unavailable.")
        return corp_id, conversation_id

    def resolve_upload(virtual_path: str) -> Path:
        corp_id, conversation_id = current_context()
        source = workspace.resolve_agent(virtual_path, must_exist=True)
        upload_root = (workspace.chat_root(corp_id, conversation_id) / "uploads").resolve()
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(upload_root):
            raise ValueError("Advisor input must be an upload in the current chat.")
        if source.suffix.lower() not in {".csv", ".xlsx"}:
            raise ValueError("Advisor matching accepts only CSV or XLSX uploads.")
        return source

    @tool
    def profile_advisor_file(input_virtual_path: str) -> dict[str, Any]:
        """Profile one uploaded advisor CSV/XLSX for sheet and column mapping."""
        return profile_file(resolve_upload(input_virtual_path), settings)

    @tool
    def find_all_advisors_in_database() -> dict[str, Any]:
        """Export the complete authoritative advisor source for this run."""
        target = backend.run_temp_path("advisor_reference.csv")
        temporary = target.with_name(".advisor_reference.csv.building")
        records = list(itertools.islice(
            advisor_source.iter_records(), settings.advisor_max_reference_rows + 1
        ))
        if not records:
            raise ValueError("Advisor reference source is empty.")
        if len(records) > settings.advisor_max_reference_rows:
            raise ValueError("Advisor reference source exceeds the configured row limit.")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MASTER_COLUMNS)
            writer.writeheader()
            writer.writerows(record.master_dict() for record in records)
        temporary.replace(target)
        manifest = ReferenceSnapshotManifest(
            snapshot_virtual_path="/tmp/advisor_reference.csv", row_count=len(records),
            columns=list(MASTER_COLUMNS), source_kind=advisor_source.source_kind,
            schema_version=advisor_source.schema_version, retrieved_at=datetime.now(UTC),
            sha256=sha256_file(target), query_id=None,
        )
        return manifest.model_dump(mode="json")

    @tool
    def start_advisor_match(
        input_virtual_path: str,
        snapshot_virtual_path: str,
        mapping: InputMapping,
    ) -> dict[str, Any]:
        """Deterministically match an upload and create a persisted review session."""
        if snapshot_virtual_path != "/tmp/advisor_reference.csv":
            raise ValueError("Use the complete snapshot returned for the active run.")
        corp_id, conversation_id = current_context()
        source = resolve_upload(input_virtual_path)
        snapshot = backend.run_temp_path("advisor_reference.csv")
        advisors = _read_reference(snapshot)
        rows = load_input(source, mapping, max_rows=settings.advisor_max_input_rows)
        decisions, counts, warnings = run_matching(rows, advisors)
        reference = ReferenceSnapshotManifest(
            snapshot_virtual_path="/tmp/advisor_reference.csv", row_count=len(advisors),
            columns=list(MASTER_COLUMNS), source_kind=advisor_source.source_kind,
            schema_version=advisor_source.schema_version, retrieved_at=datetime.now(UTC),
            sha256=sha256_file(snapshot), query_id=None,
        )
        relative = workspace.user_relative(corp_id, source)
        session_id = store.create_advisor_match_session(
            corp_id=corp_id, conversation_id=conversation_id,
            source_relative_path=relative, source_name=source.name,
            source_sha256=sha256_file(source), mapping=mapping.model_dump(mode="json"),
            reference=reference.model_dump(mode="json"),
            decisions=[decision.model_dump(mode="json") for decision in decisions],
            counts=counts.model_dump(mode="json"), output_relative_path="advisor_matches.xlsx",
            policy_version=POLICY_VERSION,
        )
        _write_session_workbook(workspace, store, corp_id, session_id)
        return MatchRunResult(
            match_session_id=session_id, output_virtual_path="/advisor_matches.xlsx",
            selected_sheet=mapping.sheet_name, counts=counts, warnings=warnings,
            policy_version=POLICY_VERSION,
        ).model_dump(mode="json")

    @tool
    def get_current_advisor_match_session() -> dict[str, Any]:
        """Return the latest persisted match-session summary for this conversation."""
        corp_id, conversation_id = current_context()
        try:
            session = store.get_latest_advisor_match_session(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise ValueError(
                "No advisor match session exists for the current conversation."
            ) from exc
        return {
            "match_session_id": session["id"],
            "source_name": session["source_name"],
            "counts": session["counts"],
            "status": session["status"],
            "revision": session["revision"],
            "output_virtual_path": "/advisor_matches.xlsx",
            "updated_at": session["updated_at"],
        }

    @tool
    def list_advisor_match_items(
        match_session_id: str,
        status: str | None = None,
        source_row_number: int | None = None,
        name_query: str | None = None,
        cursor: int = 0,
        limit: int = 10,
    ) -> dict[str, Any]:
        """List review items; status accepts labels or snake_case count keys."""
        corp_id, _ = current_context()
        if cursor < 0 or limit < 1 or limit > 20:
            raise ValueError("cursor must be nonnegative and limit must be between 1 and 20.")
        session = store.get_advisor_match_session(match_session_id, corp_id=corp_id)
        items = [MatchDecision.model_validate(value) for value in session["decisions"]]
        normalized_status = _normalize_status_filter(status)
        if normalized_status:
            items = [item for item in items if item.status == normalized_status]
        if source_row_number is not None:
            items = [item for item in items if item.source_row_number == source_row_number]
        if name_query:
            query = name_query.strip().casefold()
            items = [item for item in items if query in " ".join((item.mapped_values.get("first_name", ""), item.mapped_values.get("last_name", ""), item.mapped_values.get("full_name", ""))).casefold()]
        page = items[cursor : cursor + limit]
        return {
            "match_session_id": match_session_id,
            "items": [_review_view(item) for item in page],
            "total": len(items),
            "next_cursor": cursor + limit if cursor + limit < len(items) else None,
        }

    @tool
    def propose_manual_crd_override(
        match_session_id: str, review_item_id: str, crd_number: str,
        snapshot_virtual_path: str,
    ) -> dict[str, Any]:
        """Resolve a user-supplied unlisted CRD and create a pending confirmation proposal."""
        if snapshot_virtual_path != "/tmp/advisor_reference.csv":
            raise ValueError("Retrieve a fresh complete advisor snapshot first.")
        corp_id, _ = current_context()
        session = store.get_advisor_match_session(match_session_id, corp_id=corp_id)
        item = _find_item(session, review_item_id)
        record = next((candidate for candidate in _read_reference(backend.run_temp_path("advisor_reference.csv")) if candidate.crd_number == crd_number), None)
        if record is None:
            raise ValueError("The supplied CRD does not exist in the current advisor reference.")
        candidate = MatchCandidate(**record.model_dump(), matched_fields=[], conflicting_fields=[])
        proposal_id = store.create_advisor_override_proposal(
            corp_id=corp_id, session_id=match_session_id, review_item_id=review_item_id,
            crd_number=crd_number, advisor=candidate.model_dump(mode="json"),
            reference_sha256=sha256_file(backend.run_temp_path("advisor_reference.csv")),
            created_run_id=backend.active_run_id or "",
        )
        return {"proposal_id": proposal_id, "review_item": _review_view(item), "resolved_advisor": candidate.model_dump(exclude={"internal_score"}), "requires_explicit_confirmation": True}

    @tool
    def apply_advisor_review_decisions(
        match_session_id: str,
        decisions: list[ReviewDecision],
        approve_session: bool = False,
    ) -> dict[str, Any]:
        """Apply explicit user review decisions and deterministically regenerate the workbook."""
        corp_id, _ = current_context()
        if len(decisions) > 20:
            raise ValueError("Apply at most 20 review decisions per call.")
        if len({decision.review_item_id for decision in decisions}) != len(decisions):
            raise ValueError("Each review item may appear only once per call.")
        session = store.get_advisor_match_session(match_session_id, corp_id=corp_id)
        items = [MatchDecision.model_validate(value) for value in session["decisions"]]
        by_id = {item.review_item_id: item for item in items}
        audits = []
        proposal_ids = []
        for requested in decisions:
            item = by_id.get(requested.review_item_id)
            if item is None:
                raise ValueError(f"Unknown review item: {requested.review_item_id}.")
            prior = item.model_dump(mode="json")
            proposal_id = _apply_review(store, backend, corp_id, session, item, requested)
            if proposal_id:
                proposal_ids.append(proposal_id)
            audits.append((requested, item, prior))
        counts = _counts(items)
        store.update_advisor_match_session(
            match_session_id, corp_id=corp_id,
            decisions=[item.model_dump(mode="json") for item in items],
            counts=counts.model_dump(mode="json"),
            status="Approved" if approve_session else None,
        )
        for proposal_id in proposal_ids:
            store.apply_advisor_override_proposal(proposal_id, corp_id=corp_id)
        for requested, item, prior in audits:
            store.add_advisor_review_decision(
                corp_id=corp_id, session_id=match_session_id,
                review_item_id=item.review_item_id, action=requested.action,
                crd_number=requested.crd_number, note=requested.note,
                prior=prior, new=item.model_dump(mode="json"),
            )
        _write_session_workbook(workspace, store, corp_id, match_session_id)
        return {"match_session_id": match_session_id, "counts": counts.model_dump(), "status": "Approved" if approve_session else session["status"], "output_virtual_path": "/advisor_matches.xlsx", "profile_building_eligible": counts.matched, "profile_building_excluded": counts.ambiguous_match + counts.no_match}

    return [
        profile_advisor_file,
        find_all_advisors_in_database,
        start_advisor_match,
        get_current_advisor_match_session,
        list_advisor_match_items,
        propose_manual_crd_override,
        apply_advisor_review_decisions,
    ]


def _normalize_status_filter(status: str | None) -> MatchStatus | None:
    if status is None or not status.strip():
        return None
    key = " ".join(status.replace("_", " ").replace("-", " ").split()).casefold()
    aliases: dict[str, MatchStatus] = {
        "matched": "Matched",
        "ambiguous": "Ambiguous Match",
        "ambiguous match": "Ambiguous Match",
        "no match": "No Match",
        "unmatched": "No Match",
    }
    normalized = aliases.get(key)
    if normalized is None:
        raise ValueError(
            "Unsupported match status filter. Use matched, ambiguous_match, or no_match."
        )
    return normalized


def _read_reference(path: Path) -> list[AdvisorRecord]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [AdvisorRecord(**{column.lower(): str(row[column] or "").strip() for column in MASTER_COLUMNS}) for row in csv.DictReader(handle)]


def _find_item(session, item_id):
    for value in session["decisions"]:
        item = MatchDecision.model_validate(value)
        if item.review_item_id == item_id:
            return item
    raise ValueError(f"Unknown review item: {item_id}.")


def _review_view(item: MatchDecision) -> dict[str, Any]:
    mapped = {key: value for key, value in item.mapped_values.items() if value}
    return {
        "review_item_id": item.review_item_id, "source_row_number": item.source_row_number,
        "input": mapped, "status": item.status, "confidence": item.confidence,
        "rule_id": item.rule_id, "reason": item.explanation,
        "matched_advisor": item.matched_advisor.model_dump(exclude={"internal_score"}) if item.matched_advisor else None,
        "candidates": [candidate.model_dump(exclude={"internal_score"}) for candidate in item.candidates],
        "duplicate_group": item.duplicate_group,
    }


def _apply_review(store, backend, corp_id, session, item, requested):
    if item.automated_status is None:
        item.automated_status = item.status
    if requested.action == "confirm_candidate":
        candidate = next((candidate for candidate in item.candidates if candidate.crd_number == requested.crd_number), None)
        if candidate is None:
            raise ValueError("The selected CRD was not presented for this review item.")
        item.status, item.confidence, item.rule_id = "Matched", "User Confirmed", "USER_CONFIRMED_OVERRIDE"
        item.matched_advisor, item.decision_source = candidate, "User Override"
        item.explanation = "The user explicitly confirmed a presented advisor candidate."
    elif requested.action == "confirm_manual_crd":
        if not requested.proposal_id:
            raise ValueError("A confirmed manual CRD proposal is required.")
        proposal = store.get_advisor_override_proposal(requested.proposal_id, corp_id=corp_id)
        if proposal["session_id"] != session["id"] or proposal["review_item_id"] != item.review_item_id or proposal["status"] != "Pending":
            raise ValueError("The manual CRD proposal is invalid or stale.")
        if proposal["created_run_id"] == backend.active_run_id:
            raise ValueError("Confirm a manual CRD proposal in a later user turn.")
        if proposal["reference_sha256"] != session["reference"]["sha256"]:
            raise ValueError("The manual CRD proposal uses a different reference snapshot.")
        item.status, item.confidence, item.rule_id = "Matched", "User Confirmed", "USER_CONFIRMED_OVERRIDE"
        item.matched_advisor = MatchCandidate.model_validate(proposal["advisor"])
        item.decision_source = "User Override"
        item.explanation = "The user explicitly confirmed a separately resolved CRD override."
        return requested.proposal_id
    elif requested.action == "confirm_no_match":
        item.status, item.confidence, item.rule_id = "No Match", "None", "USER_CONFIRMED_NO_MATCH"
        item.matched_advisor, item.decision_source = None, "User Override"
        item.explanation = "The user explicitly confirmed that this row should remain unmatched."
    elif requested.action == "reopen":
        raise ValueError("Reopen requires rerunning the deterministic match in this version.")
    return None


def _counts(items):
    return MatchCounts(matched=sum(item.status == "Matched" for item in items), ambiguous_match=sum(item.status == "Ambiguous Match" for item in items), no_match=sum(item.status == "No Match" for item in items))


def _write_session_workbook(workspace, store, corp_id, session_id):
    session = store.get_advisor_match_session(session_id, corp_id=corp_id)
    decisions = [MatchDecision.model_validate(value) for value in session["decisions"]]
    mapping = InputMapping.model_validate(session["mapping"])
    reference = ReferenceSnapshotManifest.model_validate(session["reference"])
    output = workspace.resolve_agent("/advisor_matches.xlsx")
    write_match_workbook(
        output, session_id=session_id, decisions=decisions,
        counts=MatchCounts.model_validate(session["counts"]), mapping=mapping,
        source_name=session["source_name"], source_sha256=session["source_sha256"],
        reference=reference, policy_version=session["policy_version"],
        session_status=session["status"],
        session_revision=session["revision"],
    )
