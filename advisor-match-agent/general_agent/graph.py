"""Explicit LangGraph workflow for Advisor Match Agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from general_agent import user_messages
from general_agent.advisor_matching.schemas import (
    ColumnRef,
    FieldBinding,
    InputMapping,
    MappingValidationResult,
    ReviewDecision,
)
from general_agent.advisor_service import AdvisorService, ServiceContext
from general_agent.config import Settings
from general_agent.graph_prompts import (
    MAPPING_CLARIFICATION_PROMPT,
    MAPPING_PROMPT,
    ROUTER_PROMPT,
)
from general_agent.graph_state import AdvisorGraphState, MappingDecision, RouteDecision


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

    async def route(state: AdvisorGraphState) -> dict[str, Any]:
        if state.get("is_new_attachment"):
            # Attachment presence owns the start decision. The router still runs
            # to extract an all-rows firm from the same message.
            decision = await _structured_attempts(
                router_model,
                ROUTER_PROMPT.format(
                    phase="new_attachment",
                    has_attachment=True,
                    has_match=False,
                    message=state.get("user_message", ""),
                ),
                RouteDecision,
            )
            decision.route = "start_match"
        else:
            decision = await _structured_attempts(
                router_model,
                ROUTER_PROMPT.format(
                    phase=state.get("phase", "idle"),
                    has_attachment=bool(state.get("attachment_id")),
                    has_match=bool((state.get("result") or {}).get("match_session_id")),
                    message=state.get("user_message", ""),
                ),
                RouteDecision,
            )
        if state.get("pending_kind") == "manual_crd":
            explicit = _manual_confirmation_route(state.get("user_message", ""))
            if explicit:
                decision.route = explicit
        return {"route": decision.model_dump(mode="json"), "is_new_attachment": False}

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
        return {"profile": profile, "phase": "mapping", "error": None}

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
            "phase": "review",
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "review_page": {},
            "response": user_messages.match_complete(counts),
        }

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

    async def review(state: AdvisorGraphState) -> dict[str, Any]:
        decision = RouteDecision.model_validate(state["route"])
        session_id = decision.match_session_id or (state.get("result") or {}).get(
            "match_session_id"
        )
        if not session_id:
            try:
                current = await asyncio.to_thread(service.current_match, _context(state))
                session_id = current["match_session_id"]
            except KeyError:
                return {"response": user_messages.no_match_session()}
        requested_decisions = list(decision.review_decisions)
        if decision.review_action:
            if decision.source_row_number is None:
                return {
                    "response": (
                        "Tell me which source row you want to update. For example, "
                        "`Choose CRD 12345 for row 12` or `Leave row 12 unmatched`."
                    )
                }
            try:
                page = await asyncio.to_thread(
                    service.list_results,
                    _context(state),
                    session_id,
                    status=None,
                    source_row_number=decision.source_row_number,
                    limit=2,
                )
            except (KeyError, ValueError) as exc:
                return {
                    "response": user_messages.user_fixable_error(ValueError(str(exc)))
                }
            if not page["items"]:
                return {
                    "response": (
                        f"I couldn’t find source row {decision.source_row_number} in "
                        "the current matching results. Ask me to show the review list "
                        "and choose one of the displayed row numbers."
                    )
                }
            item = page["items"][0]
            if decision.review_action == "confirm_candidate" and not decision.crd_number:
                return {
                    "response": (
                        f"Tell me which candidate CRD to use for row "
                        f"{decision.source_row_number}."
                    )
                }
            requested_decisions.append(
                ReviewDecision(
                    review_item_id=item["review_item_id"],
                    action=decision.review_action,
                    crd_number=decision.crd_number,
                )
            )
        if requested_decisions:
            try:
                result = await asyncio.to_thread(
                    service.apply_decisions,
                    _context(state),
                    session_id,
                    requested_decisions,
                    approve_session=False,
                )
            except (KeyError, ValueError) as exc:
                return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
            return {
                "phase": "review",
                "result": result,
                "review_page": {},
                "response": user_messages.decisions_applied(
                    result, len(requested_decisions)
                ),
            }
        cursor = decision.review_cursor
        status_filter = decision.review_status or "ambiguous_match"
        name_query = decision.name_query
        if decision.next_page:
            previous_page = state.get("review_page") or {}
            next_cursor = previous_page.get("next_cursor")
            if next_cursor is None:
                return {
                    "response": (
                        "You’re already at the end of the current review list. You can "
                        "ask to see ambiguous advisors, unmatched advisors, or matching status."
                    )
                }
            cursor = int(next_cursor)
            status_filter = str(previous_page.get("_status_filter") or status_filter)
            name_query = previous_page.get("_name_query") or name_query
        try:
            page = await asyncio.to_thread(
                service.list_results,
                _context(state),
                session_id,
                status=status_filter,
                source_row_number=decision.source_row_number,
                name_query=name_query,
                cursor=cursor,
                limit=decision.review_limit,
            )
        except (KeyError, ValueError) as exc:
            return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
        page = {
            **page,
            "_status_filter": status_filter,
            "_name_query": name_query,
        }
        return {
            "phase": "review",
            "response": user_messages.review_page(page),
            "review_page": page,
            "result": {**(state.get("result") or {}), "match_session_id": session_id},
        }

    async def propose_crd(state: AdvisorGraphState) -> dict[str, Any]:
        decision = RouteDecision.model_validate(state["route"])
        session_id = decision.match_session_id or (state.get("result") or {}).get(
            "match_session_id"
        )
        if not session_id:
            try:
                current = await asyncio.to_thread(service.current_match, _context(state))
                session_id = current["match_session_id"]
            except KeyError:
                return {"response": user_messages.no_match_session()}
        if not decision.crd_number:
            return {
                "response": (
                    "Tell me the exact CRD you want to use and the source row number. "
                    "For example: `Use CRD 12345 for row 12`."
                )
            }
        item: dict[str, Any] | None = None
        if decision.source_row_number is not None:
            try:
                page = await asyncio.to_thread(
                    service.list_results,
                    _context(state),
                    session_id,
                    status=None,
                    source_row_number=decision.source_row_number,
                    limit=2,
                )
            except (KeyError, ValueError) as exc:
                return {
                    "response": user_messages.user_fixable_error(ValueError(str(exc)))
                }
            item = page["items"][0] if page["items"] else None
        elif decision.review_item_id:
            item = {"review_item_id": decision.review_item_id}
        else:
            return {
                "response": (
                    "Tell me which source row should use that CRD. For example: "
                    f"`Use CRD {decision.crd_number} for row 12`."
                )
            }
        if item is None:
            return {
                "response": (
                    f"I couldn’t find source row {decision.source_row_number} in the "
                    "current matching results. Ask me to show the review list first."
                )
            }
        presented = {
            str(candidate.get("crd_number") or "").strip()
            for candidate in item.get("candidates") or []
        }
        if str(decision.crd_number).strip() in presented:
            direct = ReviewDecision(
                review_item_id=item["review_item_id"],
                action="confirm_candidate",
                crd_number=decision.crd_number,
            )
            try:
                applied = await asyncio.to_thread(
                    service.apply_decisions,
                    _context(state),
                    session_id,
                    [direct],
                    approve_session=False,
                )
            except (KeyError, ValueError) as exc:
                return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
            return {
                "phase": "review",
                "result": applied,
                "review_page": {},
                "response": user_messages.decisions_applied(applied, 1),
            }
        try:
            result = await asyncio.to_thread(
                service.propose_crd,
                _context(state),
                session_id,
                item["review_item_id"],
                decision.crd_number,
            )
        except (KeyError, ValueError) as exc:
            return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
        advisor = result["resolved_advisor"]
        row_number = int(
            (result.get("review_item") or {}).get("source_row_number")
            or decision.source_row_number
            or 0
        )
        return {
            "phase": "manual_crd_confirmation",
            "result": {**(state.get("result") or {}), **result},
            "pending_kind": "manual_crd",
            "pending_payload": {
                "proposal_id": result["proposal_id"],
                "match_session_id": session_id,
                "review_item_id": item["review_item_id"],
                "crd_number": advisor["crd_number"],
                "source_row_number": row_number,
            },
            "response": user_messages.manual_crd_proposal(row_number, advisor),
        }

    async def confirm_manual(state: AdvisorGraphState) -> dict[str, Any]:
        pending = state.get("pending_payload") or {}
        if state.get("pending_kind") != "manual_crd" or not pending.get("proposal_id"):
            return {"response": user_messages.no_pending_manual_match()}
        decision = ReviewDecision(
            review_item_id=str(pending["review_item_id"]),
            action="confirm_manual_crd",
            crd_number=str(pending["crd_number"]),
            proposal_id=str(pending["proposal_id"]),
        )
        try:
            result = await asyncio.to_thread(
                service.apply_decisions,
                _context(state),
                str(pending["match_session_id"]),
                [decision],
                approve_session=False,
            )
        except (KeyError, ValueError) as exc:
            return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
        return {
            "phase": "review",
            "result": result,
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "review_page": {},
            "response": user_messages.decisions_applied(result, 1),
        }

    async def cancel_manual(state: AdvisorGraphState) -> dict[str, Any]:
        pending = state.get("pending_payload") or {}
        if state.get("pending_kind") != "manual_crd" or not pending.get("proposal_id"):
            return {"response": user_messages.no_pending_manual_match()}
        try:
            await asyncio.to_thread(
                service.cancel_proposal,
                _context(state),
                str(pending["proposal_id"]),
                str(pending["match_session_id"]),
            )
        except (KeyError, ValueError) as exc:
            return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
        row_number = pending.get("source_row_number")
        return {
            "phase": "review",
            "pending_kind": None,
            "pending_payload": {},
            "response": user_messages.manual_match_cancelled(
                int(row_number) if row_number else None
            ),
        }

    async def approve(state: AdvisorGraphState) -> dict[str, Any]:
        decision = RouteDecision.model_validate(state["route"])
        session_id = decision.match_session_id or (state.get("result") or {}).get(
            "match_session_id"
        )
        if not session_id:
            return {"response": user_messages.no_match_session()}
        try:
            result = await asyncio.to_thread(
                service.apply_decisions,
                _context(state),
                session_id,
                decision.review_decisions,
                approve_session=True,
            )
        except (KeyError, ValueError) as exc:
            return {"response": user_messages.user_fixable_error(ValueError(str(exc)))}
        return {
            "phase": "approved",
            "result": result,
            "response": user_messages.approval_complete(result),
        }

    async def status(state: AdvisorGraphState) -> dict[str, Any]:
        try:
            current = await asyncio.to_thread(service.current_match, _context(state))
        except KeyError:
            return {"response": user_messages.no_match_session()}
        return {
            "result": current,
            "response": user_messages.status_summary(current),
        }

    def reset(_state: AdvisorGraphState) -> dict[str, Any]:
        return {
            "phase": "idle",
            "attachment_id": None,
            "profile": {},
            "mapping": {},
            "validation": {},
            "result": {},
            "pending_kind": None,
            "pending_payload": {},
            "clarification_answer": None,
            "review_page": {},
            "response": user_messages.reset_complete(),
        }

    def capabilities(state: AdvisorGraphState) -> dict[str, Any]:
        return {"response": user_messages.capabilities(bool(state.get("result")))}

    def greeting(_state: AdvisorGraphState) -> dict[str, Any]:
        return {
            "response": (
                "Hi! I can help you match and review financial advisors. "
                "To get started, attach one raw advisor CSV or XLSX file and ask me "
                "to match it. I’ll help interpret the columns, flag ambiguous or "
                "unmatched rows for review, and prepare an auditable workbook."
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
        ("resolve_mapping", resolve_mapping),
        ("validate", validate),
        ("remap_firm", remap_firm),
        ("match", match),
        ("clarify", clarify),
        ("review", review),
        ("propose_crd", propose_crd),
        ("confirm_manual", confirm_manual),
        ("cancel_manual", cancel_manual),
        ("approve", approve),
        ("status", status),
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
    graph.add_conditional_edges("resolve_mapping", _after_mapping)
    graph.add_conditional_edges("validate", _after_validation)
    graph.add_conditional_edges(
        "remap_firm",
        lambda state: "clarify" if state.get("pending_kind") else "match",
    )
    graph.add_conditional_edges(
        "match", lambda state: "clarify" if state.get("pending_kind") else END
    )
    graph.add_conditional_edges("clarify", _after_clarify)
    for terminal in (
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
    return str(route)


def _manual_confirmation_route(
    message: str,
) -> Literal["confirm_manual", "cancel_manual"] | None:
    normalized = " ".join(message.casefold().split()).strip(" .!?")
    if normalized in {
        "yes",
        "confirm",
        "confirm this match",
        "apply this match",
        "approve this match",
    }:
        return "confirm_manual"
    if normalized in {
        "no",
        "cancel",
        "cancel this match",
        "do not apply this match",
        "don't apply this match",
    }:
        return "cancel_manual"
    return None


def _after_inspect(state: AdvisorGraphState) -> str:
    """Stop cleanly when matching was requested without an attachment."""

    return "map_input" if state.get("profile") else END


def _after_mapping(state: AdvisorGraphState) -> str:
    if state.get("error"):
        return END
    return "clarify" if state.get("pending_kind") else "validate"


def _after_clarify(state: AdvisorGraphState) -> str:
    return "resolve_mapping" if state.get("pending_kind") == "mapping" else "route"


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
            "unmatched or require manual review."
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
