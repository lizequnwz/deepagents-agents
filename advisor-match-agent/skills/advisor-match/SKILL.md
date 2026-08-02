---
name: advisor-match
description: "Interpret one advisor CSV or XLSX flexibly, match its rows deterministically against the authoritative advisor database, create advisor_matches.xlsx, and conduct conversational exception review. Use for header detection, column mapping, CRD lookup, advisor identity resolution, fuzzy firm/name matching, review overrides, and approval."
---

# Advisor matching

## 1. Interpret and validate the upload

1. Confirm that a new request has exactly one `.csv` or `.xlsx` upload.
2. Call `profile_advisor_file`. Inspect its bounded raw rows, plausible header rows, headerless view, patterns, and samples. Do not use generic file tools on the upload.
3. Select exactly one worksheet. Choose a headed or headerless interpretation only when the evidence is clear. Ask the user when multiple sheets, header rows, or field meanings are plausible.
4. Construct `InputMapping` using exact zero-based column indexes and exact observed headers. Use `header_row=null` and `header=null` for headerless input. Map only CRD, full name or both first/last name, firm, email, city, state, and optional ZIP.
5. Call `validate_advisor_mapping`. If it reports rows with a usable name but no firm, valid CRD, or valid email, report the count and bounded sample, then ask whether the user can provide a corrected upload or wants to continue. Never add source values conversationally.

## 2. Match deterministically

6. After all clarification, call `find_all_advisors_in_database` exactly once for the new run. Treat its snapshot ID as opaque.
7. Call `start_advisor_match` with the exact validated mapping, mapping fingerprint, reference snapshot ID, and `allow_missing_firm=true` only after the user explicitly chooses to continue without firm data.
8. Report the interpreted mapping, selected sheet/header mode, `Matched`, `Ambiguous Match`, and `No Match` counts, warnings, session ID, and `/advisor_matches.xlsx`.

## 3. Review exceptions conversationally

9. Page through `Ambiguous Match` items first with `list_advisor_match_items`, then offer `No Match` pages by reason. Use pages of 10 or fewer. Show automated Matched rows only when requested.
10. Explain source rows, candidate CRDs, and qualitative firm/location support or conflicts. Never present internal scores.
11. Use `apply_advisor_review_decisions` only for an explicit candidate or No Match choice. Source-data corrections require a corrected upload and new session.
12. For an unlisted advisor, require an exact user-supplied CRD, call `propose_manual_crd_override`, show the resolved record, and wait for confirmation in a later user turn before applying it.
13. The user may approve with unresolved exceptions. After approval, offer profile building for Matched rows only and explain that it is not implemented yet.

If a prior turn failed after matching or the user asks to continue, call `get_current_advisor_match_session` and resume the latest persisted session instead of rerunning matching.

Never invent an advisor, treat name-only or nickname-only evidence as proof, expose the complete master table, edit uploaded values, or edit the workbook directly. Deterministic tools own every row decision and workbook revision.

Read when needed:

- [column-mapping.md](references/column-mapping.md) while interpreting an upload.
- [advisor-schema.md](references/advisor-schema.md) for canonical fields and mapping rules.
- [matching-policy.md](references/matching-policy.md) for rule order and conflicts.
- [workbook-contract.md](references/workbook-contract.md) before explaining exports.
- [conversational-review.md](references/conversational-review.md) for paging and review decisions.
- [database-tool-contract.md](references/database-tool-contract.md) for reference snapshots.
- [profile-building-contract.md](references/profile-building-contract.md) only after approval.
