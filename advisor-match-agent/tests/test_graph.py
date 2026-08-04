from __future__ import annotations

import pytest

from langgraph.graph import END
from langgraph.types import Command

from general_agent import user_messages
from general_agent.advisor_matching.schemas import (
    ColumnRef,
    FieldBinding,
    InputMapping,
    InputSummary,
    MappingValidationResult,
)
from general_agent.graph import (
    _after_inspect,
    _firm_question,
    _manual_confirmation_route,
    _mapping_with_firm_column,
    _route_edge,
    _structured_attempts,
    build_advisor_graph,
)
from general_agent.graph_state import MappingDecision, RouteDecision


class StructuredModel:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    async def ainvoke(self, _prompt):
        self.calls += 1
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class MatchRequestModel:
    def with_structured_output(self, schema):
        class Output:
            async def ainvoke(_self, _prompt):
                if schema is RouteDecision:
                    return RouteDecision(route="start_match")
                return MappingDecision(clarification_required=True)

        return Output()


class GreetingModel:
    def with_structured_output(self, schema):
        class Output:
            async def ainvoke(_self, _prompt):
                if schema is RouteDecision:
                    return RouteDecision(route="greeting")
                raise AssertionError(f"Unexpected schema: {schema}")

        return Output()


class MappingClarificationModel:
    def __init__(self, decisions: list[MappingDecision]) -> None:
        self.decisions = iter(decisions)
        self.route_calls = 0
        self.mapping_prompts: list[str] = []

    def with_structured_output(self, schema):
        outer = self

        class Output:
            async def ainvoke(_self, prompt):
                if schema is RouteDecision:
                    outer.route_calls += 1
                    return RouteDecision(route="start_match")
                if schema is MappingDecision:
                    outer.mapping_prompts.append(prompt)
                    return next(outer.decisions)
                raise AssertionError(f"Unexpected schema: {schema}")

        return Output()


class MappingWorkflowService:
    def __init__(self) -> None:
        self.validated_mappings: list[InputMapping] = []

    def inspect(self, _context, attachment_id):
        return {
            "attachment_id": attachment_id,
            "file_type": "csv",
            "sheets": [
                {
                    "sheet_name": None,
                    "sample_rows": [
                        ["12345", "Jane", "Smith", "ABC Wealth", "Boston", "MA"]
                    ],
                }
            ],
        }

    def validate(self, _context, attachment_id, mapping):
        self.validated_mappings.append(mapping)
        columns = [
            {"index": index, "header": None, "label": f"Column {index + 1}"}
            for index in range(6)
        ]
        return MappingValidationResult(
            attachment_id=attachment_id,
            source_sha256="a" * 64,
            selected_sheet=None,
            mapping=mapping,
            mapping_fingerprint="mapping-fingerprint",
            columns=columns,
            input_summary=InputSummary(
                data_row_count=1,
                blank_row_count=0,
                preamble_row_count=0,
                missing_firm_row_count=0,
            ),
        )

    def create_match(
        self,
        _context,
        _validation,
        *,
        all_rows_firm=None,
        firm_resolution="auto",
    ):
        assert all_rows_firm is None
        assert firm_resolution == "auto"

        class Result:
            def model_dump(_self, *, mode):
                assert mode == "json"
                return {
                    "workflow_status": "match_created",
                    "match_session_id": "ams_test",
                    "output_artifact_id": "art_test",
                    "counts": {
                        "matched": 1,
                        "ambiguous_match": 0,
                        "no_match": 0,
                    },
                }

        return Result()


def _headerless_mapping() -> InputMapping:
    def binding(index: int) -> FieldBinding:
        return FieldBinding(columns=[ColumnRef(index=index, header=None)])

    return InputMapping(
        header_row=None,
        crd_number=binding(0),
        first_name=binding(1),
        last_name=binding(2),
        firm_name=binding(3),
        city=binding(4),
        state=binding(5),
    )


