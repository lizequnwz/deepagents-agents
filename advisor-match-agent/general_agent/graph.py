"""Explicit LangGraph workflow for Advisor Match Agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from general_agent import user_messages
from general_agent.advisor_matching.schemas import (
    ColumnRef,
    CrdInputMapping,
    CrdInputValidationResult,
    FieldBinding,
    InputMapping,
    MappingValidationResult,
)
from general_agent.advisor_service import AdvisorService, ServiceContext
from general_agent.config import Settings
from general_agent.graph_prompts import (
    CRD_MAPPING_CLARIFICATION_PROMPT,
    CRD_MAPPING_PROMPT,
    MAPPING_CLARIFICATION_PROMPT,
    MAPPING_PROMPT,
    ROUTER_PROMPT,
)
from general_agent.graph_state import (
    AdvisorGraphState,
    CrdMappingDecision,
    MappingDecision,
    RouteDecision,
)


def build_advisor_graph(
    settings: Settings,
    *,
    service: AdvisorService,
    checkpointer: Any | None = None,
    model: BaseChatModel | None = None,
) -> Any:
    """Compile the single explicit workflow with process-local checkpoints."""

    chat_model = model or init_chat_model(
        settings.model_name,
        **_model_init_kwargs(settings),
    )
    router_model = chat_model.with_structured_output(RouteDecision)
    mapping_model = chat_model.with_structured_output(MappingDecision)
    crd_mapping_model = chat_model.with_structured_output(CrdMappingDecision)

    async def route(state: AdvisorGraphState) -> dict[str, Any]:
        requested = state.get("requested_workflow")
        if requested == "profile_report":
            decision = RouteDecision(route="start_profile_report")
        elif requested == "match":
            decision = RouteDecision(route="start_match")
        else:
            decision = await _structured_attempts(
                router_model,
                ROUTER_PROMPT.format(
                    phase=(
                        "new_attachment"
                        if state.get("is_new_attachment")
                        else state.get("phase", "idle")
                    ),
                    has_attachment=bool(state.get("attachment_id")),
                    has_match=bool(
                        state.get("source_match_session_id")
                        or (state.get("result") or {}).get("match_session_id")
                    ),
                    message=state.get("user_message", ""),
                ),
                RouteDecision,
            )
        active_workflow = (
            "profile_report"
            if decision.route == "start_profile_report"
            else "match"
        )
        return {
            "route": decision.model_dump(mode="json"),
            "active_workflow": active_workflow,
            "is_new_attachment": False,
        }

    async def inspect(state: AdvisorGraphState) -> dict[str, Any]:
        attachment_id = state.get("attachment_id")
        if not attachment_id:
            return {
                "phase": "idle",
                "response": user_messages.attachment_required(),
            }
        try:
            profile = await asyncio.to_thread(
                service.inspect, _context(state), attachment_id
            )
        except ValueError as exc:
            return {"phase": "idle", "response": user_messages.user_fixable_error(exc)}
        phase = (
            "profile_mapping"
            if state.get("active_workflow") == "profile_report"
            else "mapping"
        )
        return {"profile": profile, "phase": phase, "error": None}

    async def map_input(state: AdvisorGraphState) -> dict[str, Any]:
        profile = state.get("profile")
        if not profile:
            return {
                "phase": "idle",
                "response": (
                    "I couldn’t inspect the uploaded file. Please attach it again to "
                    "start a fresh match."
                ),
            }
        decision = await _structured_attempts(
            mapping_model,
            MAPPING_PROMPT.format(
                message=state.get("user_message", ""),
                profile=json.dumps(profile, ensure_ascii=False, default=str),
            ),
            MappingDecision,
        )
        return _mapping_decision_update(decision)

    async def map_crd_input(state: AdvisorGraphState) -> dict[str, Any]:
        profile = state.get("profile")
        if not profile:
            return {
                "phase": "idle",
                "response": (
                    "I couldn’t inspect the uploaded file. Please attach it again "
                    "to start a fresh advisor profile report."
                ),
            }
        decision = await _structured_attempts(
            crd_mapping_model,
            CRD_MAPPING_PROMPT.format(
                message=state.get("user_message", ""),
                profile=json.dumps(profile, ensure_ascii=False, default=str),
            ),
            CrdMappingDecision,
        )
        return _crd_mapping_decision_update(decision)

    async def resolve_mapping(state: AdvisorGraphState) -> dict[str, Any]:
        payload = state.get("pending_payload") or {}
        answer = str(state.get("clarification_answer") or "").strip()
        proposed = payload.get("proposed_mapping")
        if proposed and _affirmative(answer):
            mapping = InputMapping.model_validate(proposed)
            return {
                "mapping": mapping.model_dump(mode="json"),
                "phase": "validating",
                "pending_kind": None,
                "pending_payload": {},
                "clarification_answer": None,
                "response": "",
                "error": None,
            }
        profile = state.get("profile")
        if not profile:
            return {
                "phase": "idle",
                "pending_kind": None,
                "pending_payload": {},
                "clarification_answer": None,
                "response": (
                    "I no longer have the bounded file preview needed to interpret "
                    "that answer. Please attach the file again to start a fresh match."
                ),
            }
        decision = await _structured_attempts(
            mapping_model,
            MAPPING_CLARIFICATION_PROMPT.format(
                question=str(payload.get("question") or "Please clarify the mapping."),
                answer=answer or "(no answer provided)",
                proposed_mapping=json.dumps(
                    proposed, ensure_ascii=False, default=str
                )
                if proposed
                else "null",
                profile=json.dumps(profile, ensure_ascii=False, default=str),
            ),
            MappingDecision,
        )
        return _mapping_decision_update(decision)

    async def resolve_crd_mapping(state: AdvisorGraphState) -> dict[str, Any]:
        payload = state.get("pending_payload") or {}
        answer = str(state.get("clarification_answer") or "").strip()
        proposed = payload.get("proposed_mapping")
        if proposed and _affirmative(answer):
            mapping = CrdInputMapping.model_validate(proposed)
            return {
                "mapping": mapping.model_dump(mode="json"),
                "phase": "profile_validating",
                "pending_kind": None,
                "pending_payload": {},
                "clarification_answer": None,
                "response": "",
                "error": None,
            }
        profile = state.get("profile")
        if not profile:
            return {
                "phase": "idle",
                "pending_kind": None,
                "pending_payload": {},
                "clarification_answer": None,
                "response": (
                    "I no longer have the bounded file preview needed to interpret "
                    "that answer. Please attach the file again."
                ),
            }
        decision = await _structured_attempts(
            crd_mapping_model,
            CRD_MAPPING_CLARIFICATION_PROMPT.format(
                question=str(
                    payload.get("question") or "Please clarify the CRD column."
                ),
                answer=answer or "(no answer provided)",
                proposed_mapping=(
                    json.dumps(proposed, ensure_ascii=False, default=str)
                    if proposed
                    else "null"
                ),
                profile=json.dumps(profile, ensure_ascii=False, default=str),
            ),
            CrdMappingDecision,
        )
        return _crd_mapping_decision_update(decision)

    async def validate(state: AdvisorGraphState) -> dict[str, Any]:
        try:
            validation = await asyncio.to_thread(
                service.validate,
                _context(state),
                str(state["attachment_id"]),
                InputMapping.model_validate(state["mapping"]),
            )
        except ValueError as exc:
            return {
                "phase": "mapping",
                "response": user_messages.user_fixable_error(exc),
                "validation": {},
                "error": None,
            }
        return {
            "validation": validation.model_dump(mode="json"),
            "phase": "matching",
            "error": None,
        }

    async def match(state: AdvisorGraphState) -> dict[str, Any]:
        route_value = RouteDecision.model_validate(state.get("route") or {})
        try:
            result = await asyncio.to_thread(
                service.create_match,
                _context(state),
                MappingValidationResult.model_validate(state["validation"]),
                all_rows_firm=route_value.all_rows_firm,
                firm_resolution=route_value.firm_resolution,
            )
        except ValueError as exc:
            return {
                "phase": state.get("phase", "matching"),
                "response": user_messages.user_fixable_error(exc),
            }
        value = result.model_dump(mode="json")
        status = value["workflow_status"]
        if status == "firm_clarification_required":
            return {
                "result": value,
                "phase": "firm_clarification",
                "pending_kind": "firm",
                "pending_payload": value,
            }
        if status == "blocked":
            return {
                "result": value,
                "phase": "blocked",
                "response": value["message"],
            }
        counts = value["counts"]
        return {
            "result": value,
            "phase": "complete",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "response": user_messages.match_complete(counts),
        }

    async def validate_crd_input(state: AdvisorGraphState) -> dict[str, Any]:
        try:
            validation = await asyncio.to_thread(
                service.validate_profile_input,
                _context(state),
                str(state["attachment_id"]),
                CrdInputMapping.model_validate(state["mapping"]),
            )
        except ValueError as exc:
            return {
                "phase": "profile_mapping",
                "response": user_messages.user_fixable_error(exc),
                "profile_report_validation": {},
                "error": None,
            }
        return {
            "profile_report_validation": validation.model_dump(mode="json"),
            "phase": "profile_generating",
            "error": None,
        }

    async def generate_profile_report(
        state: AdvisorGraphState,
    ) -> dict[str, Any]:
        source_match_session_id = state.get("source_match_session_id") or (
            (state.get("result") or {}).get("match_session_id")
        )
        try:
            if source_match_session_id:
                result = await asyncio.to_thread(
                    service.create_profile_report_from_match,
                    _context(state),
                    str(source_match_session_id),
                )
            elif state.get("profile_report_validation"):
                result = await asyncio.to_thread(
                    service.create_profile_report_from_upload,
                    _context(state),
                    CrdInputValidationResult.model_validate(
                        state["profile_report_validation"]
                    ),
                )
            else:
                return {
                    "phase": "idle",
                    "response": user_messages.profile_source_required(),
                }
        except ValueError as exc:
            return {
                "phase": "profile_report",
                "response": user_messages.user_fixable_error(exc),
            }
        value = result.model_dump(mode="json")
        return {
            "profile_report_result": value,
            "phase": "profile_complete",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "response": user_messages.profile_report_complete(value),
        }

    def profile_source_required(_state: AdvisorGraphState) -> dict[str, Any]:
        return {"phase": "idle", "response": user_messages.profile_source_required()}

    async def remap_firm(state: AdvisorGraphState) -> dict[str, Any]:
        validation = MappingValidationResult.model_validate(state["validation"])
        decision = RouteDecision.model_validate(state.get("route") or {})
        requested = decision.firm_column_header or ""
        try:
            mapping = _mapping_with_firm_column(validation, requested)
        except ValueError as exc:
            return {
                "phase": "firm_clarification",
                "pending_kind": "firm",
                "pending_payload": {
                    **(state.get("pending_payload") or {}),
                    "question": str(exc),
                },
            }
        try:
            refreshed = await asyncio.to_thread(
                service.validate,
                _context(state),
                str(state["attachment_id"]),
                mapping,
            )
        except ValueError as exc:
            return {
                "phase": "firm_clarification",
                "pending_kind": "firm",
                "pending_payload": {
                    **(state.get("pending_payload") or {}),
                    "question": user_messages.user_fixable_error(exc),
                },
            }
        return {
            "mapping": mapping.model_dump(mode="json"),
            "validation": refreshed.model_dump(mode="json"),
            "phase": "matching",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "error": None,
        }

    def clarify(state: AdvisorGraphState) -> dict[str, Any]:
        payload = state.get("pending_payload") or {}
        if state.get("pending_kind") == "firm":
            question = str(payload.get("question") or _firm_question(state))
        elif state.get("pending_kind") == "profile_mapping":
            question = str(
                payload.get("question") or "Please clarify which column contains CRDs."
            )
        else:
            question = str(payload.get("question") or "Please clarify the input mapping.")
        answer = interrupt(
            {
                "kind": state.get("pending_kind"),
                "question": question,
                "details": payload,
            }
        )
        if isinstance(answer, dict):
            message = str(answer.get("message") or "")
            return {
                "user_message": message,
                "run_id": str(answer.get("run_id") or state["run_id"]),
                "clarification_answer": message,
                "response": "",
                "is_new_attachment": False,
            }
        return {
            "user_message": str(answer),
            "clarification_answer": str(answer),
            "response": "",
            "is_new_attachment": False,
        }

    def reset(_state: AdvisorGraphState) -> dict[str, Any]:
        return {
            "phase": "idle",
            "attachment_id": None,
            "profile": {},
            "mapping": {},
            "validation": {},
            "result": {},
            "profile_report_validation": {},
            "profile_report_result": {},
            "source_match_session_id": None,
            "requested_workflow": None,
            "active_workflow": "match",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "response": user_messages.reset_complete(),
        }

    def capabilities(state: AdvisorGraphState) -> dict[str, Any]:
        return {"response": user_messages.capabilities(bool(state.get("result")))}

    def greeting(_state: AdvisorGraphState) -> dict[str, Any]:
        return {
            "response": (
                "Hi! I can help you match financial advisors or generate a placeholder "
                "advisor profile report from CRD numbers. "
                "To get started, attach one raw advisor CSV or XLSX file and ask me "
                "to match it or identify its CRD column."
            )
        }

    def unsupported(state: AdvisorGraphState) -> dict[str, Any]:
        return {
            "response": user_messages.unsupported(
                has_match=bool(state.get("result")),
                has_attachment=bool(state.get("attachment_id")),
                pending_kind=state.get("pending_kind"),
            )
        }

    graph = StateGraph(AdvisorGraphState)
    for name, node in (
        ("route", route),
        ("inspect", inspect),
        ("map_input", map_input),
        ("map_crd_input", map_crd_input),
        ("resolve_mapping", resolve_mapping),
        ("resolve_crd_mapping", resolve_crd_mapping),
        ("validate", validate),
        ("validate_crd_input", validate_crd_input),
        ("remap_firm", remap_firm),
        ("match", match),
        ("generate_profile_report", generate_profile_report),
        ("profile_source_required", profile_source_required),
        ("clarify", clarify),
        ("reset", reset),
        ("greeting", greeting),
        ("capabilities", capabilities),
        ("unsupported", unsupported),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", _route_edge)
    graph.add_conditional_edges("inspect", _after_inspect)
    graph.add_conditional_edges("map_input", _after_mapping)
    graph.add_conditional_edges("map_crd_input", _after_crd_mapping)
    graph.add_conditional_edges("resolve_mapping", _after_mapping)
    graph.add_conditional_edges("resolve_crd_mapping", _after_crd_mapping)
    graph.add_conditional_edges("validate", _after_validation)
    graph.add_conditional_edges(
        "validate_crd_input",
        lambda state: (
            "generate_profile_report"
            if state.get("profile_report_validation")
            else END
        ),
    )
    graph.add_conditional_edges(
        "remap_firm",
        lambda state: "clarify" if state.get("pending_kind") else "match",
    )
    graph.add_conditional_edges(
        "match", lambda state: "clarify" if state.get("pending_kind") else END
    )
    graph.add_conditional_edges("clarify", _after_clarify)
    for terminal in (
        "reset",
        "greeting",
        "capabilities",
        "unsupported",
        "profile_source_required",
    ):
        graph.add_edge(terminal, END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


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
                + "\n\nThe previous structured response was invalid. Return a value that "
                + f"strictly satisfies {schema.__name__}."
            )
    raise ValueError(
        f"Could not obtain valid {schema.__name__} after three attempts "
        f"({'; '.join(errors)})."
    )


def _mapping_decision_update(decision: MappingDecision) -> dict[str, Any]:
    if decision.clarification_required or decision.mapping is None:
        kind = decision.clarification_kind or (
            "confirm_mapping" if decision.mapping is not None else "provide_details"
        )
        proposed = (
            decision.mapping.model_dump(mode="json")
            if kind == "confirm_mapping" and decision.mapping is not None
            else None
        )
        question = decision.clarification_question
        if not question:
            question = (
                "Should I use this proposed column mapping?"
                if proposed
                else (
                    "I need one more detail to interpret the file. Which worksheet, "
                    "header row, or column meaning should I use?"
                )
            )
        return {
            "mapping": {},
            "phase": "mapping_clarification",
            "pending_kind": "mapping",
            "pending_payload": {
                "question": question,
                "clarification_kind": kind,
                "proposed_mapping": proposed,
            },
            "clarification_answer": None,
            "response": "",
            "error": None,
        }
    return {
        "mapping": decision.mapping.model_dump(mode="json"),
        "pending_kind": None,
        "pending_payload": {},
        "clarification_answer": None,
        "phase": "validating",
        "response": "",
        "error": None,
    }


def _crd_mapping_decision_update(
    decision: CrdMappingDecision,
) -> dict[str, Any]:
    if decision.missing_crd_column:
        return {
            "mapping": {},
            "phase": "idle",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "response": user_messages.missing_crd_column(),
            "error": None,
        }
    if decision.clarification_required or decision.mapping is None:
        kind = decision.clarification_kind or (
            "confirm_mapping" if decision.mapping is not None else "provide_details"
        )
        proposed = (
            decision.mapping.model_dump(mode="json")
            if kind == "confirm_mapping" and decision.mapping is not None
            else None
        )
        question = decision.clarification_question or (
            "Should I use this proposed CRD column?"
            if proposed
            else "Which worksheet, header row, and displayed column contains CRDs?"
        )
        return {
            "mapping": {},
            "phase": "profile_mapping_clarification",
            "pending_kind": "profile_mapping",
            "pending_payload": {
                "question": question,
                "clarification_kind": kind,
                "proposed_mapping": proposed,
            },
            "clarification_answer": None,
            "response": "",
            "error": None,
        }
    return {
        "mapping": decision.mapping.model_dump(mode="json"),
        "pending_kind": None,
        "pending_payload": {},
        "clarification_answer": None,
        "phase": "profile_validating",
        "response": "",
        "error": None,
    }


def _route_edge(state: AdvisorGraphState) -> str:
    route = (state.get("route") or {}).get("route", "unsupported")
    if route == "start_match":
        if state.get("validation") and state.get("pending_kind") == "firm":
            if (state.get("route") or {}).get("firm_column_header"):
                return "remap_firm"
            return "match"
        if state.get("profile") and state.get("pending_kind") == "mapping":
            return "map_input"
        return "inspect"
    if route == "start_profile_report":
        if state.get("source_match_session_id") or (
            state.get("result") or {}
        ).get("match_session_id"):
            return "generate_profile_report"
        if state.get("profile_report_validation"):
            return "generate_profile_report"
        if state.get("attachment_id"):
            if state.get("profile") and state.get("pending_kind") == "profile_mapping":
                return "map_crd_input"
            return "inspect"
        return "profile_source_required"
    return str(route)


def _after_inspect(state: AdvisorGraphState) -> str:
    """Stop cleanly when matching was requested without an attachment."""

    if not state.get("profile"):
        return END
    return (
        "map_crd_input"
        if state.get("active_workflow") == "profile_report"
        else "map_input"
    )


def _after_mapping(state: AdvisorGraphState) -> str:
    if state.get("error"):
        return END
    return "clarify" if state.get("pending_kind") else "validate"


def _after_crd_mapping(state: AdvisorGraphState) -> str:
    if state.get("error"):
        return END
    if not state.get("mapping") and not state.get("pending_kind"):
        return END
    return "clarify" if state.get("pending_kind") else "validate_crd_input"


def _after_clarify(state: AdvisorGraphState) -> str:
    if state.get("pending_kind") == "mapping":
        return "resolve_mapping"
    if state.get("pending_kind") == "profile_mapping":
        return "resolve_crd_mapping"
    return "route"


def _after_validation(state: AdvisorGraphState) -> str:
    return "match" if state.get("validation") else END


def _affirmative(message: str) -> bool:
    normalized = " ".join(message.casefold().split()).strip(" .!?")
    return normalized in {
        "yes",
        "y",
        "yes please",
        "correct",
        "that's correct",
        "that is correct",
        "use it",
        "use that",
        "use that mapping",
        "confirm",
    }


def _context(state: AdvisorGraphState) -> ServiceContext:
    return ServiceContext(
        corp_id=state["corp_id"],
        conversation_id=state["conversation_id"],
        run_id=state["run_id"],
        user_message=state.get("user_message", ""),
    )


def _firm_question(state: AdvisorGraphState) -> str:
    payload = state.get("pending_payload") or {}
    validation = state.get("validation") or {}
    summary = validation.get("input_summary") or {}
    reason = payload.get("reason")
    affected = int(summary.get("missing_firm_row_count") or 0)
    total = int(payload.get("data_row_count") or summary.get("data_row_count") or 0)
    firm_label = _mapped_firm_label(validation)

    if reason == "missing_firm":
        if summary.get("firm_column_missing"):
            opening = "I couldn’t identify a firm column in the uploaded file."
        elif firm_label:
            opening = (
                f"I found the firm column “{firm_label}”, but it has no usable value "
                f"for {_row_count(affected or total)}."
            )
        else:
            opening = (
                f"I couldn’t find a usable firm value for {_row_count(affected or total)}."
            )
        return (
            f"{opening}\n\n"
            f"For {_row_count(affected or total)}, the file also does not provide a CRD "
            "number or valid email. The matcher cannot confidently confirm an advisor "
            "from a name alone; exact city and state can help when they are available.\n\n"
            "- If the file already contains firm information under another column, tell "
            "me the exact column name, for example: `Use Employer as the firm column`.\n"
            "- If every advisor belongs to the same firm, tell me the exact firm name, "
            "for example: `Use ABC Wealth for all advisors`.\n"
            "- I can continue without firm information, but affected rows may remain "
            "unmatched and appear on the Review Required sheet."
        )

    sample = ", ".join(str(item) for item in payload.get("source_firm_sample") or [])
    stated = str(payload.get("stated_firm") or "").strip()
    if reason == "mixed_source_firms":
        opening = "The uploaded firm column contains more than one firm"
    elif reason == "blank_source_firms":
        opening = "Some rows in the uploaded firm column are blank"
    else:
        opening = "The firm you provided does not match the populated firm values"
    details = f" (examples: {sample})" if sample else ""
    target = f" “{stated}”" if stated else " the firm you provided"
    return (
        f"{opening}{details}, so I need your confirmation before changing the data.\n\n"
        f"Tell me either `Keep the firms from the file` or `Use{target} for all advisors`. "
        "Applying one firm to every row will be recorded as an audited override."
    )


def _firm_column_binding(
    validation: MappingValidationResult, requested: str
) -> FieldBinding:
    needle = _column_key(requested)
    if not needle:
        raise ValueError("Tell me the exact name of the column that contains firm values.")
    matches: dict[int, dict[str, Any]] = {}
    for column in validation.columns:
        candidates = (column.get("header"), column.get("label"))
        if any(_column_key(value) == needle for value in candidates):
            matches[int(column["index"])] = column
    if not matches:
        available = ", ".join(
            f"“{column.get('label')}”" for column in validation.columns[:10]
        )
        suffix = f" Available columns are: {available}." if available else ""
        raise ValueError(
            f"I couldn’t find a column named “{requested.strip()}”.{suffix} "
            "Please provide one exact column name."
        )
    if len(matches) > 1:
        labels = ", ".join(f"“{item.get('label')}”" for item in matches.values())
        raise ValueError(
            f"More than one column matches “{requested.strip()}”: {labels}. "
            "Please use the exact displayed column label."
        )
    column = next(iter(matches.values()))
    header = column.get("header") if validation.mapping.header_row is not None else None
    return FieldBinding(
        columns=[ColumnRef(index=int(column["index"]), header=header)]
    )


def _mapping_with_firm_column(
    validation: MappingValidationResult, requested: str
) -> InputMapping:
    firm_binding = _firm_column_binding(validation, requested)
    return InputMapping.model_validate(
        {
            **validation.mapping.model_dump(mode="json"),
            "firm_name": firm_binding.model_dump(mode="json"),
        }
    )


def _mapped_firm_label(validation: dict[str, Any]) -> str | None:
    binding = (validation.get("mapping") or {}).get("firm_name") or {}
    references = binding.get("columns") or []
    if not references:
        return None
    index = references[0].get("index")
    for column in validation.get("columns") or []:
        if column.get("index") == index:
            return str(column.get("label") or column.get("header") or "").strip() or None
    return None


def _column_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _row_count(value: int) -> str:
    count = max(1, value)
    return f"{count} advisor row" + ("" if count == 1 else "s")


def _model_init_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs = dict(settings.model_kwargs)
    kwargs.setdefault("streaming", False)
    return kwargs
