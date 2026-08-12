"""Typed contracts for stateless advisor matching and profile generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

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

MAPPED_FIELDS = (
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


class ColumnRef(BaseModel):
    """One exact physical column selected by position and observed header."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    header: str | None = None


class InputMapping(BaseModel):
    """One-column-per-field mapping for an advisor match input."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    header_row: int | None = Field(default=1, ge=1)
    crd_number: ColumnRef | None = None
    first_name: ColumnRef | None = None
    last_name: ColumnRef | None = None
    full_name: ColumnRef | None = None
    firm_name: ColumnRef | None = None
    email: ColumnRef | None = None
    city: ColumnRef | None = None
    state: ColumnRef | None = None
    zip_code: ColumnRef | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> "InputMapping":
        has_name = bool(self.full_name or (self.first_name and self.last_name))
        if not any((self.crd_number, self.email, has_name)):
            raise ValueError(
                "Map a CRD, email, full name, or both first and last name "
                "before matching."
            )
        if self.full_name and (self.first_name or self.last_name):
            raise ValueError(
                "Choose either a full-name column or separate first and last name columns."
            )
        if bool(self.first_name) != bool(self.last_name):
            raise ValueError(
                "First and last name columns must be mapped together."
            )
        for reference in self.field_refs().values():
            if self.header_row is None and reference.header is not None:
                raise ValueError("Headerless mappings must use null column headers.")
            if self.header_row is not None and reference.header is None:
                raise ValueError(
                    "Headed mappings must include every exact observed header."
                )
        return self

    def field_refs(self) -> dict[str, ColumnRef]:
        return {
            field: reference
            for field in MAPPED_FIELDS
            if (reference := getattr(self, field)) is not None
        }


class CrdInputMapping(BaseModel):
    """Exact worksheet, header row, and physical CRD column selection."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    header_row: int | None = Field(default=1, ge=1)
    crd_number: ColumnRef

    @model_validator(mode="after")
    def validate_crd_binding(self) -> "CrdInputMapping":
        if self.header_row is None and self.crd_number.header is not None:
            raise ValueError("Headerless CRD mappings must use a null column header.")
        if self.header_row is not None and self.crd_number.header is None:
            raise ValueError("Headed CRD mappings must include the observed header.")
        return self

    def as_input_mapping(self) -> InputMapping:
        return InputMapping(
            sheet_name=self.sheet_name,
            header_row=self.header_row,
            crd_number=self.crd_number,
        )


class InputSummary(BaseModel):
    data_row_count: int = Field(ge=0)
    blank_row_count: int = Field(ge=0)
    preamble_row_count: int = Field(ge=0)
    firm_column_missing: bool = False
    missing_firm_row_count: int = Field(ge=0)
    missing_firm_confirmation_required: bool = False


class MappingValidationResult(BaseModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_sheet: str | None
    mapping: InputMapping
    mapping_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    columns: list[dict[str, Any]]
    input_summary: InputSummary
    missing_firm_sample: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5
    )
    warnings: list[str] = Field(default_factory=list)


class CrdInputValidationResult(BaseModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_sheet: str | None
    mapping: CrdInputMapping
    mapping_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    columns: list[dict[str, Any]]
    data_row_count: int = Field(ge=1)
    usable_crd_count: int = Field(ge=0)
    unique_crd_count: int = Field(ge=0)
    blank_crd_count: int = Field(ge=0)
    duplicate_crd_count: int = Field(ge=0)


class AdvisorRecord(BaseModel):
    crd_number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    firm_name: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None

    def master_dict(self) -> dict[str, Optional[str]]:
        return {column: getattr(self, column.lower()) for column in MASTER_COLUMNS}


MatchStatus = Literal["Matched", "Ambiguous Match", "No Match"]
MatchConfidence = Literal["High", "Uncertain", "None"]
FirmResolution = Literal[
    "auto", "use_source", "override_all", "continue_without_firm"
]


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
    candidate_count: int = Field(default=0, ge=0)
    candidates_truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    duplicate_group: str | None = None

    @model_validator(mode="after")
    def validate_candidate_count(self) -> "MatchDecision":
        if self.candidates and self.candidate_count == 0:
            self.candidate_count = len(self.candidates)
        if self.candidate_count < len(self.candidates):
            raise ValueError("candidate_count cannot be smaller than candidates.")
        self.candidates_truncated = self.candidate_count > len(self.candidates)
        return self


class MatchCounts(BaseModel):
    matched: int = 0
    ambiguous_match: int = 0
    no_match: int = 0


class ReferenceManifest(BaseModel):
    row_count: int = Field(gt=0)
    source_kind: str
    schema_version: str
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_id: str | None = None


class MatchResult(BaseModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mapping: InputMapping
    mapping_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_summary: InputSummary
    counts: MatchCounts
    firm_resolution: FirmResolution
    all_rows_firm: str | None = None
    firm_override_rows: int = Field(default=0, ge=0)
    reference: ReferenceManifest
    warnings: list[str] = Field(default_factory=list)
    policy_version: str
    generated_at: datetime


class FirmResolutionRequired(BaseModel):
    reason: Literal[
        "missing_firm",
        "blank_source_firms",
        "mixed_source_firms",
        "firm_conflict",
    ]
    stated_firm: str | None = None
    data_row_count: int = Field(ge=1)
    populated_firm_row_count: int = Field(ge=0)
    blank_firm_row_count: int = Field(ge=0)
    distinct_source_firm_count: int = Field(ge=0)
    source_firm_sample: list[str] = Field(default_factory=list, max_length=5)
    affected_row_sample: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5
    )
    allowed_resolutions: list[
        Literal["use_source", "override_all", "continue_without_firm"]
    ]


class ProfileGenerationResult(BaseModel):
    filename: Literal["advisor_profile_report.html"] = "advisor_profile_report.html"
    media_type: Literal["text/html"] = "text/html"
    html: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mapping: CrdInputMapping
    input_crd_count: int = Field(ge=0)
    unique_crd_count: int = Field(ge=1)
    blank_crd_count: int = Field(ge=0)
    duplicate_crd_count: int = Field(ge=0)
