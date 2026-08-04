"""Deterministic, user-facing copy for the advisor workflow."""

from __future__ import annotations

from typing import Any


def attachment_required() -> str:
    return (
        "I can help with that. Attach one advisor CSV or XLSX file to begin. "
        "Include whichever identity fields you have—such as advisor name, CRD, "
        "email, firm, city, or state—and I’ll inspect the columns before matching."
    )


def match_complete(counts: dict[str, Any]) -> str:
    matched = int(counts.get("matched") or 0)
    ambiguous = int(counts.get("ambiguous_match") or 0)
    unmatched = int(counts.get("no_match") or 0)
    total = matched + ambiguous + unmatched
    lines = [
        f"I finished matching {_advisors(total)}:",
        "",
        f"- {matched} {_was_were(matched)} matched automatically",
        f"- {ambiguous} {_has_have(ambiguous)} multiple possible matches",
        f"- {unmatched} could not be matched",
        "",
        "I prepared the workbook below.",
    ]
    if ambiguous or unmatched:
        choices = []
        if ambiguous:
            choices.append(f"review the {_advisors(ambiguous, 'ambiguous advisor')}")
        if unmatched:
            choices.append(f"review the {_advisors(unmatched, 'unmatched advisor')}")
        lines.append(f"Next, you can ask me to {' or '.join(choices)}.")
    else:
        lines.append("All rows matched automatically, so the results are ready for approval.")
    return "\n".join(lines)


def no_match_session() -> str:
    return (
        "There aren’t any advisor-matching results in this chat yet. Attach one "
        "advisor CSV or XLSX file and I’ll start a new match."
    )


def decisions_applied(result: dict[str, Any], decision_count: int) -> str:
    counts = result.get("counts") or {}
    remaining = int(counts.get("ambiguous_match") or 0) + int(
        counts.get("no_match") or 0
    )
    opening = (
        "I applied that review decision"
        if decision_count == 1
        else f"I applied {decision_count} review decisions"
    )
    if remaining:
        next_step = (
            f"There {_is_are(remaining)} still {_advisors(remaining, 'advisor')} "
            "that may need review."
        )
    else:
        next_step = "No advisors remain in the ambiguous or unmatched queues."
    return f"{opening} and regenerated the workbook below. {next_step}"


def manual_crd_proposal(row_number: int, advisor: dict[str, Any]) -> str:
    name = _name(advisor) or "this advisor"
    firm = str(advisor.get("firm_name") or "").strip()
    location = _location(advisor)
    details = ", ".join(value for value in (firm, location) if value)
    suffix = f" — {details}" if details else ""
    return (
        f"I found CRD {advisor.get('crd_number')} for row {row_number}: "
        f"{name}{suffix}. This advisor was not one of the candidates originally "
        "presented for that row, so I have not changed the match yet.\n\n"
        "To apply this manual match, reply `Confirm this match`. To leave the row "
        "unchanged, reply `Cancel this match`."
    )


def no_pending_manual_match() -> str:
    return (
        "There isn’t a manual advisor match waiting for confirmation. Ask me to "
        "show the advisors that need review, then choose a row and CRD."
    )


def manual_match_cancelled(row_number: int | None = None) -> str:
    target = f" for row {row_number}" if row_number else ""
    return (
        f"I cancelled the proposed manual match{target}. No matching decision was changed."
    )


def approval_complete(result: dict[str, Any]) -> str:
    counts = result.get("counts") or {}
    return (
        "The review is approved, and the final workbook is ready below. "
        f"It contains {int(counts.get('matched') or 0)} matched, "
        f"{int(counts.get('ambiguous_match') or 0)} ambiguous, and "
        f"{int(counts.get('no_match') or 0)} unmatched advisor rows."
    )


def status_summary(current: dict[str, Any]) -> str:
    counts = current.get("counts") or {}
    status = str(current.get("status") or "in progress").casefold()
    label = "approved" if status == "approved" else "ready for review"
    ambiguous = int(counts.get("ambiguous_match") or 0)
    unmatched = int(counts.get("no_match") or 0)
    if status == "approved":
        next_step = "The approved workbook is available in this chat."
    elif ambiguous or unmatched:
        next_step = "Ask me to show the advisors that need review."
    else:
        next_step = "The results are ready for approval."
    return (
        f"The current matching results are {label}: "
        f"{int(counts.get('matched') or 0)} matched, {ambiguous} ambiguous, and "
        f"{unmatched} unmatched. {next_step}"
    )


def reset_complete() -> str:
    return (
        "I cleared the current matching progress from this chat. When you’re ready, "
        "attach a CSV or XLSX file to start a fresh match."
    )


