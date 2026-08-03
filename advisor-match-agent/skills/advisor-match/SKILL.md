---
name: advisor-match
description: "Interpret one advisor CSV or XLSX flexibly, match its rows deterministically against the authoritative advisor database, create advisor_matches.xlsx, and conduct conversational exception review. Use for header detection, column mapping, CRD lookup, exact normalized advisor identity resolution, bounded firm comparison, review overrides, and approval."
---

# Advisor matching

## 1. Interpret and validate the upload

1. Confirm that a new request has exactly one `.csv` or `.xlsx` attachment ID.
2. Call `inspect_advisor_upload` with that opaque attachment ID. Inspect its bounded raw rows, plausible header rows, headerless view, patterns, and samples. Do not use generic file tools on the upload.
3. Select exactly one worksheet. Choose a headed or headerless interpretation only when the evidence is clear. Ask the user when multiple sheets, header rows, or field meanings are plausible.
4. Construct `InputMapping` using exact zero-based column indexes and exact observed headers. Use `header_row=null` and `header=null` for headerless input. Map only CRD, full name or both first/last name, firm, email, city, state, and optional ZIP.
5. Call `validate_advisor_input`. Report the bounded count and sample of usable-name rows that lack firm, valid CRD, and valid email. A missing firm column alone is not a blocker when every row has CRD or valid email evidence.
6. Call `create_advisor_match` with the exact validated attachment, mapping, and fingerprint. If the current user message explicitly states one firm for every advisor, pass the exact firm as `all_rows_firm` in this same call and same turn. The firm text must appear in the current user message, but the user need not repeat it or say “apply.” The tool never changes or derives the upload; it applies an audited session override only to copied mapped values.
7. Treat `firm_clarification_required` as a bounded checkpoint. When source firm values are blank, mixed, or conflict with the stated firm, show the discrepancy and ask whether to use source values or override all rows. On a later turn call `get_current_advisor_input`, then call `create_advisor_match` with `firm_resolution="use_source"` or with `firm_resolution="override_all"` plus the exact firm restated in that current message. Use `continue_without_firm` only after explicit permission to continue with weaker evidence.

## 2. Match deterministically

8. `match_created` is the only successful match outcome. It retrieves or reuses the attachment-scoped authoritative snapshot, runs deterministic matching, and publishes the verified workbook. Treat the returned reference manifest and snapshot ID as opaque. Never request the master rows or a protected path.
9. Treat `blocked` as an authoritative-source problem. Report the blocker and stop without blaming the upload or retrying. For `match_created`, report the interpreted mapping, selected sheet/header mode, any session firm override, `Matched`, `Ambiguous Match`, and `No Match` counts, warnings, session ID, and workbook artifact ID.

## 3. Review exceptions conversationally

10. Page through `Ambiguous Match` items first with `list_advisor_match_results`, then offer `No Match` pages by reason. Use pages of 10 or fewer. Show automated Matched rows only when requested.
11. Explain source rows, candidate CRDs, total candidate counts, truncation, and qualitative firm/location support or conflicts. Never present internal firm-similarity values.
12. Use `apply_advisor_match_decisions` only for an explicit candidate or No Match choice. Other source-data corrections require a corrected upload and new session.
13. For an unlisted advisor, require an exact user-supplied CRD, call `propose_crd_match`, show the resolved record, and wait for confirmation in a later user turn before applying it.
14. The user may approve with unresolved exceptions. After approval, report the final workbook artifact. Profile building is not implemented; do not offer or simulate it.

If a prior turn failed after matching or the user asks to continue, call `get_current_advisor_match` and resume the latest persisted session instead of rerunning matching.

Never invent an advisor, treat name-only or nickname-only evidence as proof, expose the complete master table, overwrite or derive an uploaded file, or edit the workbook directly. Only `create_advisor_match` may apply one explicitly user-supplied firm to every validated advisor row as an audited session override. Deterministic tools own every row decision and publish every verified workbook revision as an immutable artifact.

Read when needed:

- [column-mapping.md](references/column-mapping.md) while interpreting an upload.
- [advisor-schema.md](references/advisor-schema.md) for canonical fields and mapping rules.
- [matching-policy.md](references/matching-policy.md) for rule order and conflicts.
- [workbook-contract.md](references/workbook-contract.md) before explaining exports.
- [conversational-review.md](references/conversational-review.md) for paging and review decisions.
- [database-tool-contract.md](references/database-tool-contract.md) for reference snapshots.
- [profile-building-contract.md](references/profile-building-contract.md) only after approval.
