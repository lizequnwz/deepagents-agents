"""Public request, response, and error models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from advisor_match.advisor_matching.schemas import (
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


class MatchMappingResponse(BaseModel):
    source: SourceDescription
    profile: dict[str, Any]
    decision: MappingDecision
    validation: MappingValidationResult | None = None
    validation_error: str | None = None


class ProfileMappingResponse(BaseModel):
    source: SourceDescription
    profile: dict[str, Any]
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
