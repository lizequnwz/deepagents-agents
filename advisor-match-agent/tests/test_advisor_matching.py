from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from general_agent.advisor_matching.input_loader import load_input
from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching import policy
from general_agent.advisor_matching.schemas import AdvisorRecord, InputMapping
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource


ADVISORS = [
    AdvisorRecord(
        crd_number="1001", first_name="Robert", last_name="Mercer",
        firm_name="Cedar Grove Advisory", email="robert@example.com",
        street_address="10 Cedar Lane", city="Richmond", state="VA", zip_code="23219",
    ),
    AdvisorRecord(
        crd_number="1002", first_name="John", last_name="Smith",
        firm_name="Northstar Wealth", city="Boston", state="MA", zip_code="02108",
    ),
    AdvisorRecord(
        crd_number="1003", first_name="John", last_name="Smith",
        firm_name="Harbor Advisory", city="Cambridge", state="MA", zip_code="02139",
    ),
]


def _row(row_number: int, **mapped: str):
    values = {
        "crd_number": "", "first_name": "", "last_name": "", "full_name": "",
        "firm_name": "", "email": "", "street_address": "", "city": "",
        "state": "", "zip_code": "",
    }
    values.update(mapped)
    return row_number, dict(values), values


def test_exact_crd_is_decisive_and_reports_conflicts() -> None:
    decisions, counts, _ = run_matching(
        [_row(2, crd_number="1001", full_name="Someone Else", state="CA", email="other@example.com")],
        ADVISORS,
    )
    assert counts.matched == 1
    assert decisions[0].rule_id == "EXACT_CRD"
    assert decisions[0].matched_advisor.crd_number == "1001"
    assert decisions[0].warnings
    assert any("email conflicted" in warning for warning in decisions[0].warnings)


def test_exact_email_can_match_with_unknown_crd_warning() -> None:
    decisions, counts, _ = run_matching(
        [_row(2, crd_number="9999", email="ROBERT@EXAMPLE.COM")], ADVISORS,
    )
    assert counts.matched == 1
    assert decisions[0].rule_id == "UNIQUE_EXACT_EMAIL"
    assert any("CRD was not found" in warning for warning in decisions[0].warnings)


@pytest.mark.parametrize(
    ("mapped", "rule_id"),
    [
        ({"crd_number": "12-34"}, "MALFORMED_CRD"),
        ({"crd_number": "9999"}, "CRD_NOT_FOUND"),
        ({"email": "not-an-email"}, "MALFORMED_EMAIL"),
    ],
)
def test_invalid_identifier_only_rows_have_specific_reasons(mapped, rule_id) -> None:
    decisions, counts, _ = run_matching([_row(2, **mapped)], ADVISORS)
    assert counts.no_match == 1
    assert decisions[0].rule_id == rule_id


def test_nickname_with_support_is_review_only() -> None:
    decisions, counts, _ = run_matching(
        [_row(2, full_name="Bob Mercer", firm_name="Cedar Grove Advisory", city="Richmond", state="VA")],
        ADVISORS,
    )
    assert counts.ambiguous_match == 1
    assert decisions[0].status == "Ambiguous Match"
    assert decisions[0].candidates[0].crd_number == "1001"


def test_name_alone_is_never_confirmed() -> None:
    decisions, counts, _ = run_matching([_row(2, full_name="John Smith")], ADVISORS)
    assert counts.matched == 0
    assert decisions[0].status == "Ambiguous Match"
    assert len(decisions[0].candidates) == 2


def test_last_comma_first_name_format_is_normalized_deterministically() -> None:
    decisions, counts, _ = run_matching(
        [_row(2, full_name="Mercer, Robert", firm_name="Cedar Grove Advisory")],
        ADVISORS,
    )
    assert counts.matched == 1
    assert decisions[0].matched_advisor.crd_number == "1001"


def test_duplicate_input_rows_remain_separate_review_items() -> None:
    rows = [_row(2, crd_number="1001"), _row(3, crd_number="1001")]
    decisions, counts, warnings = run_matching(rows, ADVISORS)
    assert counts.matched == 2
    assert decisions[0].review_item_id != decisions[1].review_item_id
    assert decisions[0].duplicate_group == decisions[1].duplicate_group
    assert warnings


