"""Deterministic indexed advisor identity resolution."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.index import AdvisorIndex, IndexedAdvisor
from general_agent.advisor_matching.policy import (
    FIRM_CONFLICT_SIMILARITY,
    FIRM_WILDCARD_MIN_LENGTH,
    MINIMUM_FIRM_SIMILARITY,
    REVIEW_CANDIDATE_LIMIT,
)
from general_agent.advisor_matching.schemas import (
    AdvisorRecord,
    MatchCandidate,
    MatchCounts,
    MatchDecision,
)

NameKind = Literal["exact", "nickname", "conflict", "missing"]
FirmKind = Literal["exact", "wildcard", "close", "conflict", "missing"]


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    """Private policy evidence kept out of persisted/model-facing schemas."""

    advisor: IndexedAdvisor
    candidate: MatchCandidate
    name_kind: NameKind
    firm_kind: FirmKind
    location_match: bool
    state_conflict: bool
    firm_conflict: bool

    @property
    def strong_conflict(self) -> bool:
        return self.state_conflict or self.firm_conflict

    @property
    def independently_supported(self) -> bool:
        return self.firm_kind in {"exact", "wildcard", "close"} or self.location_match


def run_matching(
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
    advisors: AdvisorIndex | Iterable[AdvisorRecord],
) -> tuple[list[MatchDecision], MatchCounts, list[str]]:
    """Resolve rows with one reusable exact index over the authoritative source."""

    index = (
        advisors
        if isinstance(advisors, AdvisorIndex)
        else AdvisorIndex.from_records(advisors)
    )
    signatures = Counter(_duplicate_signature(mapped) for _, _, mapped in rows)
    decisions: list[MatchDecision] = []

    for row_number, source, mapped in rows:
        item_id = "ami_" + hashlib.sha256(
            f"{row_number}:{source}".encode("utf-8")
        ).hexdigest()[:12]
        duplicate = _duplicate_signature(mapped)
        duplicate_group = (
            hashlib.sha256(duplicate.encode("utf-8")).hexdigest()[:8]
            if duplicate and signatures[duplicate] > 1
            else None
        )
        decision = _resolve(item_id, row_number, source, mapped, index)
        decision.duplicate_group = duplicate_group
        decisions.append(decision)

    counts = _counts(decisions)
    duplicate_rows = sum(item.duplicate_group is not None for item in decisions)
    warnings = (
        [f"{duplicate_rows} rows belong to duplicate groups."]
        if duplicate_rows
        else []
    )
    return decisions, counts, warnings


def _resolve(
    item_id: str,
    row_number: int,
    source: dict[str, object],
    mapped: dict[str, str],
    index: AdvisorIndex,
) -> MatchDecision:
    warnings = _input_warnings(mapped)
    raw_crd = str(mapped.get("crd_number") or "").strip()
    input_crd = norm.crd(raw_crd)
    raw_email = str(mapped.get("email") or "").strip()
    input_email = norm.email(raw_email)

    if input_crd and (record := index.crd_record(input_crd)) is not None:
        assessment = _assess(mapped, record)
        warnings.extend(assessment.candidate.conflicting_evidence)
        master_email = norm.email(record.email)
        if input_email and master_email and input_email != master_email:
            warnings.append("Exact CRD matched but email conflicted.")
        return _decision(
            item_id,
            row_number,
            source,
            mapped,
            "Matched",
            "High",
            "EXACT_CRD",
            "Exact CRD matched the authoritative advisor record.",
            assessment.candidate,
            warnings=_unique(warnings),
        )

    email_matches = index.email_records(input_email) if input_email else ()
    if len(email_matches) == 1:
        assessment = _assess(mapped, email_matches[0])
        warnings.extend(assessment.candidate.conflicting_evidence)
        if input_crd and index.crd_record(input_crd) is None:
            warnings.append(
                "Exact email matched; the supplied CRD was not found in the reference."
            )
        return _decision(
            item_id,
            row_number,
            source,
            mapped,
            "Matched",
            "High",
            "UNIQUE_EXACT_EMAIL",
            "Unique normalized email matched the authoritative advisor record.",
            assessment.candidate,
            warnings=_unique(warnings),
        )
    if len(email_matches) > 1:
        assessments = sorted(
            (_assess(mapped, record) for record in email_matches), key=_candidate_order
        )
        return _review_decision(
            item_id,
            row_number,
            source,
            mapped,
            rule_id="NON_UNIQUE_EMAIL",
            explanation=(
                "The normalized email belongs to multiple authoritative advisor "
                "records and requires user review."
            ),
            assessments=assessments,
            warnings=warnings,
        )

    name_key = _input_name_key(mapped)
    if name_key is None:
        return _insufficient_identity_decision(
            item_id,
            row_number,
            source,
            mapped,
            warnings,
            raw_crd,
            input_crd,
            raw_email,
            input_email,
        )

    first, last = name_key
    raw_records = index.name_records(first, last)
    alias_first = norm.NICKNAMES.get(first)
    alias_records = (
        index.name_records(alias_first, last)
        if alias_first and alias_first != first
        else ()
    )
    by_crd: dict[str, CandidateAssessment] = {}
    for record in raw_records:
        by_crd[record.crd_number] = _assess(mapped, record, name_kind="exact")
    for record in alias_records:
        by_crd.setdefault(
            record.crd_number, _assess(mapped, record, name_kind="nickname")
        )

    if not by_crd:
        explanation = "No advisor had the same normalized first and last name."
        rule = "NAME_NOT_FOUND"
        if input_crd and index.crd_record(input_crd) is None:
            explanation = "The supplied CRD and normalized advisor name were not found."
            rule = "CRD_NOT_FOUND"
        elif input_email and not email_matches:
            explanation = "The supplied email and normalized advisor name were not found."
            rule = "EMAIL_NOT_FOUND"
        return _decision(
            item_id,
            row_number,
            source,
            mapped,
            "No Match",
            "None",
            rule,
            explanation,
            warnings=_unique(warnings),
        )

    assessments = sorted(by_crd.values(), key=_candidate_order)
    supported = [
        assessment
        for assessment in assessments
        if assessment.independently_supported and not assessment.strong_conflict
    ]
    if len(supported) == 1 and supported[0].name_kind == "exact":
        selected = supported[0]
        return _decision(
            item_id,
            row_number,
            source,
            mapped,
            "Matched",
            "High",
            "EXACT_NAME_SUPPORTED",
            (
                "Exact normalized first and last name plus independent firm or "
                "city/state evidence identified one advisor."
            ),
            selected.candidate,
            warnings=_unique(warnings),
        )

    has_exact = any(item.name_kind == "exact" for item in assessments)
    return _review_decision(
        item_id,
        row_number,
        source,
        mapped,
        rule_id=(
            "EXACT_NAME_REVIEW_REQUIRED" if has_exact else "NICKNAME_REVIEW_REQUIRED"
        ),
        explanation=(
            "One or more exact-name candidates require user review."
            if has_exact
            else "One or more nickname-derived candidates require user review."
        ),
        assessments=assessments,
        warnings=warnings,
    )


def _review_decision(
    item_id: str,
    row_number: int,
    source: dict[str, object],
    mapped: dict[str, str],
    *,
    rule_id: str,
    explanation: str,
    assessments: list[CandidateAssessment],
    warnings: list[str],
) -> MatchDecision:
    candidates = [item.candidate for item in assessments[:REVIEW_CANDIDATE_LIMIT]]
    return MatchDecision(
        review_item_id=item_id,
        source_row_number=row_number,
        source_values=source,
        mapped_values=mapped,
        status="Ambiguous Match",
        confidence="Uncertain",
        rule_id=rule_id,
        explanation=explanation,
        candidates=candidates,
        candidate_count=len(assessments),
        candidates_truncated=len(assessments) > len(candidates),
        warnings=_unique(warnings),
    )


def _insufficient_identity_decision(
    item_id: str,
    row_number: int,
    source: dict[str, object],
    mapped: dict[str, str],
    warnings: list[str],
    raw_crd: str,
    input_crd: str,
    raw_email: str,
    input_email: str,
) -> MatchDecision:
    raw_name = _raw_name(mapped)
    if raw_name:
        rule = "INSUFFICIENT_NAME"
        explanation = "A usable full name or both first and last name are required."
    elif raw_crd and not input_crd and not raw_email:
        rule = "MALFORMED_CRD"
        explanation = "The supplied CRD is malformed and no other identity field is usable."
    elif raw_email and not input_email and not raw_crd:
        rule = "MALFORMED_EMAIL"
        explanation = "The supplied email is malformed and no other identity field is usable."
    elif input_crd:
        rule = "CRD_NOT_FOUND"
        explanation = "The supplied CRD was not found in the authoritative reference."
    elif input_email:
        rule = "EMAIL_NOT_FOUND"
        explanation = "The supplied email was not found in the authoritative reference."
    else:
        rule = "INSUFFICIENT_EVIDENCE"
        explanation = "A usable advisor name, CRD, or email is required."
    return _decision(
        item_id,
        row_number,
        source,
        mapped,
        "No Match",
        "None",
        rule,
        explanation,
        warnings=_unique(warnings),
    )


def _decision(
    item_id: str,
    row_number: int,
    source: dict[str, object],
    mapped: dict[str, str],
    status: str,
    confidence: str,
    rule: str,
    explanation: str,
    advisor: MatchCandidate | None = None,
    warnings: list[str] | None = None,
) -> MatchDecision:
    return MatchDecision(
        review_item_id=item_id,
        source_row_number=row_number,
        source_values=source,
        mapped_values=mapped,
        status=status,
        confidence=confidence,
        rule_id=rule,
        explanation=explanation,
        matched_advisor=advisor,
        warnings=warnings or [],
    )


def _assess(
    mapped: dict[str, str],
    record: IndexedAdvisor,
    *,
    name_kind: NameKind | None = None,
) -> CandidateAssessment:
    actual_name_kind = name_kind or _name_kind(mapped, record)
    input_firm = norm.firm(mapped.get("firm_name"))
    master_firm = norm.firm(record.firm_name)
    firm_similarity = _firm_ratio(input_firm, master_firm)
    exact_firm = bool(input_firm and master_firm and input_firm == master_firm)
    wildcard_firm = bool(
        input_firm
        and master_firm
        and not exact_firm
        and _firm_wildcard_match(input_firm, master_firm)
    )
    close_firm = bool(
        input_firm
        and master_firm
        and not exact_firm
        and not wildcard_firm
        and firm_similarity >= MINIMUM_FIRM_SIMILARITY
    )
    firm_conflict = bool(
        input_firm
        and master_firm
        and not wildcard_firm
        and firm_similarity < FIRM_CONFLICT_SIMILARITY
    )
    firm_kind: FirmKind = (
        "exact"
        if exact_firm
        else "wildcard"
        if wildcard_firm
        else "close"
        if close_firm
        else "conflict"
        if firm_conflict
        else "missing"
    )

    input_city = norm.city(mapped.get("city"))
    input_state = norm.state(mapped.get("state"))
    master_city = norm.city(record.city)
    master_state = norm.state(record.state)
    complete_location = bool(input_city and input_state)
    location_match = bool(
        complete_location and input_city == master_city and input_state == master_state
    )
    state_conflict = bool(input_state and master_state and input_state != master_state)
    city_conflict = bool(
        complete_location
        and input_state == master_state
        and input_city != master_city
    )

    supporting: list[str] = []
    if actual_name_kind == "exact":
        supporting.append("Exact normalized first and last name")
    elif actual_name_kind == "nickname":
        supporting.append("Curated nickname maps to the authoritative first name")
    if exact_firm:
        supporting.append("Exact normalized firm")
    elif wildcard_firm:
        supporting.append(
            "Anchored firm wildcard matched: "
            f"{mapped.get('firm_name', '')!r} and {record.firm_name!r}"
        )
    elif close_firm:
        supporting.append(
            f"Close firm name: {mapped.get('firm_name', '')!r} and {record.firm_name!r}"
        )
    if location_match:
        supporting.append("Exact city and state")

    conflicting: list[str] = []
    if actual_name_kind == "conflict":
        conflicting.append("Advisor name conflicts")
    if firm_conflict:
        conflicting.append(
            f"Firm conflicts: {mapped.get('firm_name', '')!r} and {record.firm_name!r}"
        )
    if state_conflict:
        conflicting.append(
            f"State conflicts: {mapped.get('state', '')!r} and {record.state!r}"
        )
    elif city_conflict:
        conflicting.append(
            f"City differs within the same state: {mapped.get('city', '')!r} and {record.city!r}"
        )

    contextual: list[str] = []
    input_zip = norm.zip_code(mapped.get("zip_code"))
    master_zip = norm.zip_code(record.zip_code)
    if input_zip and master_zip:
        contextual.append("ZIP matches" if input_zip == master_zip else "ZIP differs")

    candidate = MatchCandidate(
        crd_number=record.crd_number,
        first_name=record.first_name,
        last_name=record.last_name,
        firm_name=record.firm_name,
        email=record.email,
        city=record.city,
        state=record.state,
        zip_code=record.zip_code,
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        contextual_evidence=contextual,
    )
    return CandidateAssessment(
        advisor=record,
        candidate=candidate,
        name_kind=actual_name_kind,
        firm_kind=firm_kind,
        location_match=location_match,
        state_conflict=state_conflict,
        firm_conflict=firm_conflict,
    )


def _candidate_order(item: CandidateAssessment) -> tuple[int | str, ...]:
    firm_order = {"exact": 0, "wildcard": 1, "close": 2, "missing": 3, "conflict": 4}
    return (
        0 if item.name_kind == "exact" else 1,
        0 if not item.strong_conflict else 1,
        0 if item.firm_kind == "exact" else 1,
        0 if item.location_match else 1,
        firm_order[item.firm_kind],
        item.advisor.crd_number,
    )


def _name_kind(mapped: dict[str, str], record: IndexedAdvisor) -> NameKind:
    input_key = _input_name_key(mapped)
    if input_key is None:
        return "missing"
    master_key = (norm.first_name(record.first_name), norm.person_name(record.last_name))
    if input_key == master_key:
        return "exact"
    first, last = input_key
    if norm.NICKNAMES.get(first) == master_key[0] and last == master_key[1]:
        return "nickname"
    return "conflict"


def _input_name_key(mapped: dict[str, str]) -> tuple[str, str] | None:
    raw_full = str(mapped.get("full_name") or "").strip()
    if raw_full.count(",") == 1:
        family, given = raw_full.split(",", 1)
        first = norm.first_name(given)
        last = norm.person_name(family)
        return (first, last) if first and last else None
    if raw_full:
        parts = norm.person_name(raw_full).split()
        return (parts[0], parts[-1]) if len(parts) >= 2 else None

    first = norm.first_name(mapped.get("first_name"))
    last = norm.person_name(mapped.get("last_name"))
    return (first, last) if first and last else None


def _raw_name(mapped: dict[str, str]) -> str:
    return " ".join(
        value
        for value in (
            str(mapped.get("full_name") or "").strip(),
            str(mapped.get("first_name") or "").strip(),
            str(mapped.get("last_name") or "").strip(),
        )
        if value
    )


def _input_warnings(mapped: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    raw_crd = str(mapped.get("crd_number") or "").strip()
    raw_email = str(mapped.get("email") or "").strip()
    if raw_crd and not norm.crd(raw_crd):
        warnings.append("The supplied CRD is malformed.")
    if raw_email and not norm.email(raw_email):
        warnings.append("The supplied email is malformed.")
    if _raw_name(mapped) and _input_name_key(mapped) is None:
        warnings.append("The supplied name is incomplete.")
    return warnings


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0
    return SequenceMatcher(None, left, right).ratio()


def _firm_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0
    direct = _ratio(left, right)
    token_sorted = _ratio(" ".join(sorted(left.split())), " ".join(sorted(right.split())))
    return max(direct, token_sorted)


def _firm_wildcard_match(left: str, right: str) -> bool:
    """Match ``Ed Jones`` as the anchored pattern ``Ed%Jones%``."""

    tokens = left.split()
    if sum(len(token) for token in tokens) < FIRM_WILDCARD_MIN_LENGTH:
        return False
    cursor = 0
    for index, token in enumerate(tokens):
        found = right.find(token, cursor)
        if found < 0 or (index == 0 and found != 0):
            return False
        cursor = found + len(token)
    return True


def _duplicate_signature(mapped: dict[str, str]) -> str:
    name_key = _input_name_key(mapped)
    return "|".join(
        (
            norm.crd(mapped.get("crd_number")),
            norm.email(mapped.get("email")),
            " ".join(name_key) if name_key else "",
            norm.firm(mapped.get("firm_name")),
            norm.city(mapped.get("city")),
            norm.state(mapped.get("state")),
            norm.zip_code(mapped.get("zip_code")),
        )
    )


def _counts(items: list[MatchDecision]) -> MatchCounts:
    return MatchCounts(
        matched=sum(item.status == "Matched" for item in items),
        ambiguous_match=sum(item.status == "Ambiguous Match" for item in items),
        no_match=sum(item.status == "No Match" for item in items),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
