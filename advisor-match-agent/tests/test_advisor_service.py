from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pytest
from openpyxl import load_workbook

from advisor_match.advisor_matching.index import ReferenceDataQualityError
from advisor_match.advisor_matching.schemas import (
    AdvisorRecord,
    ColumnRef,
    CrdInputMapping,
    InputMapping,
)
from advisor_match.advisor_service import AdvisorService, SourceHashMismatch
from advisor_match.files import InMemoryFile
from advisor_match.firm import FirmResolutionError


REFERENCE = [
    AdvisorRecord(
        crd_number="1001",
        first_name="Avery",
        last_name="Stone",
        firm_name="Northstar Wealth",
        email="avery@example.com",
        city="Boston",
        state="MA",
    ),
    AdvisorRecord(
        crd_number="1002",
        first_name="Robert",
        last_name="Mercer",
        firm_name="Cedar Grove Advisory",
        email="robert@example.com",
        city="Richmond",
        state="VA",
    ),
]


@dataclass
class FakeReferenceSource:
    records: list[AdvisorRecord]
    source_kind: str = "snowflake"
    schema_version: str = "test-v1"
    query_id: str | None = "query-123"

    def iter_records(self):
        yield from self.records


def _service(settings, records=None) -> AdvisorService:
    return AdvisorService(
        settings,
        lambda: FakeReferenceSource(records if records is not None else REFERENCE),
    )


def test_service_validates_matches_and_builds_verified_memory_workbook(
    settings, tmp_path
) -> None:
    source = InMemoryFile(
        "advisors.csv",
        b"CRD,First,Last,Email\n"
        b"1001,Avery,Stone,avery@example.com\n"
        b",Mystery,Person,mystery@example.com\n",
    )
    mapping = InputMapping(
        crd_number=ColumnRef(index=0, header="CRD"),
        first_name=ColumnRef(index=1, header="First"),
        last_name=ColumnRef(index=2, header="Last"),
        email=ColumnRef(index=3, header="Email"),
    )
    before = list(tmp_path.rglob("*"))

    result = _service(settings).match(
        source, analyzed_source_sha256=source.sha256, mapping=mapping
    )

    assert result.result.counts.matched == 1
    assert result.result.counts.no_match == 1
    assert result.result.reference.query_id == "query-123"
    assert len(result.result.reference.sha256) == 64
    assert result.workbook.startswith(b"PK")
    assert list(tmp_path.rglob("*")) == before


def test_profile_generation_is_file_driven_and_deduplicated(settings) -> None:
    source = InMemoryFile(
        "profile.csv",
        b"CRD,Note\n 00123 ,first\nFSA_ID:111,second\n00123,again\n,blank\n",
    )
    mapping = CrdInputMapping(crd_number=ColumnRef(index=0, header="CRD"))
    service = _service(settings)

    validation = service.validate_profile_input(source, mapping)
    result = service.generate_profile(
        source, analyzed_source_sha256=source.sha256, mapping=mapping
    )

    assert validation.unique_crd_count == 2
    assert validation.blank_crd_count == 1
    assert validation.duplicate_crd_count == 1
    assert result.unique_crd_count == 2
    assert result.html.startswith("<!doctype html>")
    assert "00123" not in result.html


def test_changed_source_is_rejected_before_reference_query(settings) -> None:
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        return FakeReferenceSource(REFERENCE)

    source = InMemoryFile("advisors.csv", b"CRD\n1001\n")
    mapping = InputMapping(crd_number=ColumnRef(index=0, header="CRD"))

    with pytest.raises(SourceHashMismatch):
        AdvisorService(settings, factory).match(
            source, analyzed_source_sha256="0" * 64, mapping=mapping
        )

    assert calls == 0


def test_name_only_rows_require_form_driven_firm_resolution(settings) -> None:
    source = InMemoryFile("advisors.csv", b"Name\nAvery Stone\n")
    mapping = InputMapping(full_name=ColumnRef(index=0, header="Name"))
    service = _service(settings)

    with pytest.raises(FirmResolutionError) as raised:
        service.match(source, analyzed_source_sha256=source.sha256, mapping=mapping)

    assert raised.value.details.reason == "missing_firm"
    assert raised.value.details.allowed_resolutions == [
        "override_all",
        "continue_without_firm",
    ]


def test_all_rows_firm_augments_only_copied_matching_values(settings) -> None:
    source = InMemoryFile("advisors.csv", b"Name\nAvery Stone\n")
    mapping = InputMapping(full_name=ColumnRef(index=0, header="Name"))

    execution = _service(settings).match(
        source,
        analyzed_source_sha256=source.sha256,
        mapping=mapping,
        firm_resolution="override_all",
        all_rows_firm="Northstar Wealth",
    )

    assert execution.result.counts.matched == 1
    assert execution.result.firm_override_rows == 1
    workbook = load_workbook(BytesIO(execution.workbook), data_only=True)
    try:
        original = list(workbook["Original Input"].values)
        matched = list(workbook["Matched"].values)
        summary = dict(workbook["Run Summary"].values)
    finally:
        workbook.close()
    assert original == [("Source Row", "Name"), (2, "Avery Stone")]
    assert matched[1][3] == "Northstar Wealth"
    assert summary["User-Supplied Firm"] == "Northstar Wealth"
    assert summary["Rows With Firm Override"] == 1


def test_duplicate_reference_crds_are_a_controlled_blocker(settings) -> None:
    source = InMemoryFile("advisors.csv", b"CRD\n1001\n")
    mapping = InputMapping(crd_number=ColumnRef(index=0, header="CRD"))
    duplicate = [REFERENCE[0], REFERENCE[0].model_copy()]

    with pytest.raises(ReferenceDataQualityError) as raised:
        _service(settings, duplicate).match(
            source, analyzed_source_sha256=source.sha256, mapping=mapping
        )

    assert raised.value.duplicate_crds == {"1001": 2}


def test_reference_digest_is_stable_for_identical_ordered_records(settings) -> None:
    source = InMemoryFile("advisors.csv", b"CRD\n1001\n")
    mapping = InputMapping(crd_number=ColumnRef(index=0, header="CRD"))
    service = _service(settings)

    first = service.match(
        source, analyzed_source_sha256=source.sha256, mapping=mapping
    )
    second = service.match(
        source, analyzed_source_sha256=source.sha256, mapping=mapping
    )

    assert first.result.reference.sha256 == second.result.reference.sha256
