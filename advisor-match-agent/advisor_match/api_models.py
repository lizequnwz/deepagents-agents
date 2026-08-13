"""Public request, response, and error models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from advisor_match.advisor_matching.schemas import (
    ColumnRef,
    CrdInputMapping,
    CrdInputValidationResult,
    FirmResolution,
    InputMapping,
    MappingValidationResult,
)
from advisor_match.mapping import CrdMappingDecision, MappingDecision


class MatchConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyzed_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mapping: InputMapping
    firm_resolution: FirmResolution = "auto"
    all_rows_firm: str | None = Field(default=None, max_length=200)


class ProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyzed_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mapping: CrdInputMapping


class SourceDescription(BaseModel):
    filename: str
    format: Literal["csv", "xlsx"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProfilePreviewRow(BaseModel):
    row_number: int = Field(ge=1)
    values: list[str]


class ProfileSampleRow(BaseModel):
    row_number: int = Field(ge=1)
    values: dict[str, str]


class ProfileColumn(BaseModel):
    index: int = Field(ge=0)
    header: str
    label: str
    non_null_sample: int = Field(ge=0)
    pattern: Literal["email", "numeric", "text"]


class HeaderCandidate(BaseModel):
    row_number: int = Field(ge=1)
    columns: list[ProfileColumn]
    sample_rows: list[ProfileSampleRow]
    mapping_suggestions: dict[str, list[ColumnRef]]


class HeaderlessColumn(BaseModel):
    index: int = Field(ge=0)
    header: None = None
    label: str
    pattern: Literal["email", "numeric", "text"]


class HeaderlessProfile(BaseModel):
    columns: list[HeaderlessColumn]
    sample_rows: list[ProfileSampleRow]


class ProfileSheet(BaseModel):
    name: str | None
    preview_row_count: int = Field(ge=0)
    preview_truncated: bool
    preview_rows: list[ProfilePreviewRow]
    header_candidates: list[HeaderCandidate]
    headerless: HeaderlessProfile


class UploadProfile(BaseModel):
    format: Literal["csv", "xlsx"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sheets: list[ProfileSheet]
    warnings: list[str]


class MatchMappingResponse(BaseModel):
    source: SourceDescription
    profile: UploadProfile
    decision: MappingDecision
    validation: MappingValidationResult | None = None
    validation_error: str | None = None


class ProfileMappingResponse(BaseModel):
    source: SourceDescription
    profile: UploadProfile
    decision: CrdMappingDecision
    validation: CrdInputValidationResult | None = None
    validation_error: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
