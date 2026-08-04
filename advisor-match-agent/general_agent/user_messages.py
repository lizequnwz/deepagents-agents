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
        "Download the workbook below for the complete results and audit details.",
    ]
    if ambiguous or unmatched:
        lines.extend(
            [
                "Open the **Review Required** sheet to review ambiguous or unmatched "
                "records. You can record your final decisions in the blank **User "
                "Decision**, **Selected CRD**, and **Reviewer Notes** columns, then save "
                "that downloaded copy for your downstream work.",
                "",
                "Edits to the downloaded workbook stay on your computer; they are not "
                "sent back to or validated by this application.",
            ]
        )
    else:
        lines.append(
            "All rows matched automatically. The **Review Required** sheet is empty, "
            "and the workbook is ready for your downstream work."
        )
    if matched:
        lines.extend(
            [
                "",
                "Use **Generate advisor profile report** below to create a placeholder "
                "HTML report from the automatically matched CRD numbers.",
            ]
        )
    return "\n".join(lines)


def profile_source_required() -> str:
    return (
        "Attach one advisor CSV or XLSX file that contains CRD numbers, or first "
        "complete advisor matching and use its **Generate advisor profile report** "
        "action."
    )


def missing_crd_column() -> str:
    return (
        "I couldn’t find a usable CRD column in the uploaded file. A profile report "
        "requires one column containing CRD identifiers. Add or rename that column "
        "and upload the file again."
    )


def profile_report_complete(result: dict[str, Any]) -> str:
    unique = int(result.get("unique_crd_count") or 0)
    duplicates = int(result.get("duplicate_crd_count") or 0)
    blanks = int(result.get("blank_crd_count") or 0)
    lines = [
        f"I generated the placeholder advisor profile report for {unique} unique "
        f"CRD number{'s' if unique != 1 else ''}.",
        "Preview it below or download the HTML file for offline review.",
    ]
    if duplicates or blanks:
        lines.append(
            f"I ignored {duplicates} duplicate occurrence{'s' if duplicates != 1 else ''} "
            f"and {blanks} blank value{'s' if blanks != 1 else ''}."
        )
    return "\n\n".join(lines)


def reset_complete() -> str:
    return (
        "I cleared the current advisor workflow progress from this chat. When you’re "
        "ready, attach a CSV or XLSX file to start a fresh match or profile report."
    )


def capabilities(has_match: bool = False) -> str:
    if has_match:
        return (
            "The matching run is complete, and the workbook in this chat is the final "
            "application output. Review ambiguous or unmatched records on its **Review "
            "Required** sheet and record any final decisions in your downloaded copy. "
            "This application does not apply row-level review choices in chat or "
            "validate changes made to the downloaded workbook. You can generate a "
            "placeholder advisor profile report from the automatically matched CRDs, "
            "or attach a new file containing a CRD column."
        )
    return (
        "I can match advisors from one CSV or XLSX file against the configured master "
        "advisor database. I’ll inspect the columns, perform deterministic matching, "
        "and prepare an auditable workbook. Ambiguous and unmatched records are placed "
        "on a **Review Required** sheet for you to review in Excel. I can also generate "
        "a placeholder HTML advisor profile report from a CRD column. Attach a file "
        "when you’re ready. I don’t perform general web research."
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
    elif pending_kind == "profile_mapping":
        next_step = (
            "I’m waiting for your answer about which worksheet, header row, and column "
            "contains CRD numbers. Please answer that question to continue."
        )
    elif pending_kind == "firm":
        next_step = (
            "I’m waiting for your answer about the advisors’ firm information. "
            "Please identify the firm column, provide one firm for all rows, or ask me "
            "to continue without firm information."
        )
    elif has_match:
        next_step = (
            "The matching run is complete. Download the workbook, review ambiguous or "
            "unmatched records on the **Review Required** sheet, and make any final "
            "changes in your local copy."
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


def user_fixable_error(error: ValueError) -> str:
    detail = " ".join(str(error).split()).strip().rstrip(".")
    if not detail:
        detail = "the supplied information could not be validated"
    return (
        f"I couldn’t continue because {detail[0].lower() + detail[1:]}. "
        "Please correct that information and try again; your original upload was not changed."
    )


def _advisors(count: int) -> str:
    return f"{count} advisor" + ("" if count == 1 else "s")


def _was_were(count: int) -> str:
    return "was" if count == 1 else "were"


def _has_have(count: int) -> str:
    return "has" if count == 1 else "have"
