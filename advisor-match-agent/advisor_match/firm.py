"""Deterministic, form-driven firm resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from advisor_match.advisor_matching import normalization as norm
from advisor_match.advisor_matching.schemas import (
    FirmResolution,
    FirmResolutionRequired,
    InputMapping,
    InputSummary,
)

MappedRows = list[tuple[int, dict[str, object], dict[str, str]]]


class FirmResolutionError(ValueError):
    def __init__(self, details: FirmResolutionRequired) -> None:
        super().__init__("Firm resolution is required before matching.")
        self.details = details


@dataclass(frozen=True, slots=True)
class ResolvedFirms:
    rows: MappedRows
    resolution: FirmResolution
    all_rows_firm: str | None
    override_rows: int = 0


def resolve_firms(
    *,
    rows: MappedRows,
    mapping: InputMapping,
    input_summary: InputSummary,
    missing_firm_sample: list[dict[str, Any]],
    all_rows_firm: str | None,
    firm_resolution: FirmResolution,
) -> ResolvedFirms:
    firm = validate_firm_name(all_rows_firm) if all_rows_firm else None
    if firm_resolution in {"use_source", "continue_without_firm"} and firm:
        raise ValueError(
            f"firm_resolution={firm_resolution!r} cannot include all_rows_firm."
        )
    if firm_resolution == "override_all" and not firm:
        raise ValueError("override_all requires an explicit all_rows_firm.")

    if firm_resolution == "use_source":
        if mapping.firm_name is None:
            raise ValueError("use_source requires a mapped firm column.")
        return ResolvedFirms(rows, firm_resolution, None)
    if firm_resolution == "continue_without_firm":
        return ResolvedFirms(rows, firm_resolution, None)
    if firm_resolution == "override_all":
        return _override(rows, firm or "", firm_resolution)

    if firm is None:
        if not input_summary.missing_firm_confirmation_required:
            return ResolvedFirms(rows, "auto", None)
        profile = _firm_profile(rows)
        raise FirmResolutionError(
            FirmResolutionRequired(
                reason="missing_firm",
                data_row_count=len(rows),
                populated_firm_row_count=profile["populated_row_count"],
                blank_firm_row_count=profile["blank_row_count"],
                distinct_source_firm_count=profile["distinct_count"],
                source_firm_sample=profile["display_sample"],
                affected_row_sample=missing_firm_sample,
                allowed_resolutions=["override_all", "continue_without_firm"],
            )
        )

    if mapping.firm_name is None:
        return _override(rows, firm, "override_all")

    profile = _firm_profile(rows)
    target = norm.firm(firm)
    normalized_values = profile["normalized_values"]
    if profile["blank_row_count"] == 0 and normalized_values == {target}:
        return ResolvedFirms(rows, "auto", firm)

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
    raise FirmResolutionError(
        FirmResolutionRequired(
            reason=_firm_clarification_reason(
                blank_count=profile["blank_row_count"],
                normalized_values=normalized_values,
                target=target,
            ),
            stated_firm=firm,
            data_row_count=len(rows),
            populated_firm_row_count=profile["populated_row_count"],
            blank_firm_row_count=profile["blank_row_count"],
            distinct_source_firm_count=profile["distinct_count"],
            source_firm_sample=profile["display_sample"],
            affected_row_sample=affected_rows,
            allowed_resolutions=["use_source", "override_all"],
        )
    )


def validate_firm_name(value: str) -> str:
    firm = " ".join(str(value or "").split())
    if not firm or not norm.firm(firm):
        raise ValueError("Provide a nonblank, meaningful all-rows firm.")
    if len(firm) > 200:
        raise ValueError("Firm name must be 200 characters or fewer.")
    if firm.startswith(("=", "+", "-", "@")):
        raise ValueError("Firm name cannot begin with a spreadsheet formula prefix.")
    return firm


def input_summary_warnings(summary: InputSummary) -> list[str]:
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


def _override(
    rows: MappedRows, firm_name: str, resolution: FirmResolution
) -> ResolvedFirms:
    overridden = [
        (row_number, source_values, {**mapped, "firm_name": firm_name})
        for row_number, source_values, mapped in rows
    ]
    return ResolvedFirms(overridden, resolution, firm_name, len(overridden))


def _firm_profile(rows: MappedRows) -> dict[str, Any]:
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
