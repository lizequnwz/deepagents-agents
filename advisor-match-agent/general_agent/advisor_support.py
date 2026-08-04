"""Deterministic support functions for AdvisorService.

These functions have no model or tool-selection behavior.
"""

from __future__ import annotations

import contextlib
import csv
import itertools
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.index import AdvisorIndex
from general_agent.advisor_matching.schemas import (
    AdvisorRecord,
    FirmClarificationResult,
    FirmResolution,
    InputMapping,
    InputSummary,
    MASTER_COLUMNS,
    ReferenceSnapshotManifest,
)
from general_agent.advisor_matching.source import AdvisorReferenceSource, sha256_file
from general_agent.config import Settings
from general_agent.advisor_repository import AdvisorRepository
from general_agent.workspace import Workspace

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


def _resolve_firm_rows(
    *,
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
    mapping: InputMapping,
    input_summary: InputSummary,
    missing_firm_sample: list[dict[str, Any]],
    all_rows_firm: str | None,
    firm_resolution: FirmResolution,
    source_attachment_id: str,
    source_sha256: str,
    selected_sheet: str | None,
    source_transformation: dict[str, Any],
) -> (
    tuple[
        list[tuple[int, dict[str, object], dict[str, str]]],
        dict[str, Any],
    ]
    | FirmClarificationResult
):
    """Resolve firm intent before any authoritative-reference retrieval."""

    if firm_resolution in {"use_source", "continue_without_firm"}:
        if all_rows_firm is not None:
            raise ValueError(
                f"firm_resolution={firm_resolution!r} cannot include all_rows_firm."
            )
    elif firm_resolution == "override_all" and all_rows_firm is None:
        raise ValueError("override_all requires an explicit all_rows_firm.")

    if firm_resolution == "use_source":
        if mapping.firm_name is None:
            raise ValueError("use_source requires a mapped firm column.")
        return rows, source_transformation
    if firm_resolution == "continue_without_firm":
        return rows, source_transformation
    if firm_resolution == "override_all":
        return _override_firm_rows(
            rows=rows,
            firm_name=all_rows_firm or "",
            source_attachment_id=source_attachment_id,
            source_sha256=source_sha256,
            selected_sheet=selected_sheet,
            source_transformation=source_transformation,
        )

    if all_rows_firm is None:
        if not input_summary.missing_firm_confirmation_required:
            return rows, source_transformation
        profile = _firm_profile(rows)
        return FirmClarificationResult(
            reason="missing_firm",
            data_row_count=len(rows),
            populated_firm_row_count=profile["populated_row_count"],
            blank_firm_row_count=profile["blank_row_count"],
            distinct_source_firm_count=profile["distinct_count"],
            source_firm_sample=profile["display_sample"],
            affected_row_sample=missing_firm_sample,
            allowed_resolutions=["override_all", "continue_without_firm"],
        )

    if mapping.firm_name is None:
        return _override_firm_rows(
            rows=rows,
            firm_name=all_rows_firm,
            source_attachment_id=source_attachment_id,
            source_sha256=source_sha256,
            selected_sheet=selected_sheet,
            source_transformation=source_transformation,
        )

    profile = _firm_profile(rows)
    target = norm.firm(all_rows_firm)
    normalized_values = profile["normalized_values"]
    if profile["blank_row_count"] == 0 and normalized_values == {target}:
        return rows, source_transformation

    affected_rows = []
    for row_number, _, mapped in rows:
        source_firm = str(mapped.get("firm_name") or "").strip()
        if not source_firm or norm.firm(source_firm) != target:
            affected_rows.append(
                {
                    "source_row_number": row_number,
                    "name": _mapped_display_name(mapped),
                    "source_firm": source_firm,
                }
            )
        if len(affected_rows) == 5:
            break
    return FirmClarificationResult(
        reason=_firm_clarification_reason(
            blank_count=profile["blank_row_count"],
            normalized_values=normalized_values,
            target=target,
        ),
        stated_firm=all_rows_firm,
        data_row_count=len(rows),
        populated_firm_row_count=profile["populated_row_count"],
        blank_firm_row_count=profile["blank_row_count"],
        distinct_source_firm_count=profile["distinct_count"],
        source_firm_sample=profile["display_sample"],
        affected_row_sample=affected_rows,
        allowed_resolutions=["use_source", "override_all"],
    )


