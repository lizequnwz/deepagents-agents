from __future__ import annotations

from datetime import UTC, datetime

from openpyxl import load_workbook

from general_agent.advisor_matching.schemas import (
    InputMapping, MatchCounts, MatchDecision, ReferenceSnapshotManifest,
)
from general_agent.advisor_matching.workbook import SHEETS, verify_match_workbook, write_match_workbook


def test_workbook_is_four_sheet_auditable_and_formula_safe(tmp_path) -> None:
    decision = MatchDecision(
        review_item_id="ami_test", source_row_number=2,
        source_values={"Name": "=HYPERLINK(\"https://invalid.example\")"},
        mapped_values={"full_name": "=HYPERLINK(\"https://invalid.example\")"},
        status="No Match", confidence="None", rule_id="NO_ACCEPTABLE_CANDIDATE",
        explanation="No advisor satisfied the accepted identity rules.",
    )
    reference = ReferenceSnapshotManifest(
        snapshot_virtual_path="/tmp/advisor_reference.csv", row_count=40,
        columns=["CRD_NUMBER"], source_kind="synthetic", schema_version="1",
        retrieved_at=datetime.now(UTC), sha256="a" * 64,
    )
    output = tmp_path / "advisor_matches.xlsx"
    write_match_workbook(
        output, session_id="ams_test", decisions=[decision],
        counts=MatchCounts(no_match=1), mapping=InputMapping(full_name={"columns": [{"index": 0, "header": "Name"}]}),
        source_name="input.csv", source_sha256="b" * 64, reference=reference,
        policy_version="1",
    )
    assert verify_match_workbook(output, expected_rows=1) == {"matched": 0, "review_items": 1, "original": 1}
    workbook = load_workbook(output, data_only=False)
    assert tuple(workbook.sheetnames) == SHEETS
    cell = workbook["Original Input"]["B2"]
    assert cell.value.startswith("=")
    assert cell.data_type == "s"
    workbook.close()
