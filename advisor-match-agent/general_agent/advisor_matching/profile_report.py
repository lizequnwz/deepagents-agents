"""Deterministic CRD collection and placeholder profile-report generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.schemas import MatchDecision


@dataclass(frozen=True, slots=True)
class CrdCollection:
    crd_numbers: list[str]
    input_count: int
    blank_count: int
    duplicate_count: int

    @property
    def unique_count(self) -> int:
        return len(self.crd_numbers)


def collect_input_crds(
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
) -> CrdCollection:
    """Collect the mapped CRD value from every nonblank source row."""

    return _collect(mapped.get("crd_number") for _number, _source, mapped in rows)


def collect_matched_crds(decisions: list[MatchDecision]) -> CrdCollection:
    """Collect only automatically matched advisor CRDs."""

    values = [
        decision.matched_advisor.crd_number
        for decision in decisions
        if decision.status == "Matched" and decision.matched_advisor is not None
    ]
    return _collect(values)


def generate_advisor_profile_report(crd_numbers: list[str]) -> str:
    """Return the supported v1 placeholder report without exposing input values."""

    if not crd_numbers:
        raise ValueError("At least one usable CRD is required to generate a report.")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        "  <title>Advisor Profile Report</title>\n"
        "</head>\n"
        "<body></body>\n"
        "</html>\n"
    )


def verify_advisor_profile_report(path: Path) -> None:
    """Verify the fixed HTML artifact after writing and before publication."""

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("The advisor profile report is not valid UTF-8 HTML.") from exc
    normalized = content.casefold()
    if not normalized.startswith("<!doctype html>"):
        raise ValueError("The advisor profile report is missing its HTML doctype.")
    if "<html" not in normalized or "</html>" not in normalized:
        raise ValueError("The advisor profile report has an incomplete HTML document.")
    if "<script" in normalized:
        raise ValueError("The advisor profile report must not contain scripts.")


def _collect(values) -> CrdCollection:
    seen: set[str] = set()
    unique: list[str] = []
    input_count = 0
    blank_count = 0
    duplicate_count = 0
    for value in values:
        input_count += 1
        crd = norm.crd(value)
        if not crd:
            blank_count += 1
            continue
        if crd in seen:
            duplicate_count += 1
            continue
        seen.add(crd)
        unique.append(crd)
    return CrdCollection(
        crd_numbers=unique,
        input_count=input_count,
        blank_count=blank_count,
        duplicate_count=duplicate_count,
    )
