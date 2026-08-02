"""Typed contracts shared by advisor tools and deterministic matching code."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MASTER_COLUMNS = (
    "CRD_NUMBER",
    "FIRST_NAME",
    "LAST_NAME",
    "FIRM_NAME",
    "EMAIL",
    "CITY",
    "STATE",
    "ZIP_CODE",
)


class ColumnRef(BaseModel):
    """One exact physical column binding.

    ``header`` is the observed header value for headed input and ``None`` for
    headerless input. The zero-based index remains decisive when headers are
    duplicated.
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    header: str | None = None


class FieldBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnRef] = Field(min_length=1)
    combine: Literal["first", "join_space"] = "first"


class InputMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    header_row: int | None = Field(default=1, ge=1)
    crd_number: FieldBinding | None = None
    first_name: FieldBinding | None = None
    last_name: FieldBinding | None = None
    full_name: FieldBinding | None = None
    firm_name: FieldBinding | None = None
    email: FieldBinding | None = None
    city: FieldBinding | None = None
    state: FieldBinding | None = None
    zip_code: FieldBinding | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> "InputMapping":
        has_name = bool(self.full_name or (self.first_name and self.last_name))
        if not any((self.crd_number, self.email, has_name)):
            raise ValueError(
                "Map a CRD, email, full name, or both first and last name "
                "before matching."
            )
        for binding in self.field_bindings().values():
            for reference in binding.columns:
                if self.header_row is None and reference.header is not None:
                    raise ValueError(
                        "Headerless mappings must use null column headers."
                    )
                if self.header_row is not None and reference.header is None:
                    raise ValueError(
                        "Headed mappings must include every exact observed header."
                    )
        return self

    def field_bindings(self) -> dict[str, FieldBinding]:
        fields = (
            "crd_number",
            "first_name",
            "last_name",
            "full_name",
            "firm_name",
            "email",
            "city",
            "state",
            "zip_code",
        )
        return {
            field: binding
            for field in fields
            if (binding := getattr(self, field)) is not None
        }


class InputSummary(BaseModel):
    data_row_count: int = Field(ge=0)
    blank_row_count: int = Field(ge=0)
    preamble_row_count: int = Field(ge=0)
    missing_firm_row_count: int = Field(ge=0)
    missing_firm_confirmation_required: bool = False


class MappingValidationResult(BaseModel):
    attachment_id: str
    source_sha256: str
    selected_sheet: str | None
    mapping: InputMapping
    mapping_fingerprint: str
    columns: list[dict[str, Any]]
    input_summary: InputSummary
    missing_firm_sample: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5
    )
    warnings: list[str] = Field(default_factory=list)


class AdvisorRecord(BaseModel):
    crd_number: str
    first_name: str
    last_name: str
    firm_name: str = ""
    email: str = ""
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
    city: str = ""
    state: str = ""
    zip_code: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    contextual_evidence: list[str] = Field(default_factory=list)
    internal_score: float = Field(default=0, ge=0, le=1, exclude=True)
    internal_name_similarity: float = Field(default=0, ge=0, le=1, exclude=True)
    internal_alias_name_similarity: float = Field(
        default=0, ge=0, le=1, exclude=True
    )
    internal_firm_similarity: float = Field(default=0, ge=0, le=1, exclude=True)
    internal_exact_firm: bool = Field(default=False, exclude=True)
    internal_close_firm: bool = Field(default=False, exclude=True)
    internal_location_match: bool = Field(default=False, exclude=True)
    internal_state_conflict: bool = Field(default=False, exclude=True)
    internal_firm_conflict: bool = Field(default=False, exclude=True)


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
    reference_snapshot_id: str = Field(pattern=r"^ars_[a-f0-9]{32}$")
    row_count: int = Field(gt=0)
    columns: list[str]
    source_kind: Literal["synthetic", "snowflake"]
    schema_version: str
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_id: str | None = None


class MatchRunResult(BaseModel):
    match_session_id: str
    output_artifact_id: str
    selected_sheet: str | None
    interpreted_mapping: InputMapping
    mapping_fingerprint: str
    input_summary: InputSummary
    counts: MatchCounts
    warnings: list[str] = Field(default_factory=list)
    policy_version: str


class ReviewDecision(BaseModel):
    review_item_id: str
    action: Literal[
        "confirm_candidate", "confirm_manual_crd", "confirm_no_match"
    ]
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
    model_config = ConfigDict(extra="forbid")
