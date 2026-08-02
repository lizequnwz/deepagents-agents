"""Deterministic exact, corroborated fuzzy, and ambiguity resolution."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.policy import ACCEPTANCE_SCORE, MINIMUM_MARGIN, MINIMUM_NAME_SIMILARITY, PLAUSIBLE_SCORE, POLICY_VERSION, REVIEW_CANDIDATE_LIMIT, WEIGHTS
from general_agent.advisor_matching.schemas import AdvisorRecord, MatchCandidate, MatchCounts, MatchDecision


def run_matching(rows: list[tuple[int, dict[str, object], dict[str, str]]], advisors: list[AdvisorRecord]) -> tuple[list[MatchDecision], MatchCounts, list[str]]:
    by_crd = {record.crd_number: record for record in advisors}
    by_email: dict[str, list[AdvisorRecord]] = defaultdict(list)
    signatures = Counter(_duplicate_signature(mapped) for _, _, mapped in rows)
    for record in advisors:
        if norm.email(record.email):
            by_email[norm.email(record.email)].append(record)
    decisions = []
    for row_number, source, mapped in rows:
        item_id = "ami_" + hashlib.sha256(f"{row_number}:{source}".encode()).hexdigest()[:12]
        duplicate = _duplicate_signature(mapped)
        duplicate_group = hashlib.sha256(duplicate.encode()).hexdigest()[:8] if duplicate and signatures[duplicate] > 1 else None
        decision = _resolve(item_id, row_number, source, mapped, advisors, by_crd, by_email)
        decision.duplicate_group = duplicate_group
        decisions.append(decision)
    counts = MatchCounts(
        matched=sum(item.status == "Matched" for item in decisions),
        ambiguous_match=sum(item.status == "Ambiguous Match" for item in decisions),
        no_match=sum(item.status == "No Match" for item in decisions),
    )
    warnings = [f"{sum(item.duplicate_group is not None for item in decisions)} rows belong to duplicate groups."] if any(item.duplicate_group for item in decisions) else []
    return decisions, counts, warnings


def _resolve(item_id, row_number, source, mapped, advisors, by_crd, by_email) -> MatchDecision:
    raw_crd = str(mapped.get("crd_number") or "").strip()
    input_crd = norm.crd(mapped.get("crd_number"))
    if input_crd and input_crd in by_crd:
        candidate = _candidate(mapped, by_crd[input_crd])
        warnings = [f"Exact CRD matched but {field} conflicted." for field in candidate.conflicting_fields]
        master_email = norm.email(candidate.email)
        input_email = norm.email(mapped.get("email"))
        if input_email and master_email and input_email != master_email:
            warnings.append("Exact CRD matched but email conflicted.")
        return _decision(item_id, row_number, source, mapped, "Matched", "High", "EXACT_CRD", "Exact CRD matched the authoritative advisor record.", candidate, warnings=warnings)
    raw_email = str(mapped.get("email") or "").strip()
    input_email = norm.email(mapped.get("email"))
    email_matches = by_email.get(input_email, []) if input_email else []
    if len(email_matches) == 1:
        candidate = _candidate(mapped, email_matches[0])
        warnings = [f"Exact email matched but {field} conflicted." for field in candidate.conflicting_fields]
        if raw_crd and not input_crd:
            warnings.append("Exact email matched; the supplied CRD was malformed.")
        elif input_crd and input_crd not in by_crd:
            warnings.append("Exact email matched; the supplied CRD was not found in the reference.")
        return _decision(item_id, row_number, source, mapped, "Matched", "High", "UNIQUE_EXACT_EMAIL", "Unique normalized email matched the authoritative advisor record.", candidate, warnings=warnings)
    input_name = _input_name(mapped)
    if not input_name and raw_crd and not input_crd and not raw_email:
        return _decision(item_id, row_number, source, mapped, "No Match", "None", "MALFORMED_CRD", "The supplied CRD is malformed and no other identity field is usable.")
    if not input_name and input_crd and input_crd not in by_crd and not raw_email:
        return _decision(item_id, row_number, source, mapped, "No Match", "None", "CRD_NOT_FOUND", "The supplied CRD was not found and no other identity field is usable.")
    if not input_name and raw_email and not input_email and not raw_crd:
        return _decision(item_id, row_number, source, mapped, "No Match", "None", "MALFORMED_EMAIL", "The supplied email is malformed and no other identity field is usable.")
    if not input_name and not input_crd and not input_email:
        return _decision(item_id, row_number, source, mapped, "No Match", "None", "INSUFFICIENT_EVIDENCE", "A usable advisor name, CRD, or email is required.")
    ranked = sorted((_candidate(mapped, record) for record in advisors), key=lambda item: (-item.internal_score, item.crd_number))
    exact_supported = [candidate for candidate in ranked if _name_similarity(mapped, candidate) == 1 and _has_support(mapped, candidate)]
    if len(exact_supported) == 1 and not _strong_conflict(mapped, exact_supported[0]):
        return _decision(item_id, row_number, source, mapped, "Matched", "High", "EXACT_NAME_SUPPORTED", "Exact normalized name and independent firm/location evidence identified one advisor.", exact_supported[0])
    plausible = [candidate for candidate in ranked if candidate.internal_score >= PLAUSIBLE_SCORE and _name_similarity(mapped, candidate, aliases=True) >= MINIMUM_NAME_SIMILARITY]
    if plausible:
        top = plausible[0]
        margin = top.internal_score - (plausible[1].internal_score if len(plausible) > 1 else 0)
        if top.internal_score >= ACCEPTANCE_SCORE and margin >= MINIMUM_MARGIN and _has_support(mapped, top) and not _strong_conflict(mapped, top) and not _uses_nickname_alias(mapped, top):
            return _decision(item_id, row_number, source, mapped, "Matched", "High", "FUZZY_NAME_CORROBORATED", "Strong name similarity plus independent firm/location evidence identified one advisor.", top)
        shown = plausible[:REVIEW_CANDIDATE_LIMIT]
        return MatchDecision(review_item_id=item_id, source_row_number=row_number, source_values=source, mapped_values=mapped, status="Ambiguous Match", confidence="Uncertain", rule_id="AMBIGUOUS_CANDIDATES", explanation="One or more plausible candidates require user review.", candidates=shown)
    return _decision(item_id, row_number, source, mapped, "No Match", "None", "NO_ACCEPTABLE_CANDIDATE", "No advisor satisfied the accepted identity rules.")


def _decision(item_id, row_number, source, mapped, status, confidence, rule, explanation, advisor=None, warnings=None):
    return MatchDecision(review_item_id=item_id, source_row_number=row_number, source_values=source, mapped_values=mapped, status=status, confidence=confidence, rule_id=rule, explanation=explanation, matched_advisor=advisor, warnings=warnings or [])


def _candidate(mapped: dict[str, str], record: AdvisorRecord) -> MatchCandidate:
    input_name = _input_name(mapped, aliases=True)
    master_name = norm.person_name(f"{record.first_name} {record.last_name}")
    similarities = {
        "name": _ratio(input_name, master_name), "firm": _ratio(norm.firm(mapped.get("firm_name")), norm.firm(record.firm_name)),
        "street": _ratio(norm.street(mapped.get("street_address")), norm.street(record.street_address)), "city": _ratio(norm.city(mapped.get("city")), norm.city(record.city)),
        "state": _ratio(norm.state(mapped.get("state")), norm.state(record.state)), "zip": _ratio(norm.zip_code(mapped.get("zip_code")), norm.zip_code(record.zip_code)),
    }
    present = {field: value for field, value in similarities.items() if _present(mapped, field)}
    denominator = sum(WEIGHTS[field] for field in present) or 1
    score = sum(WEIGHTS[field] * value for field, value in present.items()) / denominator
    matched = [field for field, value in present.items() if value >= 0.99]
    conflicts = [field for field, value in present.items() if value < 0.45]
    return MatchCandidate(**record.model_dump(), matched_fields=matched, conflicting_fields=conflicts, internal_score=score)


def _input_name(mapped, *, aliases=False):
    raw_full = str(mapped.get("full_name") or "").strip()
    if raw_full.count(",") == 1:
        family, given = raw_full.split(",", 1)
        full = norm.person_name(f"{given} {family}")
    else:
        full = norm.person_name(raw_full)
    value = full or norm.person_name(f"{mapped.get('first_name', '')} {mapped.get('last_name', '')}")
    if not aliases or not value:
        return value
    first, *remaining = value.split()
    return " ".join((norm.NICKNAMES.get(first, first), *remaining))


def _ratio(left, right):
    if not left or not right:
        return 0
    return SequenceMatcher(None, left, right).ratio()


def _present(mapped, field):
    source = {"name": _input_name(mapped), "firm": mapped.get("firm_name"), "street": mapped.get("street_address"), "city": mapped.get("city"), "state": mapped.get("state"), "zip": mapped.get("zip_code")}
    return bool(str(source[field] or "").strip())


def _name_similarity(mapped, candidate, *, aliases=False):
    return _ratio(_input_name(mapped, aliases=aliases), norm.person_name(f"{candidate.first_name} {candidate.last_name}"))


def _uses_nickname_alias(mapped, candidate):
    return _name_similarity(mapped, candidate, aliases=True) > _name_similarity(mapped, candidate)


def _has_support(mapped, candidate):
    fields = set(candidate.matched_fields)
    return "firm" in fields or {"city", "state"} <= fields or {"street", "zip"} <= fields


def _strong_conflict(mapped, candidate):
    return "name" in candidate.conflicting_fields or len(set(candidate.conflicting_fields) & {"firm", "state", "zip"}) >= 2


def _duplicate_signature(mapped):
    return "|".join((norm.crd(mapped.get("crd_number")), norm.email(mapped.get("email")), _input_name(mapped), norm.firm(mapped.get("firm_name")), norm.city(mapped.get("city")), norm.state(mapped.get("state"))))
