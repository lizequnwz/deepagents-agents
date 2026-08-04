from __future__ import annotations

import pytest

from langgraph.graph import END
from langgraph.types import Command

from general_agent import user_messages
from general_agent.advisor_matching.schemas import (
    ColumnRef,
    CrdInputMapping,
    CrdInputValidationResult,
    FieldBinding,
    InputMapping,
    InputSummary,
    MappingValidationResult,
    ProfileReportResult,
)
from general_agent.graph import (
    _after_inspect,
    _firm_question,
    _mapping_with_firm_column,
    _route_edge,
    _structured_attempts,
    build_advisor_graph,
)
from general_agent.graph_state import CrdMappingDecision, MappingDecision, RouteDecision


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


class ProfileRequestModel:
    def __init__(self, decisions: list[CrdMappingDecision] | None = None) -> None:
        self.route_calls = 0
        self.crd_mapping_calls = 0
        self.decisions = iter(decisions) if decisions is not None else None

    def with_structured_output(self, schema):
        outer = self

        class Output:
            async def ainvoke(_self, _prompt):
                if schema is RouteDecision:
                    outer.route_calls += 1
                    return RouteDecision(route="start_profile_report")
                if schema is CrdMappingDecision:
                    outer.crd_mapping_calls += 1
                    if outer.decisions is not None:
                        return next(outer.decisions)
                    return CrdMappingDecision(
                        mapping=CrdInputMapping(
                            crd_number=FieldBinding(
                                columns=[ColumnRef(index=0, header="CRD")]
                            )
                        )
                    )
                raise AssertionError(f"Unexpected schema invocation: {schema}")

        return Output()


class ProfileWorkflowService:
    def __init__(self) -> None:
        self.report_sources: list[str] = []

    def inspect(self, _context, attachment_id):
        return {
            "attachment_id": attachment_id,
            "format": "csv",
            "sheets": [
                {
                    "name": None,
                    "header_candidates": [
                        {
                            "row_number": 1,
                            "columns": [
                                {"index": 0, "header": "CRD", "label": "CRD"}
                            ],
                        }
                    ],
                }
            ],
        }

    def validate_profile_input(self, _context, attachment_id, mapping):
        return CrdInputValidationResult(
            attachment_id=attachment_id,
            source_sha256="a" * 64,
            selected_sheet=None,
            mapping=mapping,
            mapping_fingerprint="profile-fingerprint",
            columns=[{"index": 0, "header": "CRD", "label": "CRD"}],
            data_row_count=2,
            usable_crd_count=2,
            unique_crd_count=2,
            blank_crd_count=0,
            duplicate_crd_count=0,
        )

    def create_profile_report_from_upload(self, _context, validation):
        self.report_sources.append(validation.attachment_id)
        return ProfileReportResult(
            profile_report_id="apr_test",
            output_artifact_id="art_profile",
            source_kind="attachment",
            source_attachment_id=validation.attachment_id,
            input_crd_count=2,
            unique_crd_count=2,
            blank_crd_count=0,
            duplicate_crd_count=0,
        )

    def create_profile_report_from_match(self, _context, match_session_id):
        self.report_sources.append(match_session_id)
        return ProfileReportResult(
            profile_report_id="apr_test",
            output_artifact_id="art_profile",
            source_kind="match_session",
            source_match_session_id=match_session_id,
            input_crd_count=2,
            unique_crd_count=2,
            blank_crd_count=0,
            duplicate_crd_count=0,
        )


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
async def test_explicit_profile_upload_bypasses_router_and_generates_report(
    settings,
) -> None:
    model = ProfileRequestModel()
    service = ProfileWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)

    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Generate the profile report",
            "attachment_id": "att_profile",
            "is_new_attachment": True,
            "requested_workflow": "profile_report",
            "phase": "idle",
        },
        config={"configurable": {"thread_id": "profile-upload"}},
    )

    assert model.route_calls == 0
    assert model.crd_mapping_calls == 1
    assert service.report_sources == ["att_profile"]
    assert result["phase"] == "profile_complete"
    assert result["profile_report_result"]["unique_crd_count"] == 2


