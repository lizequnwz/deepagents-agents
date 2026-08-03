---
name: advisor-match
description: "Interpret one advisor CSV or XLSX flexibly, match its rows deterministically against the authoritative advisor database, create advisor_matches.xlsx, and conduct conversational exception review. Use for header detection, column mapping, CRD lookup, advisor identity resolution, fuzzy firm/name matching, review overrides, and approval."
---

# Advisor matching

## 1. Interpret and validate the upload

1. Confirm that a new request has exactly one `.csv` or `.xlsx` attachment ID.
2. Call `inspect_advisor_upload` with that opaque attachment ID. Inspect its bounded raw rows, plausible header rows, headerless view, patterns, and samples. Do not use generic file tools on the upload.
3. Select exactly one worksheet. Choose a headed or headerless interpretation only when the evidence is clear. Ask the user when multiple sheets, header rows, or field meanings are plausible.
4. Construct `InputMapping` using exact zero-based column indexes and exact observed headers. Use `header_row=null` and `header=null` for headerless input. Map only CRD, full name or both first/last name, firm, email, city, state, and optional ZIP.
5. Call `validate_advisor_input`. If it reports that no firm column is mapped, always ask whether one firm applies to every advisor in the selected table, even when CRD or email evidence is available. Also report the count and bounded sample of usable-name rows that lack firm, valid CRD, and valid email.
6. If the user answers on a later turn, call `get_current_advisor_input` to recover the corporation-scoped validated checkpoint. If the user explicitly supplies one firm for every advisor, call `apply_firm_to_advisor_upload` with the exact user-supplied firm; it can securely resolve the latest validated attachment and mapping. The exact firm text must appear in that current user message—if the user only says “yes” or refers to an earlier name, ask them to restate it. This is the only supported conversational source augmentation. It creates an immutable derived attachment and never overwrites the original. Call `validate_advisor_input` on the returned attachment and mapping before proceeding. If no firm is available, use the recovered checkpoint and ask whether to continue with weaker evidence.

## 2. Match deterministically

7. After all clarification and any derived-input validation, call `find_all_advisors` exactly once for the new run. Treat its snapshot ID as opaque.
8. Call `create_advisor_match` with the exact validated attachment, mapping, mapping fingerprint, reference snapshot ID, and `allow_missing_firm=true` only after the user explicitly chooses to continue without firm data.
9. Report the interpreted mapping, selected sheet/header mode, any bulk-firm augmentation, `Matched`, `Ambiguous Match`, and `No Match` counts, warnings, session ID, and workbook artifact ID.

## 3. Review exceptions conversationally

10. Page through `Ambiguous Match` items first with `list_advisor_match_results`, then offer `No Match` pages by reason. Use pages of 10 or fewer. Show automated Matched rows only when requested.
11. Explain source rows, candidate CRDs, and qualitative firm/location support or conflicts. Never present internal scores.
12. Use `apply_advisor_match_decisions` only for an explicit candidate or No Match choice. Other source-data corrections require a corrected upload and new session.
13. For an unlisted advisor, require an exact user-supplied CRD, call `propose_crd_match`, show the resolved record, and wait for confirmation in a later user turn before applying it.
14. The user may approve with unresolved exceptions. After approval, report the final workbook artifact. Profile building is not implemented; do not offer or simulate it.

If a prior turn failed after matching or the user asks to continue, call `get_current_advisor_match` and resume the latest persisted session instead of rerunning matching.

Never invent an advisor, treat name-only or nickname-only evidence as proof, expose the complete master table, overwrite an uploaded file, or edit the workbook directly. Only `apply_firm_to_advisor_upload` may add one explicitly user-supplied firm to every validated advisor row in a derived attachment. Deterministic tools own every row decision and publish every verified workbook revision as an immutable artifact.

Read when needed:

- [column-mapping.md](references/column-mapping.md) while interpreting an upload.
- [advisor-schema.md](references/advisor-schema.md) for canonical fields and mapping rules.
- [matching-policy.md](references/matching-policy.md) for rule order and conflicts.
- [workbook-contract.md](references/workbook-contract.md) before explaining exports.
- [conversational-review.md](references/conversational-review.md) for paging and review decisions.
- [database-tool-contract.md](references/database-tool-contract.md) for reference snapshots.
- [profile-building-contract.md](references/profile-building-contract.md) only after approval.
