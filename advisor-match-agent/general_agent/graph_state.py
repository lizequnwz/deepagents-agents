"""Typed state and model outputs for the Advisor Match LangGraph."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from general_agent.advisor_matching.schemas import CrdInputMapping, InputMapping


RouteName = Literal[
    "start_match",
    "start_profile_report",
    "reset",
    "greeting",
    "capabilities",
    "unsupported",
]


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RouteName
    all_rows_firm: str | None = Field(default=None, max_length=200)
    firm_column_header: str | None = Field(default=None, max_length=200)
    firm_resolution: Literal[
        "auto", "use_source", "override_all", "continue_without_firm"
    ] = "auto"


class MappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: InputMapping | None = None
    clarification_required: bool = False
    clarification_kind: Literal["confirm_mapping", "provide_details"] | None = None
    clarification_question: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def validate_clarification_contract(self) -> "MappingDecision":
        if not self.clarification_required:
            if self.mapping is None:
                raise ValueError(
                    "A completed mapping decision must include an input mapping."
                )
            return self
        if not self.clarification_question:
            raise ValueError("A mapping clarification must include one question.")
        if self.clarification_kind == "confirm_mapping" and self.mapping is None:
            raise ValueError(
                "A mapping confirmation must include the proposed input mapping."
            )
        if self.clarification_kind == "provide_details" and self.mapping is not None:
            raise ValueError(
                "A detail clarification must not assume an input mapping."
            )
        if self.clarification_kind is None:
            raise ValueError("A mapping clarification must declare its kind.")
        return self


class CrdMappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: CrdInputMapping | None = None
    clarification_required: bool = False
    missing_crd_column: bool = False
    clarification_kind: Literal["confirm_mapping", "provide_details"] | None = None
    clarification_question: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def validate_clarification_contract(self) -> "CrdMappingDecision":
        if self.missing_crd_column:
            if self.mapping is not None or self.clarification_required:
                raise ValueError(
                    "A missing CRD column cannot include a mapping or clarification."
                )
            return self
        if not self.clarification_required:
            if self.mapping is None:
                raise ValueError("A completed CRD mapping decision needs a mapping.")
            return self
        if not self.clarification_question:
            raise ValueError("A CRD mapping clarification must include one question.")
        if self.clarification_kind == "confirm_mapping" and self.mapping is None:
            raise ValueError("A CRD mapping confirmation must include its proposal.")
        if self.clarification_kind == "provide_details" and self.mapping is not None:
            raise ValueError("A detail clarification must not assume a CRD mapping.")
        if self.clarification_kind is None:
            raise ValueError("A CRD mapping clarification must declare its kind.")
        return self


class AdvisorGraphState(TypedDict, total=False):
    corp_id: str
    conversation_id: str
    run_id: str
    user_message: str
    attachment_id: str | None
    is_new_attachment: bool
    requested_workflow: Literal["match", "profile_report"] | None
    source_match_session_id: str | None
    active_workflow: Literal["match", "profile_report"]
    phase: str
    route: dict[str, Any]
    profile: dict[str, Any]
    mapping: dict[str, Any]
    validation: dict[str, Any]
    result: dict[str, Any]
    profile_report_validation: dict[str, Any]
    profile_report_result: dict[str, Any]
    pending_kind: str | None
    pending_payload: dict[str, Any]
    clarification_answer: str | None
    response: str
    error: str | None
