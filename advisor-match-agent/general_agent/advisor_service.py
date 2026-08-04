"""Explicit application service for deterministic advisor matching and review."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.input_loader import validate_and_load_input
from general_agent.advisor_matching.index import ReferenceDataQualityError
from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.policy import POLICY_VERSION
from general_agent.advisor_matching.profiler import inspect_advisor_upload
from general_agent.advisor_matching.schemas import (
    FirmClarificationResult,
    FirmResolution,
    InputMapping,
    InputSummary,
    MappingValidationResult,
    MatchCandidate,
    MatchCounts,
    MatchDecision,
    MatchRunResult,
    ReferenceSnapshotManifest,
    ReferenceBlockerResult,
    ReviewDecision,
)
from general_agent.advisor_matching.source import AdvisorReferenceSource, sha256_file
from general_agent.advisor_matching.workbook import write_match_workbook
from general_agent.advisor_repository import AdvisorRepository
from general_agent.advisor_support import (
    _apply_review,
    _counts,
    _contains_explicit_firm,
    _find_item,
    _input_summary_warnings,
    _iter_reference,
    _load_or_create_reference,
    _normalize_status_filter,
    _resolve_firm_rows,
    _resolve_reference_snapshot,
    _review_view,
    _unique,
    _validate_source_transformation,
    _validated_firm_name,
)
from general_agent.config import Settings
from general_agent.runtime_store import RuntimeStore
from general_agent.schemas import Artifact, utc_now
from general_agent.workspace import Workspace

logger = logging.getLogger("general_agent.advisor_service")


@dataclass(frozen=True, slots=True)
class ServiceContext:
    corp_id: str
    conversation_id: str
    run_id: str
    user_message: str


@dataclass(frozen=True, slots=True)
class AdvisorService:
    settings: Settings
    workspace: Workspace
    repository: AdvisorRepository
    runtime: RuntimeStore
    advisor_source: AdvisorReferenceSource

    def resolve_upload(self, context: ServiceContext, attachment_id: str) -> tuple[Path, str]:
        try:
            source, original_name, expected_sha256 = self.repository.attachment_path(
                attachment_id,
                corp_id=context.corp_id,
                conversation_id=context.conversation_id,
            )
        except KeyError as exc:
            raise ValueError("Advisor attachment is unknown in the current chat.") from exc
        self.workspace.validate_file(context.corp_id, "attachments", source)
        if source.suffix.lower() not in {".csv", ".xlsx"}:
            raise ValueError("Advisor matching accepts only CSV or XLSX uploads.")
        if expected_sha256 and sha256_file(source) != expected_sha256:
            raise ValueError("The immutable advisor attachment failed integrity validation.")
        return source, original_name

    def inspect(self, context: ServiceContext, attachment_id: str) -> dict[str, Any]:
        source, _ = self.resolve_upload(context, attachment_id)
        return {
            "attachment_id": attachment_id,
            **inspect_advisor_upload(source, self.settings),
        }

    def validate(
        self, context: ServiceContext, attachment_id: str, mapping: InputMapping
    ) -> MappingValidationResult:
        source, _ = self.resolve_upload(context, attachment_id)
        loaded = validate_and_load_input(
            source, mapping, max_rows=self.settings.advisor_max_input_rows
        )
        metadata = self.repository.attachment_metadata(
            attachment_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        transformation = metadata["transformation"]
        _validate_source_transformation(loaded.rows, mapping, transformation)
        return MappingValidationResult(
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

    def create_match(
        self,
        context: ServiceContext,
        validation: MappingValidationResult,
        *,
        all_rows_firm: str | None = None,
        firm_resolution: FirmResolution = "auto",
    ) -> MatchRunResult | FirmClarificationResult | ReferenceBlockerResult:
        source, original_name = self.resolve_upload(context, validation.attachment_id)
        loaded = validate_and_load_input(
            source,
            validation.mapping,
            max_rows=self.settings.advisor_max_input_rows,
        )
        if (
            loaded.mapping_fingerprint != validation.mapping_fingerprint
            or loaded.source_sha256 != validation.source_sha256
        ):
            raise ValueError("The upload or mapping changed after validation; validate it again.")
        transformation = self.repository.attachment_metadata(
            validation.attachment_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )["transformation"]
        _validate_source_transformation(loaded.rows, validation.mapping, transformation)
        firm = _validated_firm_name(all_rows_firm) if all_rows_firm else None
        if firm and not _contains_explicit_firm(context.user_message, firm):
            raise ValueError(
                "The all-rows firm must appear explicitly in the current user message."
            )
        resolved = _resolve_firm_rows(
            rows=loaded.rows,
            mapping=validation.mapping,
            input_summary=loaded.summary,
            missing_firm_sample=loaded.missing_firm_sample,
            all_rows_firm=firm,
            firm_resolution=firm_resolution,
            source_attachment_id=validation.attachment_id,
            source_sha256=loaded.source_sha256,
            selected_sheet=loaded.selected_sheet,
            source_transformation=transformation,
        )
        if isinstance(resolved, FirmClarificationResult):
            return resolved
        match_rows, session_transformation = resolved
        try:
            reference, advisor_index = _load_or_create_reference(
                store=self.repository,
                workspace=self.workspace,
                advisor_source=self.advisor_source,
                settings=self.settings,
                corp_id=context.corp_id,
                conversation_id=context.conversation_id,
                attachment_id=validation.attachment_id,
            )
        except ReferenceDataQualityError as exc:
            visible = list(exc.duplicate_crds.items())[:10]
            return ReferenceBlockerResult(
                blocker_code="DUPLICATE_REFERENCE_CRD",
                message=(
                    "I can’t start matching because the master advisor database contains "
                    "duplicate CRD numbers. Your upload was not changed. Please have the "
                    "master data corrected, then try this match again."
                ),
                duplicate_crd_count=len(exc.duplicate_crds),
                duplicate_crds=[
                    {"crd_number": crd, "occurrences": count}
                    for crd, count in visible
                ],
            )
        except ValueError:
            return ReferenceBlockerResult(
                blocker_code="REFERENCE_DATA_INVALID",
                message=(
                    "I can’t start matching because the master advisor database did not "
                    "pass validation. Your upload was not changed. Please have the master "
                    "data corrected, then try this match again."
                ),
            )
        decisions, counts, match_warnings = run_matching(match_rows, advisor_index)
        session_id = self.repository.create_advisor_match_session(
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
            source_attachment_id=validation.attachment_id,
            source_name=original_name,
            source_sha256=loaded.source_sha256,
            mapping=validation.mapping.model_dump(mode="json"),
            input_summary=loaded.summary.model_dump(mode="json"),
            source_transformation=session_transformation,
            reference=reference.model_dump(mode="json"),
            decisions=[item.model_dump(mode="json") for item in decisions],
            counts=counts.model_dump(mode="json"),
            policy_version=POLICY_VERSION,
        )
        artifact = self._write_workbook(context, session_id)
        return MatchRunResult(
            match_session_id=session_id,
            output_artifact_id=artifact.artifact_id,
            selected_sheet=loaded.selected_sheet,
            interpreted_mapping=validation.mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            input_summary=loaded.summary,
            counts=counts,
            source_transformation=session_transformation,
            reference=reference,
            warnings=_unique([*_input_summary_warnings(loaded.summary), *match_warnings]),
            policy_version=POLICY_VERSION,
        )

    def current_match(self, context: ServiceContext) -> dict[str, Any]:
        session = self.repository.get_latest_advisor_match_session(
            context.conversation_id, corp_id=context.corp_id
        )
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

    def list_results(
        self,
        context: ServiceContext,
        match_session_id: str,
        *,
        status: str | None = None,
        source_row_number: int | None = None,
        name_query: str | None = None,
        cursor: int = 0,
        limit: int = 10,
    ) -> dict[str, Any]:
        if cursor < 0 or limit < 1 or limit > 20:
            raise ValueError("cursor must be nonnegative and limit must be between 1 and 20.")
        session = self.repository.get_advisor_match_session(
            match_session_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        items = [MatchDecision.model_validate(value) for value in session["decisions"]]
        normalized_status = _normalize_status_filter(status)
        if normalized_status:
            items = [item for item in items if item.status == normalized_status]
        if source_row_number is not None:
            items = [item for item in items if item.source_row_number == source_row_number]
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

    def propose_crd(
        self,
        context: ServiceContext,
        match_session_id: str,
        review_item_id: str,
        crd_number: str,
    ) -> dict[str, Any]:
        session = self.repository.get_advisor_match_session(
            match_session_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        item = _find_item(session, review_item_id)
        reference, snapshot = _resolve_reference_snapshot(
            store=self.repository,
            workspace=self.workspace,
            corp_id=context.corp_id,
            conversation_id=session["conversation_id"],
            snapshot_id=session["reference"]["reference_snapshot_id"],
        )
        normalized_crd = norm.crd(crd_number)
        record = next(
            (item for item in _iter_reference(snapshot) if item.crd_number == normalized_crd),
            None,
        )
        if record is None:
            raise ValueError("The supplied CRD does not exist in this session's reference.")
        candidate = MatchCandidate(**record.model_dump())
        proposal_id = self.repository.create_advisor_override_proposal(
            corp_id=context.corp_id,
            session_id=match_session_id,
            review_item_id=review_item_id,
            crd_number=normalized_crd,
            advisor=candidate.model_dump(mode="json"),
            reference_sha256=reference.sha256,
            created_run_id=context.run_id,
        )
        return {
            "proposal_id": proposal_id,
            "review_item": _review_view(item),
            "resolved_advisor": candidate.model_dump(mode="json"),
            "requires_explicit_confirmation": True,
        }

    def apply_decisions(
        self,
        context: ServiceContext,
        match_session_id: str,
        decisions: list[ReviewDecision],
        *,
        approve_session: bool = False,
    ) -> dict[str, Any]:
        if len(decisions) > 20:
            raise ValueError("Apply at most 20 review decisions per request.")
        if len({item.review_item_id for item in decisions}) != len(decisions):
            raise ValueError("Each review item may appear only once per request.")
        session = self.repository.get_advisor_match_session(
            match_session_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        items = [MatchDecision.model_validate(value) for value in session["decisions"]]
        by_id = {item.review_item_id: item for item in items}
        audits: list[dict[str, Any]] = []
        proposal_ids: list[str] = []
        for requested in decisions:
            item = by_id.get(requested.review_item_id)
            if item is None:
                raise ValueError(f"Unknown review item: {requested.review_item_id}.")
            prior = item.model_dump(mode="json")
            proposal_id = _apply_review(
                self.repository,
                context.run_id,
                context.corp_id,
                session,
                item,
                requested,
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
        self.repository.update_advisor_match_session(
            match_session_id,
            corp_id=context.corp_id,
            decisions=[item.model_dump(mode="json") for item in items],
            counts=counts.model_dump(mode="json"),
            status=status,
            audits=audits,
            proposal_ids=proposal_ids,
        )
        artifact = self._write_workbook(context, match_session_id)
        return {
            "match_session_id": match_session_id,
            "counts": counts.model_dump(),
            "status": status,
            "output_artifact_id": artifact.artifact_id,
        }

    def cancel_proposal(
        self, context: ServiceContext, proposal_id: str, match_session_id: str
    ) -> None:
        proposal = self.repository.get_advisor_override_proposal(
            proposal_id, corp_id=context.corp_id
        )
        if proposal["session_id"] != match_session_id:
            raise ValueError("The pending manual match does not belong to these results.")
        self.repository.get_advisor_match_session(
            match_session_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        if not self.repository.cancel_advisor_override_proposal(
            proposal_id, corp_id=context.corp_id
        ):
            raise ValueError("The pending manual match is no longer available.")

    def _write_workbook(self, context: ServiceContext, session_id: str) -> Artifact:
        session = self.repository.get_advisor_match_session(
            session_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        artifact_id = "art_" + uuid.uuid4().hex
        output = self.workspace.artifact_file(context.corp_id, context.run_id, artifact_id)
        output.parent.mkdir(parents=True, exist_ok=False)
        temporary = output.with_name(".advisor_matches.building.xlsx")
        try:
            write_match_workbook(
                temporary,
                session_id=session_id,
                decisions=[
                    MatchDecision.model_validate(value) for value in session["decisions"]
                ],
                counts=MatchCounts.model_validate(session["counts"]),
                mapping=InputMapping.model_validate(session["mapping"]),
                input_summary=InputSummary.model_validate(session["input_summary"]),
                source_name=session["source_name"],
                source_sha256=session["source_sha256"],
                reference=ReferenceSnapshotManifest.model_validate(session["reference"]),
                policy_version=session["policy_version"],
                session_status=session["status"],
                session_revision=session["revision"],
                source_transformation=session["source_transformation"],
            )
            temporary.replace(output)
            artifact = Artifact(
                artifact_id=artifact_id,
                run_id=context.run_id,
                match_session_id=session_id,
                revision=session["revision"],
                relative_path="advisor_matches.xlsx",
                change_type="created",
                size_bytes=output.stat().st_size,
                sha256=sha256_file(output),
                created_at=utc_now(),
            )
            self.repository.add_artifact(
                artifact,
                output,
                corp_id=context.corp_id,
                conversation_id=context.conversation_id,
            )
            self.repository.set_advisor_match_artifact(
                session_id, artifact_id, corp_id=context.corp_id
            )
            self.runtime.add_artifact(artifact, corp_id=context.corp_id)
            return artifact
        except Exception:
            temporary.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            try:
                output.parent.rmdir()
            except OSError:
                pass
            raise
