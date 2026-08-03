"""Deterministic exact, corroborated fuzzy, and ambiguity resolution."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.policy import (
    ACCEPTANCE_SCORE,
    FIRM_CONFLICT_SIMILARITY,
    FIRM_WILDCARD_MIN_LENGTH,
    MINIMUM_FIRM_SIMILARITY,
    MINIMUM_MARGIN,
    MINIMUM_NAME_SIMILARITY,
    PLAUSIBLE_SCORE,
    REVIEW_CANDIDATE_LIMIT,
    WEIGHTS,
)
from general_agent.advisor_matching.schemas import (
    AdvisorRecord,
    MatchCandidate,
    MatchCounts,
    MatchDecision,
)


def run_matching(
    rows: list[tuple[int, dict[str, object], dict[str, str]]],
    advisors: list[AdvisorRecord],
) -> tuple[list[MatchDecision], MatchCounts, list[str]]:
    by_crd = {norm.crd(record.crd_number): record for record in advisors}
    by_email: dict[str, list[AdvisorRecord]] = defaultdict(list)
    signatures = Counter(_duplicate_signature(mapped) for _, _, mapped in rows)
    for record in advisors:
        if normalized_email := norm.email(record.email):
            by_email[normalized_email].append(record)

    decisions = []
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
        decision = _resolve(
            item_id, row_number, source, mapped, advisors, by_crd, by_email
        )
        decision.duplicate_group = duplicate_group
        decisions.append(decision)

    counts = MatchCounts(
        matched=sum(item.status == "Matched" for item in decisions),
        ambiguous_match=sum(
            item.status == "Ambiguous Match" for item in decisions
        ),
        no_match=sum(item.status == "No Match" for item in decisions),
    )
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
    advisors: list[AdvisorRecord],
    by_crd: dict[str, AdvisorRecord],
    by_email: dict[str, list[AdvisorRecord]],
) -> MatchDecision:
    warnings = _input_warnings(mapped)
    raw_crd = str(mapped.get("crd_number") or "").strip()
    input_crd = norm.crd(raw_crd)
    raw_email = str(mapped.get("email") or "").strip()
    input_email = norm.email(raw_email)

    if input_crd and input_crd in by_crd:
        candidate = _candidate(mapped, by_crd[input_crd])
        warnings.extend(candidate.conflicting_evidence)
        master_email = norm.email(candidate.email)
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
            candidate,
            warnings=_unique(warnings),
        )

    email_matches = by_email.get(input_email, []) if input_email else []
    if len(email_matches) == 1:
        candidate = _candidate(mapped, email_matches[0])
        warnings.extend(candidate.conflicting_evidence)
        if input_crd and input_crd not in by_crd:
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
            candidate,
            warnings=_unique(warnings),
        )
    if len(email_matches) > 1:
        candidates = sorted(
            (_candidate(mapped, record) for record in email_matches),
            key=lambda item: (-item.internal_score, item.crd_number),
        )[:REVIEW_CANDIDATE_LIMIT]
        return MatchDecision(
            review_item_id=item_id,
            source_row_number=row_number,
            source_values=source,
            mapped_values=mapped,
            status="Ambiguous Match",
            confidence="Uncertain",
            rule_id="NON_UNIQUE_EMAIL",
            explanation=(
                "The normalized email belongs to multiple authoritative advisor "
                "records and requires user review."
            ),
            candidates=candidates,
            warnings=_unique(warnings),
        )

    input_name = _input_name(mapped)
    if not input_name:
        return _insufficient_identity_decision(
            item_id, row_number, source, mapped, warnings, raw_crd, input_crd,
            raw_email, input_email,
        )

    ranked = sorted(
        (_candidate(mapped, record) for record in advisors),
        key=lambda item: (-item.internal_score, item.crd_number),
    )
    exact_supported = [
        candidate
        for candidate in ranked
        if candidate.internal_name_similarity == 1
        and _has_exact_name_support(candidate)
        and not _strong_conflict(candidate)
    ]
    if len(exact_supported) == 1:
        return _decision(
            item_id,
            row_number,
            source,
            mapped,
            "Matched",
            "High",
            "EXACT_NAME_SUPPORTED",
            (
                "Exact normalized name and independent firm or city/state "
                "evidence identified one advisor."
            ),
            exact_supported[0],
            warnings=_unique(warnings),
        )

    plausible = [
        candidate
        for candidate in ranked
        if candidate.internal_score >= PLAUSIBLE_SCORE
        and max(
            candidate.internal_name_similarity,
            candidate.internal_alias_name_similarity,
        )
        >= MINIMUM_NAME_SIMILARITY
    ]
    if plausible:
        top = plausible[0]
        margin = top.internal_score - (
            plausible[1].internal_score if len(plausible) > 1 else 0
        )
        uses_nickname = (
            top.internal_alias_name_similarity > top.internal_name_similarity
        )
        if (
            top.internal_score >= ACCEPTANCE_SCORE
            and margin >= MINIMUM_MARGIN
            and _has_fuzzy_name_support(top)
            and not _strong_conflict(top)
            and not uses_nickname
        ):
            return _decision(
                item_id,
                row_number,
                source,
                mapped,
                "Matched",
                "High",
                "FUZZY_NAME_CORROBORATED",
                (
                    "Strong name similarity plus independent firm or city/state "
                    "evidence identified one advisor."
                ),
                top,
                warnings=_unique(warnings),
            )
        return MatchDecision(
            review_item_id=item_id,
            source_row_number=row_number,
            source_values=source,
            mapped_values=mapped,
            status="Ambiguous Match",
            confidence="Uncertain",
            rule_id="AMBIGUOUS_CANDIDATES",
            explanation="One or more plausible candidates require user review.",
            candidates=plausible[:REVIEW_CANDIDATE_LIMIT],
            warnings=_unique(warnings),
        )

    rule = "NO_ACCEPTABLE_CANDIDATE"
    explanation = "No advisor satisfied the accepted identity rules."
    if input_crd and input_crd not in by_crd:
        rule = "CRD_NOT_FOUND"
        explanation = "The supplied CRD was not found in the authoritative reference."
    elif input_email and not email_matches:
        rule = "EMAIL_NOT_FOUND"
        explanation = "The supplied email was not found in the authoritative reference."
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


def _insufficient_identity_decision(
    item_id,
    row_number,
    source,
    mapped,
    warnings,
    raw_crd,
    input_crd,
    raw_email,
    input_email,
) -> MatchDecision:
    raw_name = _raw_name(mapped)
    if raw_name:
        rule = "INSUFFICIENT_NAME"
        explanation = (
            "A usable full name or both first and last name are required."
        )
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
        item_id, row_number, source, mapped, "No Match", "None", rule,
        explanation, warnings=_unique(warnings),
    )


def _decision(
    item_id,
    row_number,
    source,
    mapped,
    status,
    confidence,
    rule,
    explanation,
    advisor=None,
    warnings=None,
):
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


def _candidate(mapped: dict[str, str], record: AdvisorRecord) -> MatchCandidate:
    input_name = _input_name(mapped)
    alias_name = _input_name(mapped, aliases=True)
    master_name = norm.person_name(f"{record.first_name} {record.last_name}")
    name_similarity = _ratio(input_name, master_name)
    alias_similarity = _ratio(alias_name, master_name)

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
        and (wildcard_firm or firm_similarity >= MINIMUM_FIRM_SIMILARITY)
    )
    firm_conflict = bool(
        input_firm
        and master_firm
        and not wildcard_firm
        and firm_similarity < FIRM_CONFLICT_SIMILARITY
    )

    input_city = norm.city(mapped.get("city"))
    input_state = norm.state(mapped.get("state"))
    master_city = norm.city(record.city)
    master_state = norm.state(record.state)
    complete_location = bool(input_city and input_state)
    location_match = bool(
        complete_location
        and input_city == master_city
        and input_state == master_state
    )
    state_conflict = bool(input_state and master_state and input_state != master_state)
    city_conflict = bool(
        complete_location
        and input_state == master_state
        and input_city != master_city
    )

    supporting = []
    if name_similarity == 1:
        supporting.append("Exact normalized name")
    elif alias_similarity > name_similarity and alias_similarity >= MINIMUM_NAME_SIMILARITY:
        supporting.append("Nickname alias is a plausible name candidate")
    elif name_similarity >= MINIMUM_NAME_SIMILARITY:
        supporting.append("Close advisor name")
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

    conflicting = []
    if input_name and name_similarity < 0.45 and alias_similarity < 0.45:
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

    contextual = []
    input_zip = norm.zip_code(mapped.get("zip_code"))
    master_zip = norm.zip_code(record.zip_code)
    if input_zip and master_zip:
        contextual.append("ZIP matches" if input_zip == master_zip else "ZIP differs")

    present_scores: dict[str, float] = {}
    if input_name:
        present_scores["name"] = max(name_similarity, alias_similarity)
    if input_firm:
        present_scores["firm"] = firm_similarity
    if complete_location:
        present_scores["city"] = _ratio(input_city, master_city)
        present_scores["state"] = 1.0 if input_state == master_state else 0.0
    denominator = sum(WEIGHTS[field] for field in present_scores) or 1
    score = sum(
        WEIGHTS[field] * value for field, value in present_scores.items()
    ) / denominator
    return MatchCandidate(
        **record.model_dump(),
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        contextual_evidence=contextual,
        internal_score=score,
        internal_name_similarity=name_similarity,
        internal_alias_name_similarity=alias_similarity,
        internal_firm_similarity=firm_similarity,
        internal_exact_firm=exact_firm,
        internal_close_firm=close_firm,
        internal_location_match=location_match,
        internal_state_conflict=state_conflict,
        internal_firm_conflict=firm_conflict,
    )


def _input_name(mapped: dict[str, str], *, aliases: bool = False) -> str:
    raw_full = str(mapped.get("full_name") or "").strip()
    if raw_full.count(",") == 1:
        family, given = raw_full.split(",", 1)
        full = norm.person_name(f"{given} {family}")
    else:
        full = norm.person_name(raw_full)
    if len(full.split()) < 2:
        first = norm.first_name(mapped.get("first_name"), aliases=aliases)
        last = norm.person_name(mapped.get("last_name"))
        full = f"{first} {last}".strip() if first and last else ""
    elif aliases:
        first, *remaining = full.split()
        full = " ".join((norm.NICKNAMES.get(first, first), *remaining))
    return full


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


def _has_exact_name_support(candidate: MatchCandidate) -> bool:
    return bool(
        candidate.internal_exact_firm
        or candidate.internal_close_firm
        or candidate.internal_location_match
    )


def _has_fuzzy_name_support(candidate: MatchCandidate) -> bool:
    if candidate.internal_exact_firm:
        return True
    if candidate.internal_close_firm:
        return candidate.internal_location_match
    return candidate.internal_location_match


def _strong_conflict(candidate: MatchCandidate) -> bool:
    return candidate.internal_firm_conflict or candidate.internal_state_conflict


def _input_warnings(mapped: dict[str, str]) -> list[str]:
    warnings = []
    raw_crd = str(mapped.get("crd_number") or "").strip()
    raw_email = str(mapped.get("email") or "").strip()
    if raw_crd and not norm.crd(raw_crd):
        warnings.append("The supplied CRD is malformed.")
    if raw_email and not norm.email(raw_email):
        warnings.append("The supplied email is malformed.")
    if _raw_name(mapped) and not _input_name(mapped):
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
    return "|".join(
        (
            norm.crd(mapped.get("crd_number")),
            norm.email(mapped.get("email")),
            _input_name(mapped),
            norm.firm(mapped.get("firm_name")),
            norm.city(mapped.get("city")),
            norm.state(mapped.get("state")),
            norm.zip_code(mapped.get("zip_code")),
        )
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
