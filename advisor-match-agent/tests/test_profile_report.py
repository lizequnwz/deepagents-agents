from __future__ import annotations

import pytest

from general_agent.advisor_matching.profile_report import (
    collect_input_crds,
    collect_matched_crds,
    generate_advisor_profile_report,
)
from general_agent.advisor_matching.schemas import MatchDecision


def _input_row(number: int, crd: str) -> tuple[int, dict[str, object], dict[str, str]]:
    return number, {"CRD": crd}, {"crd_number": crd}


def _decision(status: str, crd: str | None) -> MatchDecision:
    advisor = None
    if crd is not None:
        advisor = {
            "crd_number": crd,
            "first_name": "Avery",
            "last_name": "Stone",
        }
    return MatchDecision.model_validate(
        {
            "review_item_id": f"row-{status}-{crd}",
            "source_row_number": 2,
            "source_values": {},
            "mapped_values": {},
            "status": status,
            "confidence": "High" if status == "Matched" else "None",
            "rule_id": "TEST",
            "explanation": "test",
            "matched_advisor": advisor,
        }
    )


def test_input_crds_are_opaque_trimmed_and_stably_deduplicated() -> None:
    collected = collect_input_crds(
        [
            _input_row(2, " 00123 "),
            _input_row(3, "FSA_ID:111"),
            _input_row(4, "00123"),
            _input_row(5, "  "),
        ]
    )

    assert collected.crd_numbers == ["00123", "FSA_ID:111"]
    assert collected.input_count == 4
    assert collected.blank_count == 1
    assert collected.duplicate_count == 1


def test_only_automatic_matches_supply_profile_crds() -> None:
    collected = collect_matched_crds(
        [
            _decision("Matched", "1001"),
            _decision("Ambiguous Match", None),
            _decision("No Match", None),
            _decision("Matched", "1001"),
            _decision("Matched", "FSA_ID:111"),
        ]
    )

    assert collected.crd_numbers == ["1001", "FSA_ID:111"]
    assert collected.input_count == 3
    assert collected.duplicate_count == 1


def test_placeholder_report_is_static_valid_html() -> None:
    first = generate_advisor_profile_report(["1001"])
    second = generate_advisor_profile_report(["SECRET-CRD"])

    assert first == second
    assert first.startswith("<!doctype html>")
    assert "<body></body>" in first
    assert "1001" not in first
    assert "<script" not in first.casefold()


def test_placeholder_report_rejects_an_empty_crd_list() -> None:
    with pytest.raises(ValueError, match="At least one usable CRD"):
        generate_advisor_profile_report([])
