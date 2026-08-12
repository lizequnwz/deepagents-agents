from __future__ import annotations

import pytest

from advisor_match.advisor_matching.schemas import ColumnRef, InputMapping
from advisor_match.mapping import (
    MappingDecision,
    MappingModelError,
    _openai_model_name,
    _structured_attempts,
)


class SequenceModel:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    async def ainvoke(self, _prompt):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.asyncio
async def test_structured_mapping_retries_up_to_three_times() -> None:
    valid = MappingDecision(
        mapping=InputMapping(crd_number=ColumnRef(index=0, header="CRD"))
    )
    model = SequenceModel([ValueError("bad"), {"mapping": None}, valid])

    result = await _structured_attempts(model, "prompt", MappingDecision)

    assert result == valid
    assert model.calls == 3


@pytest.mark.asyncio
async def test_structured_mapping_fails_after_three_invalid_attempts() -> None:
    model = SequenceModel([ValueError("bad")])

    with pytest.raises(MappingModelError, match="after three attempts"):
        await _structured_attempts(model, "prompt", MappingDecision)

    assert model.calls == 3


def test_mapping_clarification_can_supply_a_concrete_proposal() -> None:
    decision = MappingDecision(
        mapping=InputMapping(crd_number=ColumnRef(index=0, header="CRD")),
        clarification_required=True,
        clarification_kind="confirm_mapping",
        clarification_question="Use CRD from the Advisors worksheet?",
    )

    assert decision.clarification_required is True
    assert decision.mapping.crd_number.index == 0


def test_openai_model_name_accepts_plain_or_provider_prefixed_values() -> None:
    assert _openai_model_name("gpt-5.1") == "gpt-5.1"
    assert _openai_model_name("openai:gpt-5.1") == "gpt-5.1"
    with pytest.raises(ValueError, match="OpenAI"):
        _openai_model_name("anthropic:claude")
