"""Narrow LangChain tools for advisor profiling, matching, and review."""

from __future__ import annotations

import contextlib
import csv
import itertools
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.augmentation import augment_input_with_firm
from general_agent.advisor_matching.input_loader import validate_and_load_input
from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.policy import POLICY_VERSION
from general_agent.advisor_matching.profiler import (
    inspect_advisor_upload as inspect_upload,
)
from general_agent.advisor_matching.schemas import (
    AdvisorRecord,
    FirmAugmentationResult,
    InputMapping,
    InputSummary,
    MASTER_COLUMNS,
    MappingValidationResult,
    MatchCandidate,
    MatchCounts,
    MatchDecision,
    MatchRunResult,
    MatchStatus,
    ReferenceSnapshotManifest,
    ReviewDecision,
)
from general_agent.advisor_matching.source import AdvisorReferenceSource, sha256_file
from general_agent.advisor_matching.workbook import write_match_workbook
from general_agent.config import Settings
from general_agent.schemas import Artifact, utc_now
from general_agent.store import Store
from general_agent.workspace import (
    Workspace,
    current_conversation_id,
    current_corp_id,
)


def build_advisor_tools(
    *,
    settings: Settings,
    workspace: Workspace,
    backend: AdvisorWorkspaceBackend,
    store: Store,
    advisor_source: AdvisorReferenceSource,
) -> list[BaseTool]:
    def current_context() -> tuple[str, str]:
        corp_id, conversation_id = current_corp_id(), current_conversation_id()
        if not corp_id or not conversation_id:
            raise RuntimeError(
                "The active corporation and conversation context is unavailable."
            )
        return corp_id, conversation_id

    def resolve_upload(attachment_id: str) -> tuple[Path, str]:
        corp_id, conversation_id = current_context()
        try:
            source, original_name, expected_sha256 = store.attachment_path(
                attachment_id,
                corp_id=corp_id,
                conversation_id=conversation_id,
            )
        except KeyError as exc:
            raise ValueError("Advisor attachment is unknown in the current chat.") from exc
        try:
            workspace.validate_file(corp_id, "attachments", source)
        except ValueError as exc:
            raise ValueError("The advisor attachment path is invalid.") from exc
        if source.suffix.lower() not in {".csv", ".xlsx"}:
            raise ValueError("Advisor matching accepts only CSV or XLSX uploads.")
        if expected_sha256 and sha256_file(source) != expected_sha256:
            raise ValueError("The immutable advisor attachment failed integrity validation.")
        return source, original_name

    @tool
    def inspect_advisor_upload(attachment_id: str) -> dict[str, Any]:
        """Inspect bounded raw rows and plausible header interpretations."""

        source, _ = resolve_upload(attachment_id)
        return {"attachment_id": attachment_id, **inspect_upload(source, settings)}

    @tool
    def validate_advisor_input(
        attachment_id: str,
        mapping: InputMapping,
    ) -> dict[str, Any]:
        """Validate one interpreted advisor upload and return its pre-match checkpoint."""

        corp_id, conversation_id = current_context()
        source, _ = resolve_upload(attachment_id)
        loaded = validate_and_load_input(
            source, mapping, max_rows=settings.advisor_max_input_rows
        )
        metadata = store.attachment_metadata(
            attachment_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
        transformation = metadata["transformation"]
        _validate_source_transformation(loaded.rows, mapping, transformation)
        result = MappingValidationResult(
            attachment_id=attachment_id,
            source_sha256=loaded.source_sha256,
            selected_sheet=loaded.selected_sheet,
            mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            columns=loaded.columns,
            input_summary=loaded.summary,
            missing_firm_sample=loaded.missing_firm_sample,
            source_transformation=transformation,
            warnings=_input_summary_warnings(loaded.summary),
        )
        serialized = result.model_dump(mode="json")
        run_id = backend.active_run_id
        if not run_id:
            raise RuntimeError("The active run context is unavailable.")
        store.set_advisor_input_checkpoint(
            corp_id=corp_id,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            validated_run_id=run_id,
            validation=serialized,
        )
        return serialized

    @tool
    def get_current_advisor_input() -> dict[str, Any]:
        """Return the latest validated advisor input checkpoint in this chat."""

        corp_id, conversation_id = current_context()
        try:
            checkpoint = store.get_advisor_input_checkpoint(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise ValueError(
                "No validated advisor input exists in the current chat."
            ) from exc
        return checkpoint["validation"]

    @tool
    def apply_firm_to_advisor_upload(
        firm_name: str,
        attachment_id: str | None = None,
        mapping: InputMapping | None = None,
    ) -> dict[str, Any]:
        """Create an immutable derived upload with one user-confirmed firm on all rows."""

        corp_id, conversation_id = current_context()
        run_id = backend.active_run_id
        if not run_id:
            raise RuntimeError("The active run context is unavailable.")
        try:
            stored_checkpoint = store.get_advisor_input_checkpoint(
                conversation_id, corp_id=corp_id
            )
        except KeyError as exc:
            raise ValueError(
                "Validate an advisor input before applying an all-rows firm."
            ) from exc
        if stored_checkpoint["validated_run_id"] == run_id:
            raise ValueError(
                "Ask for and receive the all-rows firm confirmation in a later "
                "user turn before applying it."
            )
        checkpoint = stored_checkpoint["validation"]
        checkpoint_attachment_id = str(checkpoint["attachment_id"])
        if attachment_id is not None and attachment_id != checkpoint_attachment_id:
            raise ValueError(
                "The supplied attachment is not the current validated input."
            )
        attachment_id = checkpoint_attachment_id
        checkpoint_mapping = InputMapping.model_validate(checkpoint["mapping"])
        if (
            mapping is not None
            and mapping.model_dump(mode="json")
            != checkpoint_mapping.model_dump(mode="json")
        ):
            raise ValueError(
                "The supplied mapping is not the current validated mapping."
            )
        mapping = checkpoint_mapping
        source, original_name = resolve_upload(attachment_id)
        current_question = store.get_run(run_id, corp_id=corp_id).question
        if not _contains_explicit_firm(current_question, firm_name):
            raise ValueError(
                "The firm name must appear explicitly in the current user message "
                "before it can be applied to every advisor."
            )
        suffix = source.suffix.lower()
        derived_name = f"{Path(original_name).stem}_with_firm{suffix}"
        with tempfile.TemporaryDirectory(prefix="advisor-firm-") as temporary:
            staged = Path(temporary) / derived_name
            augmentation = augment_input_with_firm(
                source,
                staged,
                mapping,
                firm_name,
                max_rows=settings.advisor_max_input_rows,
            )
            transformation = {
                "type": "bulk_firm_augmentation",
                "source_attachment_id": attachment_id,
                "source_sha256": augmentation.source_sha256,
                "firm_name": augmentation.firm_name,
                "rows_updated": augmentation.rows_updated,
                "selected_sheet": augmentation.selected_sheet,
                "firm_column_index": augmentation.firm_column_index,
                "firm_column_header": augmentation.firm_column_header,
            }
            content_type = (
                "text/csv"
                if suffix == ".csv"
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            with staged.open("rb") as handle:
                attachment, protected = workspace.upload(
                    corp_id=corp_id,
                    conversation_id=conversation_id,
                    original_name=derived_name,
                    content_type=content_type,
                    source=handle,
                    max_bytes=settings.max_upload_mb * 1024 * 1024,
                )
        try:
            store.add_attachment(
                run_id,
                attachment,
                protected,
                corp_id=corp_id,
                derived_from_attachment_id=attachment_id,
                transformation=transformation,
            )
        except Exception:
            protected.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                protected.parent.rmdir()
            raise
        return FirmAugmentationResult(
            source_attachment_id=attachment_id,
            attachment_id=attachment.attachment_id,
            original_name=attachment.original_name,
            source_sha256=augmentation.source_sha256,
            derived_sha256=attachment.sha256,
            firm_name=augmentation.firm_name,
            rows_updated=augmentation.rows_updated,
            selected_sheet=augmentation.selected_sheet,
            mapping=augmentation.mapping,
        ).model_dump(mode="json")

    @tool
    def find_all_advisors() -> dict[str, Any]:
        """Snapshot all authoritative advisors and return only the opaque manifest."""

        corp_id, conversation_id = current_context()
        snapshot_id = "ars_" + uuid.uuid4().hex
        target = (
            workspace.reference_file(corp_id, snapshot_id)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".advisor_reference.csv.building")
        count = 0
        try:
            with temporary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=MASTER_COLUMNS)
                writer.writeheader()
                for record in itertools.islice(
                    advisor_source.iter_records(),
                    settings.advisor_max_reference_rows + 1,
                ):
                    count += 1
                    if count > settings.advisor_max_reference_rows:
                        raise ValueError(
                            "Advisor reference source exceeds the configured row limit."
                        )
                    writer.writerow(record.master_dict())
            if count == 0:
                raise ValueError("Advisor reference source is empty.")
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        manifest = ReferenceSnapshotManifest(
            reference_snapshot_id=snapshot_id,
            row_count=count,
            columns=list(MASTER_COLUMNS),
            source_kind=advisor_source.source_kind,
            schema_version=advisor_source.schema_version,
            retrieved_at=datetime.now(UTC),
            sha256=sha256_file(target),
            query_id=None,
        )
        store.create_advisor_reference_snapshot(
            snapshot_id=snapshot_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
            manifest=manifest.model_dump(mode="json"),
            snapshot_path=target,
        )
        return manifest.model_dump(mode="json")

    @tool
    def create_advisor_match(
        attachment_id: str,
        reference_snapshot_id: str,
        mapping: InputMapping,
        mapping_fingerprint: str,
        allow_missing_firm: bool = False,
    ) -> dict[str, Any]:
        """Create a persisted deterministic advisor match and verified workbook."""

        corp_id, conversation_id = current_context()
        source, original_name = resolve_upload(attachment_id)
        loaded = validate_and_load_input(
            source,
            mapping,
            max_rows=settings.advisor_max_input_rows,
        )
        if loaded.mapping_fingerprint != mapping_fingerprint:
            raise ValueError(
                "The upload or mapping changed after validation; validate it again."
            )
        _require_current_validation(
            store=store,
            corp_id=corp_id,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            mapping=mapping,
            mapping_fingerprint=mapping_fingerprint,
        )
        metadata = store.attachment_metadata(
            attachment_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
        transformation = metadata["transformation"]
        _validate_source_transformation(loaded.rows, mapping, transformation)
        if (
            loaded.summary.missing_firm_confirmation_required
            and not allow_missing_firm
        ):
            if loaded.summary.firm_column_missing:
                raise ValueError(
                    "The selected input has no mapped firm column. Ask whether "
                    "one firm applies to every advisor; otherwise require explicit "
                    "permission to continue with weaker evidence."
                )
            raise ValueError(
                f"{loaded.summary.missing_firm_row_count} rows have a usable name "
                "but no firm, valid CRD, or valid email. Ask whether one firm "
                "applies to every advisor; otherwise require explicit permission "
                "to continue with weaker evidence."
            )
        reference, snapshot = _resolve_reference_snapshot(
            store=store,
            workspace=workspace,
            corp_id=corp_id,
            conversation_id=conversation_id,
            snapshot_id=reference_snapshot_id,
        )
        advisors = _read_reference(snapshot)
        if len(advisors) != reference.row_count:
            raise ValueError("The advisor reference snapshot row count changed.")
        decisions, counts, match_warnings = run_matching(loaded.rows, advisors)
        warnings = _unique(
            [*_input_summary_warnings(loaded.summary), *match_warnings]
        )
        session_id = store.create_advisor_match_session(
            corp_id=corp_id,
            conversation_id=conversation_id,
            source_attachment_id=attachment_id,
            source_name=original_name,
            source_sha256=loaded.source_sha256,
            mapping=mapping.model_dump(mode="json"),
            input_summary=loaded.summary.model_dump(mode="json"),
            source_transformation=transformation,
            reference=reference.model_dump(mode="json"),
            decisions=[decision.model_dump(mode="json") for decision in decisions],
            counts=counts.model_dump(mode="json"),
            policy_version=POLICY_VERSION,
        )
        artifact = _write_session_workbook(
            workspace, store, backend, corp_id, session_id
        )
        return MatchRunResult(
            match_session_id=session_id,
            output_artifact_id=artifact.artifact_id,
            selected_sheet=loaded.selected_sheet,
            interpreted_mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            input_summary=loaded.summary,
            counts=counts,
            source_transformation=transformation,
            warnings=warnings,
            policy_version=POLICY_VERSION,
        ).model_dump(mode="json")

    @tool
    def get_current_advisor_match() -> dict[str, Any]:
        """Return this conversation's latest persisted advisor match summary."""

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
            "interpreted_mapping": session["mapping"],
            "input_summary": session["input_summary"],
            "source_transformation": session["source_transformation"],
            "counts": session["counts"],
            "status": session["status"],
            "revision": session["revision"],
            "output_artifact_id": session["output_artifact_id"],
            "updated_at": session["updated_at"],
        }

    @tool
    def list_advisor_match_results(
        match_session_id: str,
        status: str | None = None,
        source_row_number: int | None = None,
        name_query: str | None = None,
        cursor: int = 0,
        limit: int = 10,
    ) -> dict[str, Any]:
        """List bounded advisor match results with qualitative candidate evidence."""

        corp_id, _ = current_context()
        if cursor < 0 or limit < 1 or limit > 20:
            raise ValueError(
                "cursor must be nonnegative and limit must be between 1 and 20."
            )
        session = store.get_advisor_match_session(
            match_session_id, corp_id=corp_id
        )
        items = [
            MatchDecision.model_validate(value) for value in session["decisions"]
        ]
        normalized_status = _normalize_status_filter(status)
        if normalized_status:
            items = [item for item in items if item.status == normalized_status]
        if source_row_number is not None:
            items = [
                item
                for item in items
                if item.source_row_number == source_row_number
            ]
        if name_query:
            query = name_query.strip().casefold()
            items = [
                item
                for item in items
                if query
                in " ".join(
                    (
                        item.mapped_values.get("first_name", ""),
                        item.mapped_values.get("last_name", ""),
                        item.mapped_values.get("full_name", ""),
                    )
                ).casefold()
            ]
        page = items[cursor : cursor + limit]
        return {
            "match_session_id": match_session_id,
            "items": [_review_view(item) for item in page],
            "total": len(items),
            "next_cursor": cursor + limit if cursor + limit < len(items) else None,
        }

    @tool
    def propose_crd_match(
        match_session_id: str,
        review_item_id: str,
        crd_number: str,
    ) -> dict[str, Any]:
        """Resolve a user-supplied CRD and propose it for later-turn confirmation."""

        corp_id, _ = current_context()
        session = store.get_advisor_match_session(
            match_session_id, corp_id=corp_id
        )
        item = _find_item(session, review_item_id)
        reference, snapshot = _resolve_reference_snapshot(
            store=store,
            workspace=workspace,
            corp_id=corp_id,
            conversation_id=session["conversation_id"],
            snapshot_id=session["reference"]["reference_snapshot_id"],
        )
        record = next(
            (
                candidate
                for candidate in _read_reference(snapshot)
                if candidate.crd_number == crd_number
            ),
            None,
        )
        if record is None:
            raise ValueError(
                "The supplied CRD does not exist in this session's advisor reference."
            )
        candidate = MatchCandidate(**record.model_dump())
        proposal_id = store.create_advisor_override_proposal(
            corp_id=corp_id,
            session_id=match_session_id,
            review_item_id=review_item_id,
            crd_number=crd_number,
            advisor=candidate.model_dump(mode="json"),
            reference_sha256=reference.sha256,
            created_run_id=backend.active_run_id or "",
        )
        return {
            "proposal_id": proposal_id,
            "review_item": _review_view(item),
            "resolved_advisor": candidate.model_dump(mode="json"),
            "requires_explicit_confirmation": True,
        }

    @tool
    def apply_advisor_match_decisions(
        match_session_id: str,
        decisions: list[ReviewDecision],
        approve_session: bool = False,
    ) -> dict[str, Any]:
        """Apply explicit advisor match decisions and regenerate the verified workbook."""

        corp_id, _ = current_context()
        if len(decisions) > 20:
            raise ValueError("Apply at most 20 review decisions per call.")
        if len({decision.review_item_id for decision in decisions}) != len(
            decisions
        ):
            raise ValueError("Each review item may appear only once per call.")
        session = store.get_advisor_match_session(
            match_session_id, corp_id=corp_id
        )
        items = [
            MatchDecision.model_validate(value) for value in session["decisions"]
        ]
        by_id = {item.review_item_id: item for item in items}
        audits = []
        proposal_ids = []
        for requested in decisions:
            item = by_id.get(requested.review_item_id)
            if item is None:
                raise ValueError(
                    f"Unknown review item: {requested.review_item_id}."
                )
            prior = item.model_dump(mode="json")
            proposal_id = _apply_review(
                store, backend, corp_id, session, item, requested
            )
            if proposal_id:
                proposal_ids.append(proposal_id)
            audits.append(
                {
                    "review_item_id": item.review_item_id,
                    "action": requested.action,
                    "crd_number": requested.crd_number,
                    "note": requested.note,
                    "prior": prior,
                    "new": item.model_dump(mode="json"),
                }
            )
        counts = _counts(items)
        status = "Approved" if approve_session else session["status"]
        store.update_advisor_match_session(
            match_session_id,
            corp_id=corp_id,
            decisions=[item.model_dump(mode="json") for item in items],
            counts=counts.model_dump(mode="json"),
            status=status,
            audits=audits,
            proposal_ids=proposal_ids,
        )
        artifact = _write_session_workbook(
            workspace, store, backend, corp_id, match_session_id
        )
        return {
            "match_session_id": match_session_id,
            "counts": counts.model_dump(),
            "status": status,
            "output_artifact_id": artifact.artifact_id,
        }

    return [
        inspect_advisor_upload,
        validate_advisor_input,
        get_current_advisor_input,
        apply_firm_to_advisor_upload,
        find_all_advisors,
        create_advisor_match,
        get_current_advisor_match,
        list_advisor_match_results,
        propose_crd_match,
        apply_advisor_match_decisions,
    ]


def _validate_source_transformation(
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
    mapping: InputMapping,
    transformation: dict[str, Any],
) -> None:
    if not transformation:
        return
    if transformation.get("type") != "bulk_firm_augmentation":
        raise ValueError("The advisor attachment has an unsupported transformation.")
    binding = mapping.firm_name
    expected_header = transformation.get("firm_column_header")
    expected_index = transformation.get("firm_column_index")
    if (
        binding is None
        or len(binding.columns) != 1
        or binding.columns[0].index != expected_index
        or binding.columns[0].header != expected_header
    ):
        raise ValueError(
            "The mapping must use the exact firm column created by the derived upload."
        )
    expected_firm = str(transformation.get("firm_name") or "").strip()
    if not expected_firm or any(
        str(mapped.get("firm_name") or "").strip() != expected_firm
        for _, _, mapped in rows
    ):
        raise ValueError(
            "The derived upload no longer contains the confirmed firm on every row."
        )


def _require_current_validation(
    *,
    store: Store,
    corp_id: str,
    conversation_id: str,
    attachment_id: str,
    mapping: InputMapping,
    mapping_fingerprint: str,
) -> None:
    try:
        validation = store.get_advisor_input_checkpoint(
            conversation_id, corp_id=corp_id
        )["validation"]
    except KeyError as exc:
        raise ValueError("Validate the advisor input before matching.") from exc
    if (
        validation.get("attachment_id") != attachment_id
        or validation.get("mapping_fingerprint") != mapping_fingerprint
        or validation.get("mapping") != mapping.model_dump(mode="json")
    ):
        raise ValueError(
            "Validate this exact advisor attachment and mapping before matching."
        )


def _contains_explicit_firm(question: str, firm_name: str) -> bool:
    question_words = norm.words(question)
    firm_words = norm.words(firm_name)
    if not firm_words:
        return False
    width = len(firm_words)
    return any(
        question_words[index : index + width] == firm_words
        for index in range(len(question_words) - width + 1)
    )


def _normalize_status_filter(status: str | None) -> MatchStatus | None:
    if status is None or not status.strip():
        return None
    key = " ".join(
        status.replace("_", " ").replace("-", " ").split()
    ).casefold()
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
            "Unsupported match status filter. Use matched, ambiguous_match, "
            "or no_match."
        )
    return normalized


def _resolve_reference_snapshot(
    *,
    store: Store,
    workspace: Workspace,
    corp_id: str,
    conversation_id: str,
    snapshot_id: str,
) -> tuple[ReferenceSnapshotManifest, Path]:
    try:
        stored = store.get_advisor_reference_snapshot(
            snapshot_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
    except KeyError as exc:
        raise ValueError(
            "The advisor reference snapshot is unknown in this conversation."
        ) from exc
    manifest = ReferenceSnapshotManifest.model_validate(stored["manifest"])
    path = Path(stored["snapshot_path"])
    expected = workspace.reference_file(corp_id, snapshot_id)
    try:
        workspace.validate_file(corp_id, "advisor_references", path)
    except ValueError as exc:
        raise ValueError("The advisor reference snapshot path is invalid.") from exc
    if path.resolve() != expected.resolve():
        raise ValueError("The advisor reference snapshot path is invalid.")
    if sha256_file(path) != manifest.sha256:
        raise ValueError("The advisor reference snapshot failed integrity validation.")
    return manifest, path


def _read_reference(path: Path) -> list[AdvisorRecord]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MASTER_COLUMNS:
            raise ValueError("The advisor reference snapshot schema changed.")
        return [
            AdvisorRecord(
                **{
                    column.lower(): str(row[column] or "").strip()
                    for column in MASTER_COLUMNS
                }
            )
            for row in reader
        ]


def _find_item(session: dict[str, Any], item_id: str) -> MatchDecision:
    for value in session["decisions"]:
        item = MatchDecision.model_validate(value)
        if item.review_item_id == item_id:
            return item
    raise ValueError(f"Unknown review item: {item_id}.")


def _review_view(item: MatchDecision) -> dict[str, Any]:
    mapped = {key: value for key, value in item.mapped_values.items() if value}
    return {
        "review_item_id": item.review_item_id,
        "source_row_number": item.source_row_number,
        "input": mapped,
        "status": item.status,
        "confidence": item.confidence,
        "rule_id": item.rule_id,
        "reason": item.explanation,
        "warnings": item.warnings,
        "matched_advisor": item.matched_advisor.model_dump(mode="json")
        if item.matched_advisor
        else None,
        "candidates": [
            candidate.model_dump(mode="json") for candidate in item.candidates
        ],
        "duplicate_group": item.duplicate_group,
        "decision_source": item.decision_source,
        "automated_status": item.automated_status or item.status,
    }


def _apply_review(store, backend, corp_id, session, item, requested):
    if item.automated_status is None:
        item.automated_status = item.status
    if requested.action == "confirm_candidate":
        candidate = next(
            (
                candidate
                for candidate in item.candidates
                if candidate.crd_number == requested.crd_number
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "The selected CRD was not presented for this review item."
            )
        item.status, item.confidence, item.rule_id = (
            "Matched",
            "User Confirmed",
            "USER_CONFIRMED_OVERRIDE",
        )
        item.matched_advisor, item.decision_source = candidate, "User Override"
        item.explanation = "The user explicitly confirmed a presented advisor candidate."
    elif requested.action == "confirm_manual_crd":
        if not requested.proposal_id:
            raise ValueError("A confirmed manual CRD proposal is required.")
        proposal = store.get_advisor_override_proposal(
            requested.proposal_id, corp_id=corp_id
        )
        if (
            proposal["session_id"] != session["id"]
            or proposal["review_item_id"] != item.review_item_id
            or proposal["status"] != "Pending"
        ):
            raise ValueError("The manual CRD proposal is invalid or stale.")
        if proposal["created_run_id"] == backend.active_run_id:
            raise ValueError("Confirm a manual CRD proposal in a later user turn.")
        if proposal["reference_sha256"] != session["reference"]["sha256"]:
            raise ValueError(
                "The manual CRD proposal uses a different reference snapshot."
            )
        item.status, item.confidence, item.rule_id = (
            "Matched",
            "User Confirmed",
            "USER_CONFIRMED_OVERRIDE",
        )
        item.matched_advisor = MatchCandidate.model_validate(proposal["advisor"])
        item.decision_source = "User Override"
        item.explanation = "The user explicitly confirmed a separately resolved CRD override."
        return requested.proposal_id
    elif requested.action == "confirm_no_match":
        item.status, item.confidence, item.rule_id = (
            "No Match",
            "None",
            "USER_CONFIRMED_NO_MATCH",
        )
        item.matched_advisor, item.decision_source = None, "User Override"
        item.explanation = "The user explicitly confirmed that this row should remain unmatched."
    return None


def _counts(items: list[MatchDecision]) -> MatchCounts:
    return MatchCounts(
        matched=sum(item.status == "Matched" for item in items),
        ambiguous_match=sum(
            item.status == "Ambiguous Match" for item in items
        ),
        no_match=sum(item.status == "No Match" for item in items),
    )


def _write_session_workbook(
    workspace: Workspace,
    store: Store,
    backend: AdvisorWorkspaceBackend,
    corp_id: str,
    session_id: str,
) -> Artifact:
    run_id = backend.active_run_id
    if not run_id:
        raise RuntimeError("The active run context is unavailable.")
    session = store.get_advisor_match_session(session_id, corp_id=corp_id)
    decisions = [
        MatchDecision.model_validate(value) for value in session["decisions"]
    ]
    mapping = InputMapping.model_validate(session["mapping"])
    input_summary = InputSummary.model_validate(session["input_summary"])
    reference = ReferenceSnapshotManifest.model_validate(session["reference"])
    artifact_id = "art_" + uuid.uuid4().hex
    output = workspace.artifact_file(corp_id, run_id, artifact_id)
    output.parent.mkdir(parents=True, exist_ok=False)
    temporary = output.with_name(".advisor_matches.building.xlsx")
    try:
        write_match_workbook(
            temporary,
            session_id=session_id,
            decisions=decisions,
            counts=MatchCounts.model_validate(session["counts"]),
            mapping=mapping,
            input_summary=input_summary,
            source_name=session["source_name"],
            source_sha256=session["source_sha256"],
            reference=reference,
            policy_version=session["policy_version"],
            session_status=session["status"],
            session_revision=session["revision"],
            source_transformation=session["source_transformation"],
        )
        os.replace(temporary, output)
        artifact = Artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            match_session_id=session_id,
            revision=session["revision"],
            relative_path="advisor_matches.xlsx",
            change_type="created",
            size_bytes=output.stat().st_size,
            sha256=sha256_file(output),
            created_at=utc_now(),
        )
        store.add_artifact(artifact, output, corp_id=corp_id)
        store.set_advisor_match_artifact(
            session_id, artifact_id, corp_id=corp_id
        )
        store.add_event(
            run_id,
            "artifact_changed",
            "completed",
            f"Published workbook revision {session['revision']}",
            data=artifact.model_dump(mode="json"),
            corp_id=corp_id,
        )
        return artifact
    except Exception:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        try:
            output.parent.rmdir()
        except OSError:
            pass
        raise


def _input_summary_warnings(summary: InputSummary) -> list[str]:
    warnings = []
    if summary.preamble_row_count:
        warnings.append(
            f"Skipped {summary.preamble_row_count} preamble rows before the header."
        )
    if summary.blank_row_count:
        warnings.append(f"Skipped {summary.blank_row_count} completely blank rows.")
    if summary.firm_column_missing:
        warnings.append("The selected input has no mapped firm column.")
    if summary.missing_firm_row_count:
        warnings.append(
            f"{summary.missing_firm_row_count} rows have a usable name but no firm, "
            "valid CRD, or valid email."
        )
    return warnings


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
