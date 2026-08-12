from __future__ import annotations

import pytest

from advisor_match.advisor_matching.profile_report import (
    collect_input_crds,
    generate_advisor_profile_report,
)


def _input_row(number: int, crd: str) -> tuple[int, dict[str, object], dict[str, str]]:
    return number, {"CRD": crd}, {"crd_number": crd}


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
