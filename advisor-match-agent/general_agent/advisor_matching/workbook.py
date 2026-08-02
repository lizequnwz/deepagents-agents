"""Safe, deterministic advisor-match workbook projection and verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill

from general_agent.advisor_matching.schemas import InputMapping, MatchCounts, MatchDecision, ReferenceSnapshotManifest

SHEETS = ("Matched", "Review Required", "Original Input", "Run Summary")
_STATUS_FILL = {"Matched": "D9EAD3", "Ambiguous Match": "FFF2CC", "No Match": "F4CCCC"}


def write_match_workbook(
    output: Path,
    *,
    session_id: str,
    decisions: list[MatchDecision],
    counts: MatchCounts,
    mapping: InputMapping,
    source_name: str,
    source_sha256: str,
    reference: ReferenceSnapshotManifest,
    policy_version: str,
    session_status: str = "Reviewing",
    session_revision: int = 1,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.building{output.suffix}")
    workbook = Workbook(write_only=True)
    _write_matched(workbook.create_sheet("Matched"), decisions)
    _write_review(workbook.create_sheet("Review Required"), decisions)
    _write_original(workbook.create_sheet("Original Input"), decisions)
    _write_summary(
        workbook.create_sheet("Run Summary"), session_id=session_id, counts=counts,
        mapping=mapping, source_name=source_name, source_sha256=source_sha256,
        reference=reference, policy_version=policy_version, session_status=session_status,
        session_revision=session_revision,
        row_warning_count=sum(bool(decision.warnings) for decision in decisions),
        duplicate_row_count=sum(decision.duplicate_group is not None for decision in decisions),
    )
    workbook.save(temporary)
    verify_match_workbook(temporary, expected_rows=len(decisions))
    temporary.replace(output)


def verify_match_workbook(path: Path, *, expected_rows: int | None = None) -> dict[str, int]:
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if tuple(workbook.sheetnames) != SHEETS:
            raise ValueError(f"Unexpected workbook sheets: {workbook.sheetnames!r}.")
        matched = sum(1 for _ in workbook["Matched"].iter_rows(min_row=2, values_only=True))
        review_item_ids = {
            row[0]
            for row in workbook["Review Required"].iter_rows(min_row=2, values_only=True)
            if row and row[0]
        }
        original = sum(1 for _ in workbook["Original Input"].iter_rows(min_row=2, values_only=True))
        if expected_rows is not None and original != expected_rows:
            raise ValueError(f"Original Input has {original} rows; expected {expected_rows}.")
        if matched + len(review_item_ids) != original:
            raise ValueError("Matched and Review Required decisions do not reconcile to Original Input.")
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        raise ValueError(f"Formula cell is not allowed: {sheet.title}!{cell.coordinate}.")
        return {"matched": matched, "review_items": len(review_item_ids), "original": original}
    finally:
        workbook.close()


def _write_matched(sheet, decisions):
    headers = _decision_headers(include_candidate=False)
    _append(sheet, headers, header=True)
    for decision in decisions:
        if decision.status == "Matched":
            _append(sheet, _decision_row(decision, decision.matched_advisor))


def _write_review(sheet, decisions):
    headers = _decision_headers(include_candidate=True)
    _append(sheet, headers, header=True)
    for decision in decisions:
        if decision.status == "Matched":
            continue
        candidates = decision.candidates or [None]
        for rank, candidate in enumerate(candidates, start=1):
            _append(sheet, _decision_row(decision, candidate, rank=rank))


def _write_original(sheet, decisions):
    source_headers = []
    for decision in decisions:
        for header in decision.source_values:
            if header not in source_headers:
                source_headers.append(header)
    _append(sheet, ["source_row_number", *source_headers], header=True)
    for decision in decisions:
        _append(sheet, [decision.source_row_number, *[decision.source_values.get(header, "") for header in source_headers]])


def _write_summary(sheet, **values):
    _append(sheet, ["Field", "Value"], header=True)
    counts = values.pop("counts")
    mapping = values.pop("mapping")
    reference = values.pop("reference")
    ordered = {
        **values,
        "matched_count": counts.matched,
        "ambiguous_match_count": counts.ambiguous_match,
        "no_match_count": counts.no_match,
        "input_mapping": json.dumps(mapping.model_dump(mode="json"), sort_keys=True),
        "reference_row_count": reference.row_count,
        "reference_sha256": reference.sha256,
        "reference_retrieved_at": reference.retrieved_at.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    for key, value in ordered.items():
        _append(sheet, [key, value if value is not None else ""])


def _decision_headers(*, include_candidate):
    prefix = "candidate_advisor_" if include_candidate else "advisor_"
    return [
        "review_item_id", "source_row_number", "match_status", "match_confidence",
        "match_rule_id", "decision_source", "match_explanation", "warnings",
        "automated_status", "duplicate_group",
        "input_crd_number", "input_first_name", "input_last_name", "input_full_name",
        "input_firm_name", "input_email", "input_street_address", "input_city",
        "input_state", "input_zip_code",
        "candidate_rank" if include_candidate else "advisor_rank",
        f"{prefix}crd_number", f"{prefix}first_name", f"{prefix}last_name",
        f"{prefix}firm_name", f"{prefix}email", f"{prefix}street_address",
        f"{prefix}city", f"{prefix}state", f"{prefix}zip_code",
        "matched_fields", "conflicting_fields",
    ]


def _decision_row(decision, candidate, *, rank=1):
    advisor = candidate.model_dump(exclude={"matched_fields", "conflicting_fields", "internal_score"}) if candidate else {}
    mapped = decision.mapped_values
    return [
        decision.review_item_id, decision.source_row_number, decision.status, decision.confidence,
        decision.rule_id, decision.decision_source, decision.explanation, "; ".join(decision.warnings),
        decision.automated_status or decision.status, decision.duplicate_group or "",
        mapped.get("crd_number", ""), mapped.get("first_name", ""), mapped.get("last_name", ""),
        mapped.get("full_name", ""), mapped.get("firm_name", ""), mapped.get("email", ""),
        mapped.get("street_address", ""), mapped.get("city", ""), mapped.get("state", ""),
        mapped.get("zip_code", ""), rank if candidate else "",
        advisor.get("crd_number", ""), advisor.get("first_name", ""), advisor.get("last_name", ""),
        advisor.get("firm_name", ""), advisor.get("email", ""), advisor.get("street_address", ""),
        advisor.get("city", ""), advisor.get("state", ""), advisor.get("zip_code", ""),
        ", ".join(candidate.matched_fields) if candidate else "",
        ", ".join(candidate.conflicting_fields) if candidate else "",
    ]


def _append(sheet, values, *, header=False):
    cells = []
    for value in values:
        cell = WriteOnlyCell(sheet, value="" if value is None else value)
        if isinstance(value, str):
            cell.data_type = "s"
        cell.font = Font(name="Arial", bold=header)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        if not header and value in _STATUS_FILL:
            cell.fill = PatternFill("solid", fgColor=_STATUS_FILL[value])
        cells.append(cell)
    sheet.append(cells)