def capabilities(has_match: bool = False) -> str:
    if has_match:
        return (
            "I can show ambiguous or unmatched advisors, explain the available "
            "candidates, apply your explicit review choices, approve the results, and "
            "regenerate the workbook. For example, ask `Show advisors that need review`."
        )
    return (
        "I can match advisors from one CSV or XLSX file against the configured master "
        "advisor database. I’ll inspect the columns, perform deterministic matching, "
        "guide you through uncertain rows, and prepare an auditable workbook. Attach a "
        "file when you’re ready. I don’t perform general web research or build "
        "advisor profiles."
    )


def unsupported(
    has_match: bool = False,
    has_attachment: bool = False,
    pending_kind: str | None = None,
) -> str:
    if pending_kind == "mapping":
        next_step = (
            "I’m waiting for your answer about how to interpret the uploaded columns. "
            "Please answer that question or provide the worksheet, header row, or "
            "column meaning you want me to use."
        )
    elif pending_kind == "firm":
        next_step = (
            "I’m waiting for your answer about the advisors’ firm information. "
            "Please identify the firm column, provide one firm for all rows, or ask me "
            "to continue without firm information."
        )
    elif has_match:
        next_step = (
            "You can ask me to show matching status, review uncertain advisors, approve "
            "the results, or regenerate the workbook."
        )
    elif has_attachment:
        next_step = (
            "I already have the uploaded file. You can ask me to start matching it or "
            "explain how its columns should be interpreted."
        )
    else:
        next_step = (
            "Attach one advisor CSV or XLSX file, or ask what information the file "
            "should contain."
        )
    return f"I’m focused on advisor matching and can’t help with that request. {next_step}"


def review_page(page: dict[str, Any]) -> str:
    items = page.get("items") or []
    if not items:
        return (
            "I didn’t find any advisors matching that review filter. You can ask to "
            "see ambiguous advisors, unmatched advisors, or the current matching status."
        )
    lines = [f"Here {_is_are(len(items))} {_advisors(len(items))} to review:"]
    for item in items:
        row = int(item["source_row_number"])
        name = _name(item.get("input") or {}) or "Unnamed advisor"
        lines.extend(
            [
                "",
                f"**Row {row} — {name}**",
                str(item.get("reason") or "Review is required."),
            ]
        )
        warnings = [str(value) for value in item.get("warnings") or [] if value]
        if warnings:
            lines.append("Warnings: " + "; ".join(warnings))
        candidates = item.get("candidates") or []
        if candidates:
            lines.append("Possible matches:")
            for index, candidate in enumerate(candidates, start=1):
                lines.append(_candidate_line(index, candidate))
            lines.append(
                f"Reply `Choose CRD <number> for row {row}` or "
                f"`Leave row {row} unmatched`."
            )
        else:
            lines.append(
                f"No candidate met the matching requirements. If you know the advisor’s "
                f"CRD, reply `Use CRD <number> for row {row}`; otherwise reply "
                f"`Leave row {row} unmatched`."
            )
    if page.get("next_cursor") is not None:
        lines.extend(
            [
                "",
                "More review items are available. Say `Show the next review page` to continue.",
            ]
        )
    return "\n".join(lines)


def user_fixable_error(error: ValueError) -> str:
    detail = " ".join(str(error).split()).strip().rstrip(".")
    if not detail:
        detail = "the supplied information could not be validated"
    return (
        f"I couldn’t continue because {detail[0].lower() + detail[1:]}. "
        "Please correct that information and try again; your original upload was not changed."
    )


def _candidate_line(index: int, candidate: dict[str, Any]) -> str:
    identity = _name(candidate) or "Unnamed advisor"
    firm = str(candidate.get("firm_name") or "Firm unavailable").strip()
    location = _location(candidate)
    location_text = f" · {location}" if location else ""
    evidence = [str(value) for value in candidate.get("supporting_evidence") or []]
    conflicts = [str(value) for value in candidate.get("conflicting_evidence") or []]
    suffix = []
    if evidence:
        suffix.append("supports: " + "; ".join(evidence))
    if conflicts:
        suffix.append("conflicts: " + "; ".join(conflicts))
    evidence_text = f" — {' | '.join(suffix)}" if suffix else ""
    return (
        f"{index}. **{identity}** · {firm}{location_text} · "
        f"CRD {candidate.get('crd_number')}{evidence_text}"
    )


def _name(value: dict[str, Any]) -> str:
    full = str(value.get("full_name") or "").strip()
    if full:
        return full
    return " ".join(
        part
        for part in (
            str(value.get("first_name") or "").strip(),
            str(value.get("last_name") or "").strip(),
        )
        if part
    )


def _location(value: dict[str, Any]) -> str:
    city = str(value.get("city") or "").strip()
    state = str(value.get("state") or "").strip()
    return ", ".join(part for part in (city, state) if part)


def _advisors(count: int, noun: str = "advisor") -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _was_were(count: int) -> str:
    return "was" if count == 1 else "were"


def _has_have(count: int) -> str:
    return "has" if count == 1 else "have"


def _is_are(count: int) -> str:
    return "is" if count == 1 else "are"
