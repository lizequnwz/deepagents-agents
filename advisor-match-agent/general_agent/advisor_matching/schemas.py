"""Typed contracts shared by advisor tools and deterministic matching code."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MASTER_COLUMNS = (
    "CRD_NUMBER", "FIRST_NAME", "LAST_NAME", "FIRM_NAME", "EMAIL",
    "STREET_ADDRESS", "CITY", "STATE", "ZIP_CODE",
)


class ColumnRef(BaseModel):
    index: int = Field(ge=0)
    header: str = Field(min_length=1)


class FieldBinding(BaseModel):
    columns: list[ColumnRef] = Field(min_length=1)
    combine: Literal["first", "join_space"] = "first"


class InputMapping(BaseModel):
    sheet_name: str | None = None
    header_row: int = Field(default=1, ge=1)
    crd_number: FieldBinding | None = None
    first_name: FieldBinding | None = None
    last_name: FieldBinding | None = None
    full_name: FieldBinding | None = None
    firm_name: FieldBinding | None = None
    email: FieldBinding | None = None
    street_address: FieldBinding | None = None
    city: FieldBinding | None = None
    state: FieldBinding | None = None
    zip_code: FieldBinding | None = None

    @model_validator(mode="after")
    def require_identity_evidence(self) -> "InputMapping":
        if not any((self.crd_number, self.email, self.first_name, self.last_name, self.full_name)):
            raise ValueError("Map a CRD, email, or advisor name before matching.")
        return self


class AdvisorRecord(BaseModel):
    crd_number: str
    first_name: str
    last_name: str
    firm_name: str = ""
    email: str = ""
    street_address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    def master_dict(self) -> dict[str, str]:
        return {column: getattr(self, column.lower()) for column in MASTER_COLUMNS}


MatchStatus = Literal["Matched", "Ambiguous Match", "No Match"]
MatchConfidence = Literal["High", "Uncertain", "None", "User Confirmed"]


class MatchCandidate(BaseModel):
    crd_number: str
    first_name: str
    last_name: str
    firm_name: str = ""
    email: str = ""
    street_address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    matched_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    internal_score: float = Field(default=0, ge=0, le=1, exclude=True)


class MatchDecision(BaseModel):
    review_item_id: str
    source_row_number: int = Field(ge=1)
    source_values: dict[str, object]
    mapped_values: dict[str, str]
    status: MatchStatus
    confidence: MatchConfidence
    rule_id: str
    explanation: str
    matched_advisor: MatchCandidate | None = None
    candidates: list[MatchCandidate] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list)
    duplicate_group: str | None = None
    decision_source: Literal["Automated", "User Override"] = "Automated"
    automated_status: MatchStatus | None = None


class MatchCounts(BaseModel):
    matched: int = 0
    ambiguous_match: int = 0
    no_match: int = 0


class ReferenceSnapshotManifest(BaseModel):
    snapshot_virtual_path: Literal["/tmp/advisor_reference.csv"]
    row_count: int = Field(gt=0)
    columns: list[str]
    source_kind: Literal["synthetic", "snowflake"]
    schema_version: str
    retrieved_at: datetime
    sha256: str
    query_id: str | None = None


class MatchRunResult(BaseModel):
    match_session_id: str
    output_virtual_path: Literal["/advisor_matches.xlsx"]
    selected_sheet: str | None
    counts: MatchCounts
    warnings: list[str] = Field(default_factory=list)
    policy_version: str


class ReviewDecision(BaseModel):
    review_item_id: str
    action: Literal["confirm_candidate", "confirm_manual_crd", "confirm_no_match", "reopen"]
    crd_number: str | None = None
    proposal_id: str | None = None
    note: str = ""


class ManualOverrideProposal(BaseModel):
    proposal_id: str
    match_session_id: str
    review_item_id: str
    advisor: MatchCandidate
    reference_sha256: str
    status: Literal["Pending", "Applied", "Invalidated"] = "Pending"


class ProfileBuildRequest(BaseModel):
    """# TODO: register only when advisor profile building is implemented."""
    match_session_id: str
    matched_crd_numbers: list[str] = Field(default_factory=list)