def _binding(index: int, header: str) -> dict:
    return {"columns": [{"index": index, "header": header}]}


@pytest.mark.parametrize(
    ("filename", "mapping", "expected"),
    [
        ("clean_exact_matches.csv", {"crd_number": _binding(0, "CRD_NUMBER"), "first_name": _binding(1, "FIRST_NAME"), "last_name": _binding(2, "LAST_NAME"), "email": _binding(3, "EMAIL")}, (3, 0, 0)),
        ("casing_and_whitespace.xlsx", {"sheet_name": "Advisors", "first_name": _binding(0, "first name"), "last_name": _binding(1, "last name"), "email": _binding(2, "email address"), "firm_name": _binding(3, "firm")}, (2, 0, 0)),
        ("address_variations.csv", {"first_name": _binding(0, "First Name"), "last_name": _binding(1, "Last Name"), "firm_name": _binding(2, "Firm Name"), "street_address": _binding(3, "Street Address"), "city": _binding(4, "City"), "state": _binding(5, "State"), "zip_code": _binding(6, "ZIP")}, (1, 1, 0)),
        ("missing_fields.xlsx", {"sheet_name": "Advisors", "first_name": _binding(0, "First Name"), "last_name": _binding(1, "Last Name"), "email": _binding(2, "Email"), "firm_name": _binding(3, "Firm Name"), "city": _binding(4, "City"), "state": _binding(5, "State")}, (1, 1, 1)),
        ("partial_matches.csv", {"full_name": _binding(0, "Advisor Name"), "firm_name": _binding(1, "Company"), "city": _binding(2, "City"), "state": _binding(3, "State")}, (0, 3, 0)),
        ("duplicate_rows.xlsx", {"sheet_name": "Advisors", "crd_number": _binding(0, "CRD"), "first_name": _binding(1, "First Name"), "last_name": _binding(2, "Last Name"), "email": _binding(3, "Email")}, (3, 0, 0)),
        ("unknown_advisors.csv", {"first_name": _binding(0, "First Name"), "last_name": _binding(1, "Last Name"), "firm_name": _binding(2, "Firm Name"), "city": _binding(3, "City"), "state": _binding(4, "State")}, (0, 0, 2)),
    ],
)
def test_generated_fixtures_have_expected_results(filename, mapping, expected) -> None:
    root = Path(__file__).parents[1]
    advisors = list(SyntheticAdvisorReferenceSource(
        root / "general_agent" / "advisor_matching" / "data" / "master_advisors.csv"
    ).iter_records())
    rows = load_input(
        root / "examples" / "advisor-match" / filename,
        InputMapping.model_validate(mapping), max_rows=100,
    )
    _, counts, _ = run_matching(rows, advisors)
    assert (counts.matched, counts.ambiguous_match, counts.no_match) == expected


def test_skill_policy_reference_matches_executable_policy() -> None:
    root = Path(__file__).parents[1]
    documented = yaml.safe_load(
        (root / "skills" / "advisor-match" / "references" / "matching-policy.yaml").read_text(encoding="utf-8")
    )
    fuzzy = documented["fuzzy"]
    assert documented["version"] == policy.POLICY_VERSION
    assert fuzzy["acceptance_score"] == policy.ACCEPTANCE_SCORE
    assert fuzzy["plausible_score"] == policy.PLAUSIBLE_SCORE
    assert fuzzy["minimum_margin"] == policy.MINIMUM_MARGIN
    assert fuzzy["minimum_name_similarity"] == policy.MINIMUM_NAME_SIMILARITY
    assert fuzzy["weights"] == policy.WEIGHTS


def test_input_loader_stops_at_configured_row_limit(tmp_path) -> None:
    source = tmp_path / "too-many.csv"
    source.write_text("Name\nOne Person\nTwo Person\n", encoding="utf-8")
    mapping = InputMapping.model_validate({"full_name": _binding(0, "Name")})
    with pytest.raises(ValueError, match="limit is 1"):
        load_input(source, mapping, max_rows=1)
