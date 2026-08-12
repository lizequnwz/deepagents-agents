"""Bounded structured model calls for file-column mapping."""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from advisor_match.advisor_matching.schemas import CrdInputMapping, InputMapping
from advisor_match.config import Settings


MATCH_MAPPING_PROMPT = """Interpret this bounded CSV/XLSX profile into InputMapping.
Select exactly one worksheet and one header row, or explicitly select headerless
input. Each canonical field may map to at most one physical source column. Use
the exact zero-based column index and exact observed header. Names must use either
one full-name column or separate first-name and last-name columns. A valid mapping
needs CRD, email, full name, or both first and last name. Map only columns supported
by the bounded evidence.

Do not guess when multiple worksheets, header rows, or identity interpretations
are genuinely plausible. In that case request one concise clarification naming
the displayed choices. Use clarification_kind=confirm_mapping with a proposal
when a simple confirmation is safe. Use clarification_kind=provide_details and
mapping=null when the user must choose. Never invent columns, headers, or sheets.

Bounded profile JSON:
{profile}
"""


CRD_MAPPING_PROMPT = """Interpret this bounded CSV/XLSX profile into one exact
CrdInputMapping for an advisor profile report. Select exactly one worksheet, one
header row (or headerless input), and exactly one physical CRD column using its
exact zero-based index and observed header. Headers such as CRD, CRD number,
FINRA CRD, advisor CRD, selected CRD, and input CRD are plausible. Do not map
names, emails, firms, or other identity fields.

Set missing_crd_column=true only when no plausible CRD column exists. Do not
guess when multiple sheets, header rows, or CRD columns are plausible; request
one concise clarification naming the choices. Never invent file structure.

Bounded profile JSON:
{profile}
"""


class MappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: InputMapping | None = None
    clarification_required: bool = False
    clarification_kind: Literal["confirm_mapping", "provide_details"] | None = None
    clarification_question: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def validate_decision(self) -> "MappingDecision":
        if not self.clarification_required:
            if self.mapping is None:
                raise ValueError("A completed decision requires an input mapping.")
            if self.clarification_kind or self.clarification_question:
                raise ValueError("A completed decision cannot include clarification.")
            return self
        if not self.clarification_question or self.clarification_kind is None:
            raise ValueError("A clarification requires its kind and one question.")
        if self.clarification_kind == "confirm_mapping" and self.mapping is None:
            raise ValueError("A confirmation clarification requires a proposal.")
        if self.clarification_kind == "provide_details" and self.mapping is not None:
            raise ValueError("A details clarification cannot assume a mapping.")
        return self


class CrdMappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: CrdInputMapping | None = None
    clarification_required: bool = False
    missing_crd_column: bool = False
    clarification_kind: Literal["confirm_mapping", "provide_details"] | None = None
    clarification_question: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def validate_decision(self) -> "CrdMappingDecision":
        if self.missing_crd_column:
            if self.mapping is not None or self.clarification_required:
                raise ValueError("A missing CRD decision cannot include a mapping.")
            return self
        if not self.clarification_required:
            if self.mapping is None:
                raise ValueError("A completed decision requires a CRD mapping.")
            if self.clarification_kind or self.clarification_question:
                raise ValueError("A completed decision cannot include clarification.")
            return self
        if not self.clarification_question or self.clarification_kind is None:
            raise ValueError("A clarification requires its kind and one question.")
        if self.clarification_kind == "confirm_mapping" and self.mapping is None:
            raise ValueError("A confirmation clarification requires a proposal.")
        if self.clarification_kind == "provide_details" and self.mapping is not None:
            raise ValueError("A details clarification cannot assume a mapping.")
        return self


class MappingModelError(RuntimeError):
    pass


class MappingService:
    def __init__(self, settings: Settings, model: BaseChatModel | None = None) -> None:
        model = model or ChatOpenAI(
            model=_openai_model_name(settings.model_name),
            **_model_init_kwargs(settings),
        )
        self._match_model = model.with_structured_output(MappingDecision)
        self._crd_model = model.with_structured_output(CrdMappingDecision)

    async def propose_match(self, profile: dict[str, Any]) -> MappingDecision:
        prompt = MATCH_MAPPING_PROMPT.format(
            profile=json.dumps(profile, ensure_ascii=False, default=str)
        )
        return await _structured_attempts(self._match_model, prompt, MappingDecision)

    async def propose_crd(self, profile: dict[str, Any]) -> CrdMappingDecision:
        prompt = CRD_MAPPING_PROMPT.format(
            profile=json.dumps(profile, ensure_ascii=False, default=str)
        )
        return await _structured_attempts(self._crd_model, prompt, CrdMappingDecision)


async def _structured_attempts(model: Any, prompt: str, schema: type[Any]) -> Any:
    errors: list[str] = []
    current = prompt
    for attempt in range(1, 4):
        try:
            value = await model.ainvoke(current)
            return value if isinstance(value, schema) else schema.model_validate(value)
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}")
            current = (
                prompt
                + "\n\nThe previous structured response was invalid. Return a value "
                + f"that strictly satisfies {schema.__name__}."
            )
    raise MappingModelError(
        f"Could not obtain valid {schema.__name__} after three attempts "
        f"({'; '.join(errors)})."
    )


def _model_init_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs = dict(settings.model_kwargs)
    kwargs.setdefault("streaming", False)
    return kwargs


def _openai_model_name(configured: str) -> str:
    provider, separator, model_name = configured.partition(":")
    if not separator:
        return configured
    if provider.casefold() != "openai" or not model_name:
        raise ValueError(
            "MODEL_NAME must be an OpenAI model name or use the openai:model form."
        )
    return model_name
