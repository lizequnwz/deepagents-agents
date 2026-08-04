"""Typed state and model outputs for the Advisor Match LangGraph."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from general_agent.advisor_matching.schemas import InputMapping, ReviewDecision


RouteName = Literal[
    "start_match",
    "review",
    "propose_crd",
    "confirm_manual",
    "cancel_manual",
    "approve",
    "status",
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
    match_session_id: str | None = None
    review_status: Literal["matched", "ambiguous_match", "no_match"] | None = None
    source_row_number: int | None = Field(default=None, ge=1)
    name_query: str | None = Field(default=None, max_length=200)
    review_cursor: int = Field(default=0, ge=0)
    review_limit: int = Field(default=10, ge=1, le=20)
    next_page: bool = False
    review_action: Literal["confirm_candidate", "confirm_no_match"] | None = None
    review_decisions: list[ReviewDecision] = Field(default_factory=list, max_length=20)
    review_item_id: str | None = None
    crd_number: str | None = Field(default=None, max_length=32)


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


class AdvisorGraphState(TypedDict, total=False):
    corp_id: str
    conversation_id: str
    run_id: str
    user_message: str
    attachment_id: str | None
    is_new_attachment: bool
    phase: str
    route: dict[str, Any]
    profile: dict[str, Any]
    mapping: dict[str, Any]
    validation: dict[str, Any]
    result: dict[str, Any]
    pending_kind: str | None
    pending_payload: dict[str, Any]
    clarification_answer: str | None
    review_page: dict[str, Any]
    response: str
    error: str | None