@pytest.mark.asyncio
async def test_natural_language_profile_upload_uses_typed_router(settings) -> None:
    model = ProfileRequestModel()
    service = ProfileWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)

    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-natural-profile",
            "user_message": "Generate advisor profile reports",
            "attachment_id": "att_profile",
            "is_new_attachment": True,
            "phase": "idle",
        },
        config={"configurable": {"thread_id": "natural-profile-upload"}},
    )

    assert model.route_calls == 1
    assert service.report_sources == ["att_profile"]
    assert result["phase"] == "profile_complete"


@pytest.mark.asyncio
async def test_missing_crd_column_stops_without_generation(settings) -> None:
    model = ProfileRequestModel(
        [CrdMappingDecision(missing_crd_column=True)]
    )
    service = ProfileWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)

    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-missing-crd",
            "user_message": "Generate the profile report",
            "attachment_id": "att_profile",
            "is_new_attachment": True,
            "requested_workflow": "profile_report",
            "phase": "idle",
        },
        config={"configurable": {"thread_id": "missing-profile-column"}},
    )

    assert "requires one column containing CRD identifiers" in result["response"]
    assert service.report_sources == []
    assert not result.get("profile_report_result")


@pytest.mark.asyncio
async def test_profile_mapping_ambiguity_interrupts_and_yes_resumes(settings) -> None:
    proposed = CrdInputMapping(
        crd_number=FieldBinding(columns=[ColumnRef(index=0, header="CRD")])
    )
    model = ProfileRequestModel(
        [
            CrdMappingDecision(
                mapping=proposed,
                clarification_required=True,
                clarification_kind="confirm_mapping",
                clarification_question="Should I use the CRD column?",
            )
        ]
    )
    service = ProfileWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)
    config = {"configurable": {"thread_id": "profile-mapping-confirmation"}}

    interrupted = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-profile-one",
            "user_message": "Generate the profile report",
            "attachment_id": "att_profile",
            "is_new_attachment": True,
            "requested_workflow": "profile_report",
            "phase": "idle",
        },
        config=config,
    )
    assert interrupted["__interrupt__"]
    assert interrupted["pending_kind"] == "profile_mapping"

    result = await graph.ainvoke(
        Command(resume={"message": "Yes", "run_id": "run-profile-two"}),
        config=config,
    )
    assert result["phase"] == "profile_complete"
    assert service.report_sources == ["att_profile"]


@pytest.mark.asyncio
async def test_explicit_post_match_profile_uses_supplied_session_without_upload(
    settings,
) -> None:
    model = ProfileRequestModel()
    service = ProfileWorkflowService()
    graph = build_advisor_graph(settings, service=service, model=model)

    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-two",
            "user_message": "Generate the profile report",
            "is_new_attachment": False,
            "requested_workflow": "profile_report",
            "source_match_session_id": "ams_test",
            "phase": "complete",
        },
        config={"configurable": {"thread_id": "profile-match"}},
    )

    assert model.route_calls == 0
    assert model.crd_mapping_calls == 0
    assert service.report_sources == ["ams_test"]
    assert result["profile_report_result"]["source_kind"] == "match_session"


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

    assert result["phase"] == "complete"
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

    assert result["phase"] == "complete"
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


def test_match_completion_is_actionable_and_hides_artifact_ids() -> None:
    response = user_messages.match_complete(
        {"matched": 84, "ambiguous_match": 11, "no_match": 5}
    )

    assert "100 advisors" in response
    assert "Review Required" in response
    assert "User Decision" in response
    assert "Selected CRD" in response
    assert "not sent back to or validated" in response
    assert "artifact" not in response.casefold()


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


@pytest.mark.asyncio
async def test_post_match_review_request_explains_workbook_boundary(settings) -> None:
    graph = build_advisor_graph(
        settings,
        service=object(),
        model=FixedRouteModel(RouteDecision(route="capabilities")),
    )
    result = await graph.ainvoke(
        {
            "corp_id": "A123456",
            "conversation_id": "conversation-one",
            "run_id": "run-one",
            "user_message": "Use CRD 12345 for John Smith",
            "phase": "complete",
            "result": {"match_session_id": "ams_internal"},
        },
        config={"configurable": {"thread_id": "review-command"}},
    )

    assert "workbook" in result["response"].casefold()
    assert "does not apply row-level review choices" in result["response"]
    assert "validate changes made to the downloaded workbook" in result["response"]
