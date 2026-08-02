---
name: advisor-match
description: "Match financial-advisor rows from one uploaded CSV or XLSX against the authoritative advisor database, create advisor_matches.xlsx, and conduct a conversational review of matched, ambiguous, or unmatched records. Use for CRD lookup, advisor identity resolution, fuzzy advisor matching, column mapping, review overrides, and approval before advisor profile building."
---

# Advisor matching

1. Confirm that a new matching request has exactly one `.csv` or `.xlsx` upload.
2. Call `profile_advisor_file`. Do not use generic file tools on the upload.
3. Select a worksheet and construct a typed mapping only when the profile is clear. Ask the user when multiple sheets or columns are plausible.
4. Call `find_all_advisors_in_database` once for the run.
5. Call `start_advisor_match` with the validated mapping and returned snapshot path.
6. Report the selected sheet, `Matched`, `Ambiguous Match`, and `No Match` counts, warnings, session ID, and `/advisor_matches.xlsx`.
7. Call `list_advisor_match_items` with a small page to review results. Status filters accept `matched`, `ambiguous_match`, or `no_match` as well as their display labels. Never request or reproduce the full session.
8. Ask whether the user is happy with the results and which records they want to confirm, refine, or leave unmatched. If a name identifies multiple source rows or candidates, ask for the source row or CRD.
9. Use `apply_advisor_review_decisions` only for an explicit user choice. Never choose a candidate yourself.
10. For an advisor outside the presented candidates, require an exact user-supplied CRD, call `propose_manual_crd_override`, show the resolved record, and wait for confirmation in a later user turn before applying it.
11. After approval, offer profile building for Matched rows only. Explain that profile building is not implemented yet.

If a prior turn failed after matching or the user asks to continue, call `get_current_advisor_match_session` and resume the persisted review instead of rerunning matching.

Never invent an advisor, treat a fuzzy name alone as identity proof, expose the complete master table, or edit the workbook directly. Deterministic tools own every row decision and workbook revision.

Read when needed:

- [advisor-schema.md](references/advisor-schema.md) for canonical fields and typed mapping rules.
- [matching-policy.md](references/matching-policy.md) for rule order, normalization, and conflicts.
- [workbook-contract.md](references/workbook-contract.md) before explaining or validating exports.
- [conversational-review.md](references/conversational-review.md) for paging and review decisions.
- [database-tool-contract.md](references/database-tool-contract.md) for reference snapshots and the future Snowflake adapter.
- [profile-building-contract.md](references/profile-building-contract.md) only after the user approves matching.