@pytest.mark.asyncio
async def test_structured_output_uses_at_most_three_total_attempts() -> None:
    model = StructuredModel([ValueError("bad"), {}, {"route": "capabilities"}])
    result = await _structured_attempts(model, "route", RouteDecision)
    assert result.route == "capabilities"
    assert model.calls == 3


@pytest.mark.asyncio
async def test_structured_output_fails_safely_after_three_attempts() -> None:
    model = StructuredModel([ValueError("bad")] * 3)
    with pytest.raises(ValueError, match="after three attempts"):
        await _structured_attempts(model, "route", RouteDecision)
    assert model.calls == 3


def test_match_request_without_attachment_stops_after_prompting_for_file() -> None:
    state = {
        "phase": "idle",
        "response": "Attach one advisor CSV or XLSX file to start matching.",
    }
    assert _after_inspect(state) == END


@pytest.mark.asyncio
async def test_graph_asks_for_attachment_instead_of_entering_mapping(settings) -> None:
    graph = build_advisor_graph(
        settings,
        service=object(),  # inspect exits before the service is needed
        model=MatchRequestModel(),
    )
    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Help me match advisors",
            "is_new_attachment": False,
            "phase": "idle",
        },
        config={"configurable": {"thread_id": "A123456:conversation-one"}},
    )
    assert "Attach one advisor CSV or XLSX file" in result["response"]
    assert "CRD" in result["response"]
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_graph_greets_and_guides_the_user(settings) -> None:
    graph = build_advisor_graph(
        settings,
        service=object(),
        model=GreetingModel(),
    )
    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "hello",
            "is_new_attachment": False,
            "phase": "idle",
        },
        config={"configurable": {"thread_id": "A123456:conversation-one"}},
    )
    assert result["response"].startswith("Hi!")
    assert "attach one raw advisor CSV or XLSX file" in result["response"]


@pytest.mark.asyncio
async def test_yes_resumes_proposed_mapping_without_general_routing(settings) -> None:
    proposed = _headerless_mapping()
    model = MappingClarificationModel(
        [
            MappingDecision(
                mapping=proposed,
                clarification_required=True,
                clarification_kind="confirm_mapping",
                clarification_question=(
                    "The file may have no header row. Should I treat the first row "
                    "as data using the proposed column order?"
                ),
            )
        ]
    )
    service = MappingWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)
    config = {"configurable": {"thread_id": "mapping-confirmation"}}

    interrupted = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Match the advisors in the uploaded file",
            "attachment_id": "att_test",
            "is_new_attachment": True,
            "phase": "idle",
        },
        config=config,
    )

    assert interrupted["__interrupt__"]
    assert interrupted["pending_payload"]["proposed_mapping"]["header_row"] is None

    result = await graph.ainvoke(
        Command(resume={"message": "Yes", "run_id": "run-two"}),
        config=config,
    )

    assert result["phase"] == "review"
    assert result["pending_kind"] is None
    assert result["clarification_answer"] is None
    assert "finished matching" in result["response"]
    assert service.validated_mappings == [proposed]
    assert model.route_calls == 1
    assert len(model.mapping_prompts) == 1


@pytest.mark.asyncio
async def test_mapping_detail_resume_includes_bounded_pending_context(settings) -> None:
    question = (
        "Does this file have no header row, with CRD number in the first column?"
    )
    answer = "No header row; use that column order."
    resolved = _headerless_mapping()
    model = MappingClarificationModel(
        [
            MappingDecision(
                clarification_required=True,
                clarification_kind="provide_details",
                clarification_question=question,
            ),
            MappingDecision(mapping=resolved),
        ]
    )
    service = MappingWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)
    config = {"configurable": {"thread_id": "mapping-details"}}

    await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Match the advisors in the uploaded file",
            "attachment_id": "att_test",
            "is_new_attachment": True,
            "phase": "idle",
        },
        config=config,
    )
    result = await graph.ainvoke(
        Command(resume={"message": answer, "run_id": "run-two"}),
        config=config,
    )

    assert result["phase"] == "review"
    assert service.validated_mappings == [resolved]
    assert model.route_calls == 1
    assert len(model.mapping_prompts) == 2
    assert f"Prior clarification question: {question}" in model.mapping_prompts[1]
    assert f"User clarification answer: {answer}" in model.mapping_prompts[1]


