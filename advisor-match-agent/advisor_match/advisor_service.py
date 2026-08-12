"""Stateless application services for matching and profile generation."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from advisor_match.advisor_matching.index import (
    AdvisorIndex,
    ReferenceDataQualityError,
)
from advisor_match.advisor_matching.input_loader import validate_and_load_input
from advisor_match.advisor_matching.matcher import run_matching
from advisor_match.advisor_matching.policy import POLICY_VERSION
from advisor_match.advisor_matching.profile_report import (
    collect_input_crds,
    generate_advisor_profile_report,
    verify_advisor_profile_report,
)
from advisor_match.advisor_matching.schemas import (
    AdvisorRecord,
    CrdInputMapping,
    CrdInputValidationResult,
    FirmResolution,
    InputMapping,
    MASTER_COLUMNS,
    MappingValidationResult,
    MatchResult,
    ProfileGenerationResult,
    ReferenceManifest,
)
from advisor_match.advisor_matching.source import AdvisorReferenceSource
from advisor_match.advisor_matching.workbook import build_match_workbook
from advisor_match.config import Settings
from advisor_match.files import InMemoryFile
from advisor_match.firm import input_summary_warnings, resolve_firms

ReferenceSourceFactory = Callable[[], AdvisorReferenceSource]


class SourceHashMismatch(ValueError):
    pass


class ReferenceSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MatchExecution:
    workbook: bytes
    result: MatchResult


@dataclass(frozen=True, slots=True)
class AdvisorService:
    settings: Settings
    reference_source_factory: ReferenceSourceFactory

    def validate_match_input(
        self, source: InMemoryFile, mapping: InputMapping
    ) -> MappingValidationResult:
        loaded = validate_and_load_input(
            source, mapping, max_rows=self.settings.advisor_max_input_rows
        )
        return MappingValidationResult(
            source_sha256=loaded.source_sha256,
            selected_sheet=loaded.selected_sheet,
            mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            columns=loaded.columns,
            input_summary=loaded.summary,
            missing_firm_sample=loaded.missing_firm_sample,
            warnings=input_summary_warnings(loaded.summary),
        )

    def match(
        self,
        source: InMemoryFile,
        *,
        analyzed_source_sha256: str,
        mapping: InputMapping,
        firm_resolution: FirmResolution = "auto",
        all_rows_firm: str | None = None,
    ) -> MatchExecution:
        _verify_source_hash(source, analyzed_source_sha256)
        loaded = validate_and_load_input(
            source, mapping, max_rows=self.settings.advisor_max_input_rows
        )
        resolved = resolve_firms(
            rows=loaded.rows,
            mapping=mapping,
            input_summary=loaded.summary,
            missing_firm_sample=loaded.missing_firm_sample,
            all_rows_firm=all_rows_firm,
            firm_resolution=firm_resolution,
        )
        reference, advisor_index = self._load_reference()
        decisions, counts, match_warnings = run_matching(
            resolved.rows, advisor_index
        )
        warnings = list(
            dict.fromkeys(input_summary_warnings(loaded.summary) + match_warnings)
        )
        generated_at = datetime.now(UTC)
        result = MatchResult(
            source_sha256=loaded.source_sha256,
            mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            input_summary=loaded.summary,
            counts=counts,
            firm_resolution=resolved.resolution,
            all_rows_firm=resolved.all_rows_firm,
            firm_override_rows=resolved.override_rows,
            reference=reference,
            warnings=warnings,
            policy_version=POLICY_VERSION,
            generated_at=generated_at,
        )
        workbook = build_match_workbook(
            decisions=decisions,
            counts=counts,
            mapping=mapping,
            input_summary=loaded.summary,
            source_name=source.filename,
            source_sha256=loaded.source_sha256,
            reference=reference,
            policy_version=POLICY_VERSION,
            firm_resolution=resolved.resolution,
            all_rows_firm=resolved.all_rows_firm,
            firm_override_rows=resolved.override_rows,
        )
        return MatchExecution(workbook=workbook, result=result)

    def validate_profile_input(
        self, source: InMemoryFile, mapping: CrdInputMapping
    ) -> CrdInputValidationResult:
        loaded = validate_and_load_input(
            source,
            mapping.as_input_mapping(),
            max_rows=self.settings.advisor_max_input_rows,
        )
        crds = collect_input_crds(loaded.rows)
        return CrdInputValidationResult(
            source_sha256=loaded.source_sha256,
            selected_sheet=loaded.selected_sheet,
            mapping=mapping,
            mapping_fingerprint=loaded.mapping_fingerprint,
            columns=loaded.columns,
            data_row_count=len(loaded.rows),
            usable_crd_count=crds.input_count - crds.blank_count,
            unique_crd_count=crds.unique_count,
            blank_crd_count=crds.blank_count,
            duplicate_crd_count=crds.duplicate_count,
        )

    def generate_profile(
        self,
        source: InMemoryFile,
        *,
        analyzed_source_sha256: str,
        mapping: CrdInputMapping,
    ) -> ProfileGenerationResult:
        _verify_source_hash(source, analyzed_source_sha256)
        loaded = validate_and_load_input(
            source,
            mapping.as_input_mapping(),
            max_rows=self.settings.advisor_max_input_rows,
        )
        crds = collect_input_crds(loaded.rows)
        html = generate_advisor_profile_report(crds.crd_numbers)
        verify_advisor_profile_report(html)
        return ProfileGenerationResult(
            html=html,
            source_sha256=loaded.source_sha256,
            mapping=mapping,
            input_crd_count=crds.input_count,
            unique_crd_count=crds.unique_count,
            blank_crd_count=crds.blank_count,
            duplicate_crd_count=crds.duplicate_count,
        )

    def _load_reference(self) -> tuple[ReferenceManifest, AdvisorIndex]:
        try:
            source = self.reference_source_factory()
        except Exception as exc:
            raise ReferenceSourceError(
                f"Advisor reference source is unavailable: {exc}"
            ) from exc
        digest = hashlib.sha256()
        row_count = 0

        def records() -> Iterator[AdvisorRecord]:
            nonlocal row_count
            for position, record in enumerate(
                itertools.islice(
                    source.iter_records(),
                    self.settings.advisor_max_reference_rows + 1,
                ),
                start=1,
            ):
                if position > self.settings.advisor_max_reference_rows:
                    raise ValueError(
                        "Advisor reference source exceeds the configured row limit."
                    )
                canonical = AdvisorRecord(
                    **{
                        column.lower(): str(record.master_dict()[column] or "").strip()
                        for column in MASTER_COLUMNS
                    }
                )
                serialized = json.dumps(
                    [canonical.master_dict()[column] for column in MASTER_COLUMNS],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                digest.update(serialized.encode("utf-8"))
                digest.update(b"\n")
                row_count += 1
                yield canonical

        try:
            advisor_index = AdvisorIndex.from_records(records())
        except ReferenceDataQualityError:
            raise
        except Exception as exc:
            raise ReferenceSourceError(str(exc)) from exc
        try:
            manifest = ReferenceManifest(
                row_count=row_count,
                source_kind=source.source_kind,
                schema_version=source.schema_version,
                retrieved_at=datetime.now(UTC),
                sha256=digest.hexdigest(),
                query_id=getattr(source, "query_id", None),
            )
        except Exception as exc:
            raise ReferenceSourceError(
                f"Advisor reference provenance is invalid: {exc}"
            ) from exc
        return manifest, advisor_index


def _verify_source_hash(source: InMemoryFile, expected: str) -> None:
    if source.sha256 != expected:
        raise SourceHashMismatch(
            "The uploaded file does not match the file that was analyzed."
        )