def _override_firm_rows(
    *,
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
    firm_name: str,
    source_attachment_id: str,
    source_sha256: str,
    selected_sheet: str | None,
    source_transformation: dict[str, Any],
) -> tuple[
    list[tuple[int, dict[str, object], dict[str, str]]],
    dict[str, Any],
]:
    overridden = [
        (row_number, source_values, {**mapped, "firm_name": firm_name})
        for row_number, source_values, mapped in rows
    ]
    transformation: dict[str, Any] = {
        "type": "session_firm_override",
        "source_attachment_id": source_attachment_id,
        "source_sha256": source_sha256,
        "firm_name": firm_name,
        "rows_updated": len(overridden),
        "selected_sheet": selected_sheet,
    }
    if source_transformation:
        transformation["prior_source_transformation"] = source_transformation
    return overridden, transformation


def _firm_profile(
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
) -> dict[str, Any]:
    normalized_values: set[str] = set()
    display_values: list[str] = []
    blank_count = 0
    populated_count = 0
    for _, _, mapped in rows:
        display = str(mapped.get("firm_name") or "").strip()
        normalized = norm.firm(display)
        if not normalized:
            blank_count += 1
            continue
        populated_count += 1
        normalized_values.add(normalized)
        if display not in display_values and len(display_values) < 5:
            display_values.append(display)
    return {
        "blank_row_count": blank_count,
        "populated_row_count": populated_count,
        "distinct_count": len(normalized_values),
        "normalized_values": normalized_values,
        "display_sample": display_values,
    }


def _firm_clarification_reason(
    *, blank_count: int, normalized_values: set[str], target: str
) -> Literal["blank_source_firms", "mixed_source_firms", "firm_conflict"]:
    if len(normalized_values) > 1:
        return "mixed_source_firms"
    if normalized_values and normalized_values != {target}:
        return "firm_conflict"
    if blank_count:
        return "blank_source_firms"
    return "firm_conflict"


def _mapped_display_name(mapped: dict[str, str]) -> str:
    return str(mapped.get("full_name") or "").strip() or " ".join(
        value
        for value in (
            str(mapped.get("first_name") or "").strip(),
            str(mapped.get("last_name") or "").strip(),
        )
        if value
    )


def _validated_firm_name(value: str) -> str:
    firm = " ".join(str(value or "").split())
    if not firm or not norm.firm(firm):
        raise ValueError("Provide a nonblank, meaningful all-rows firm.")
    if len(firm) > 200:
        raise ValueError("Firm name must be 200 characters or fewer.")
    if firm.startswith(("=", "+", "-", "@")):
        raise ValueError("Firm name cannot begin with a spreadsheet formula prefix.")
    return firm


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


def _resolve_reference_snapshot(
    *,
    store: AdvisorRepository,
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


def _load_or_create_reference(
    *,
    store: AdvisorRepository,
    workspace: Workspace,
    advisor_source: AdvisorReferenceSource,
    settings: Settings,
    corp_id: str,
    conversation_id: str,
    attachment_id: str,
) -> tuple[ReferenceSnapshotManifest, AdvisorIndex]:
    try:
        stored = store.get_advisor_reference_snapshot_for_attachment(
            attachment_id,
            corp_id=corp_id,
            conversation_id=conversation_id,
        )
    except KeyError:
        stored = None

    if stored is not None:
        manifest, path = _resolve_reference_snapshot(
            store=store,
            workspace=workspace,
            corp_id=corp_id,
            conversation_id=conversation_id,
            snapshot_id=str(stored["id"]),
        )
        return manifest, AdvisorIndex.from_records(_iter_reference(path))

    snapshot_id = "ars_" + uuid.uuid4().hex
    target = workspace.reference_file(corp_id, snapshot_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.building")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MASTER_COLUMNS)
            writer.writeheader()

            def snapshot_records():
                for position, record in enumerate(
                    itertools.islice(
                        advisor_source.iter_records(),
                        settings.advisor_max_reference_rows + 1,
                    ),
                    start=1,
                ):
                    if position > settings.advisor_max_reference_rows:
                        raise ValueError(
                            "Advisor reference source exceeds the configured row limit."
                        )
                    record = record.model_copy(
                        update={"crd_number": norm.crd(record.crd_number)}
                    )
                    writer.writerow(record.master_dict())
                    yield record

            advisor_index = AdvisorIndex.from_records(snapshot_records())
        temporary.replace(target)
        manifest = ReferenceSnapshotManifest(
            reference_snapshot_id=snapshot_id,
            row_count=len(advisor_index.records),
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
            source_attachment_id=attachment_id,
            manifest=manifest.model_dump(mode="json"),
            snapshot_path=target,
        )
        return manifest, advisor_index
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            target.parent.rmdir()
        raise


def _iter_reference(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MASTER_COLUMNS:
            raise ValueError("The advisor reference snapshot schema changed.")
        for row in reader:
            yield AdvisorRecord(
                **{
                    column.lower(): str(row[column] or "").strip()
                    for column in MASTER_COLUMNS
                }
            )


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