def test_unsupported_with_attachment_does_not_ask_for_another_upload() -> None:
    response = user_messages.unsupported(has_attachment=True)

    assert "already have the uploaded file" in response
    assert "Attach one advisor" not in response


def test_missing_firm_question_explains_evidence_and_user_choices() -> None:
    question = _firm_question(
        {
            "pending_payload": {
                "reason": "missing_firm",
                "data_row_count": 4,
            },
            "validation": {
                "mapping": {},
                "columns": [
                    {"index": 0, "header": "Advisor", "label": "Advisor"},
                    {"index": 1, "header": "Employer", "label": "Employer"},
                ],
                "input_summary": {
                    "data_row_count": 4,
                    "firm_column_missing": True,
                    "missing_firm_row_count": 4,
                },
            },
        }
    )

    assert "couldn’t identify a firm column" in question
    assert "does not provide a CRD number or valid email" in question
    assert "Use Employer as the firm column" in question
    assert "Use ABC Wealth for all advisors" in question
    assert "missing_firm" not in question
    assert "override_all" not in question


def test_exact_observed_column_can_be_added_to_existing_mapping() -> None:
    validation = MappingValidationResult(
        attachment_id="att-one",
        source_sha256="a" * 64,
        selected_sheet=None,
        mapping=InputMapping(
            full_name=FieldBinding(
                columns=[ColumnRef(index=0, header="Advisor")]
            )
        ),
        mapping_fingerprint="fingerprint",
        columns=[
            {"index": 0, "header": "Advisor", "label": "Advisor"},
            {"index": 1, "header": "Employer", "label": "Employer"},
        ],
        input_summary=InputSummary(
            data_row_count=2,
            blank_row_count=0,
            preamble_row_count=0,
            firm_column_missing=True,
            missing_firm_row_count=2,
            missing_firm_confirmation_required=True,
        ),
    )

    mapping = _mapping_with_firm_column(validation, "employer")

    assert mapping.full_name == validation.mapping.full_name
    assert mapping.firm_name is not None
    assert mapping.firm_name.columns[0] == ColumnRef(index=1, header="Employer")


def test_firm_column_answer_routes_to_remapping() -> None:
    assert (
        _route_edge(
            {
                "route": {
                    "route": "start_match",
                    "firm_column_header": "Employer",
                },
                "validation": {"mapping": {}},
                "pending_kind": "firm",
            }
        )
        == "remap_firm"
    )


def test_manual_confirmation_phrases_are_deterministic() -> None:
    assert _manual_confirmation_route("Confirm this match!") == "confirm_manual"
    assert _manual_confirmation_route("Cancel this match") == "cancel_manual"
    assert _manual_confirmation_route("Tell me more") is None


def test_match_completion_is_actionable_and_hides_artifact_ids() -> None:
    response = user_messages.match_complete(
        {"matched": 84, "ambiguous_match": 11, "no_match": 5}
    )

    assert "100 advisors" in response
    assert "review the 11 ambiguous advisors" in response
    assert "review the 5 unmatched advisors" in response
    assert "artifact" not in response.casefold()


def test_review_page_shows_decision_context_without_internal_ids() -> None:
    response = user_messages.review_page(
        {
            "items": [
                {
                    "review_item_id": "ami_internal",
                    "source_row_number": 12,
                    "input": {"full_name": "Jane Smith"},
                    "reason": "Two exact-name candidates require review.",
                    "warnings": [],
                    "candidates": [
                        {
                            "crd_number": "12345",
                            "first_name": "Jane",
                            "last_name": "Smith",
                            "firm_name": "ABC Wealth",
                            "city": "Boston",
                            "state": "MA",
                            "supporting_evidence": ["Exact normalized name"],
                            "conflicting_evidence": [],
                        }
                    ],
                }
            ],
            "total": 1,
            "next_cursor": None,
        }
    )

    assert "Row 12 — Jane Smith" in response
    assert "ABC Wealth" in response
    assert "Boston, MA" in response
    assert "Choose CRD <number> for row 12" in response
    assert "ami_internal" not in response


class FixedRouteModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def with_structured_output(self, schema):
        class Output:
            async def ainvoke(_self, _prompt):
                if schema is RouteDecision:
                    return self.decision
                raise AssertionError(f"Unexpected schema: {schema}")

        return Output()


class ReviewService:
    def __init__(self) -> None:
        self.applied = []
        self.list_kwargs = []

    def list_results(self, *_args, **kwargs):
        self.list_kwargs.append(kwargs)
        return {
            "items": [
                {
                    "review_item_id": "ami_internal",
                    "source_row_number": 12,
                    "input": {"full_name": "Jane Smith"},
                    "candidates": [],
                }
            ],
            "total": 1,
            "next_cursor": None,
        }

    def apply_decisions(
        self, _context, _session_id, decisions, *, approve_session=False
    ):
        assert approve_session is False
        self.applied.extend(decisions)
        return {
            "match_session_id": "ams_internal",
            "counts": {"matched": 1, "ambiguous_match": 0, "no_match": 0},
            "status": "In Review",
            "output_artifact_id": "art_internal",
        }


@pytest.mark.asyncio
async def test_row_based_review_action_resolves_hidden_item_id(settings) -> None:
    service = ReviewService()
    graph = build_advisor_graph(
        settings,
        service=service,
        model=FixedRouteModel(
            RouteDecision(
                route="review",
                review_action="confirm_no_match",
                source_row_number=12,
            )
        ),
    )
    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Leave row 12 unmatched",
            "phase": "review",
            "result": {"match_session_id": "ams_internal"},
        },
        config={"configurable": {"thread_id": "review-command"}},
    )

    assert service.applied[0].review_item_id == "ami_internal"
    assert service.applied[0].action == "confirm_no_match"
    assert "regenerated the workbook below" in result["response"]
    assert "ami_internal" not in result["response"]
    assert "art_internal" not in result["response"]


@pytest.mark.asyncio
async def test_manual_confirmation_uses_pending_ids_without_showing_them(settings) -> None:
    service = ReviewService()
    graph = build_advisor_graph(
        settings,
        service=service,
        model=FixedRouteModel(RouteDecision(route="confirm_manual")),
    )
    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "confirmation-run",
            "user_message": "Confirm this match",
            "phase": "manual_crd_confirmation",
            "pending_kind": "manual_crd",
            "pending_payload": {
                "proposal_id": "amp_internal",
                "match_session_id": "ams_internal",
                "review_item_id": "ami_internal",
                "crd_number": "12345",
                "source_row_number": 12,
            },
            "result": {"match_session_id": "ams_internal"},
        },
        config={"configurable": {"thread_id": "manual-confirmation"}},
    )

    applied = service.applied[0]
    assert applied.action == "confirm_manual_crd"
    assert applied.proposal_id == "amp_internal"
    assert result["pending_kind"] is None
    assert "amp_internal" not in result["response"]
    assert "ami_internal" not in result["response"]


@pytest.mark.asyncio
async def test_next_review_page_uses_bounded_cursor_and_filter_from_state(settings) -> None:
    service = ReviewService()
    graph = build_advisor_graph(
        settings,
        service=service,
        model=FixedRouteModel(RouteDecision(route="review", next_page=True)),
    )
    await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "next-page-run",
            "user_message": "Show the next review page",
            "phase": "review",
            "result": {"match_session_id": "ams_internal"},
            "review_page": {
                "next_cursor": 10,
                "_status_filter": "no_match",
                "_name_query": None,
            },
        },
        config={"configurable": {"thread_id": "next-review-page"}},
    )

    assert service.list_kwargs[0]["cursor"] == 10
    assert service.list_kwargs[0]["status"] == "no_match"
