"""Explicit application service for deterministic advisor matching and export."""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from general_agent.advisor_matching.input_loader import validate_and_load_input
from general_agent.advisor_matching.index import ReferenceDataQualityError
from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.policy import POLICY_VERSION
from general_agent.advisor_matching.profiler import inspect_advisor_upload
from general_agent.advisor_matching.profile_report import (
    CrdCollection,
    collect_input_crds,
    collect_matched_crds,
    generate_advisor_profile_report,
    verify_advisor_profile_report,
)
from general_agent.advisor_matching.schemas import (
    CrdInputMapping,
    CrdInputValidationResult,
    FirmClarificationResult,
    FirmResolution,
    InputMapping,
    InputSummary,
    MappingValidationResult,
    MatchCounts,
    MatchDecision,
    MatchRunResult,
    ProfileReportResult,
    ReferenceSnapshotManifest,
    ReferenceBlockerResult,
)
from general_agent.advisor_matching.source import AdvisorReferenceSource, sha256_file
from general_agent.advisor_matching.workbook import write_match_workbook
from general_agent.advisor_repository import AdvisorRepository
from general_agent.advisor_support import (
    _contains_explicit_firm,
    _input_summary_warnings,
    _load_or_create_reference,
    _resolve_firm_rows,
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

    def validate_profile_input(
        self,
        context: ServiceContext,
        attachment_id: str,
        mapping: CrdInputMapping,
    ) -> CrdInputValidationResult:
        source, _ = self.resolve_upload(context, attachment_id)
        loaded = validate_and_load_input(
            source,
            mapping.as_input_mapping(),
            max_rows=self.settings.advisor_max_input_rows,
        )
        metadata = self.repository.attachment_metadata(
            attachment_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )
        transformation = metadata["transformation"]
        _validate_source_transformation(
            loaded.rows, mapping.as_input_mapping(), transformation
        )
        crds = collect_input_crds(loaded.rows)
        if not crds.crd_numbers:
            raise ValueError(
                "the selected CRD column contains no usable CRD values"
            )
        return CrdInputValidationResult(
            attachment_id=attachment_id,
            source_sha256=loaded.source_sha256,
            selected_sheet=loaded.selected_sheet,
            mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            columns=loaded.columns,
            data_row_count=loaded.summary.data_row_count,
            usable_crd_count=(crds.input_count - crds.blank_count),
            unique_crd_count=crds.unique_count,
            blank_crd_count=crds.blank_count,
            duplicate_crd_count=crds.duplicate_count,
            source_transformation=transformation,
        )

    def create_profile_report_from_upload(
        self,
        context: ServiceContext,
        validation: CrdInputValidationResult,
    ) -> ProfileReportResult:
        source, _ = self.resolve_upload(context, validation.attachment_id)
        generic_mapping = validation.mapping.as_input_mapping()
        loaded = validate_and_load_input(
            source,
            generic_mapping,
            max_rows=self.settings.advisor_max_input_rows,
        )
        if (
            loaded.mapping_fingerprint != validation.mapping_fingerprint
            or loaded.source_sha256 != validation.source_sha256
        ):
            raise ValueError(
                "The upload or CRD mapping changed after validation; validate it again."
            )
        transformation = self.repository.attachment_metadata(
            validation.attachment_id,
            corp_id=context.corp_id,
            conversation_id=context.conversation_id,
        )["transformation"]
        _validate_source_transformation(loaded.rows, generic_mapping, transformation)
        crds = collect_input_crds(loaded.rows)
        if not crds.crd_numbers:
            raise ValueError("The selected CRD column contains no usable CRD values.")
        return self._write_profile_report(
            context,
            crds,
            source_kind="attachment",
            source_attachment_id=validation.attachment_id,
            source_sha256=loaded.source_sha256,
            mapping=validation.mapping.model_dump(mode="json"),
            mapping_fingerprint=loaded.mapping_fingerprint,
        )

    def create_profile_report_from_match(
        self,
        context: ServiceContext,
        match_session_id: str,
    ) -> ProfileReportResult:
        try:
            session = self.repository.get_advisor_match_session(
                match_session_id,
                corp_id=context.corp_id,
                conversation_id=context.conversation_id,
            )
        except KeyError as exc:
            raise ValueError(
                "The completed advisor match is unavailable in the current chat."
            ) from exc
        decisions = [
            MatchDecision.model_validate(value) for value in session["decisions"]
        ]
        crds = collect_matched_crds(decisions)
        if not crds.crd_numbers:
            raise ValueError(
                "The completed match contains no automatically matched CRD numbers."
            )
        return self._write_profile_report(
            context,
            crds,
            source_kind="match_session",
            source_match_session_id=match_session_id,
            source_sha256=session["source_sha256"],
        )

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

    def _write_profile_report(
        self,
        context: ServiceContext,
        crds: CrdCollection,
        *,
        source_kind: str,
        source_match_session_id: str | None = None,
        source_attachment_id: str | None = None,
        source_sha256: str | None = None,
        mapping: dict[str, Any] | None = None,
        mapping_fingerprint: str | None = None,
    ) -> ProfileReportResult:
        report_id = "apr_" + uuid.uuid4().hex
        artifact_id = "art_" + uuid.uuid4().hex
        output = self.workspace.artifact_file(
            context.corp_id,
            context.run_id,
            artifact_id,
            "advisor_profile_report.html",
        )
        output.parent.mkdir(parents=True, exist_ok=False)
        temporary = output.with_name(".advisor_profile_report.building.html")
        report_persisted = False
        try:
            html = generate_advisor_profile_report(crds.crd_numbers)
            temporary.write_text(html, encoding="utf-8", newline="\n")
            verify_advisor_profile_report(temporary)
            temporary.replace(output)
            artifact = Artifact(
                artifact_id=artifact_id,
                run_id=context.run_id,
                profile_report_id=report_id,
                artifact_kind="advisor_profile_report",
                relative_path="advisor_profile_report.html",
                change_type="created",
                size_bytes=output.stat().st_size,
                sha256=sha256_file(output),
                created_at=utc_now(),
            )
            result = ProfileReportResult(
                profile_report_id=report_id,
                output_artifact_id=artifact_id,
                source_kind=source_kind,
                source_match_session_id=source_match_session_id,
                source_attachment_id=source_attachment_id,
                input_crd_count=crds.input_count,
                unique_crd_count=crds.unique_count,
                blank_crd_count=crds.blank_count,
                duplicate_crd_count=crds.duplicate_count,
            )
            self.repository.add_profile_report(
                report_id=report_id,
                artifact=artifact,
                snapshot_path=output,
                corp_id=context.corp_id,
                conversation_id=context.conversation_id,
                source_kind=source_kind,
                source_match_session_id=source_match_session_id,
                source_attachment_id=source_attachment_id,
                source_sha256=source_sha256,
                mapping=mapping,
                mapping_fingerprint=mapping_fingerprint,
                crd_numbers=crds.crd_numbers,
                input_crd_count=crds.input_count,
                blank_crd_count=crds.blank_count,
                duplicate_crd_count=crds.duplicate_count,
            )
            report_persisted = True
            self.runtime.add_artifact(artifact, corp_id=context.corp_id)
            return result
        except Exception:
            if report_persisted:
                with contextlib.suppress(Exception):
                    self.repository.delete_profile_report(
                        report_id, corp_id=context.corp_id
                    )
            temporary.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            try:
                output.parent.rmdir()
            except OSError:
                pass
            raise
