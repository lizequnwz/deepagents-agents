# Advisor Match Workflow Walkthrough

1. The user sends text and optionally one CSV/XLSX attachment.
2. A new attachment resets only that conversation's in-memory graph state.
3. The typed router classifies the request and extracts an explicitly stated
   all-rows firm. Invalid structured output is retried up to three total tries.
4. For a match, deterministic code profiles bounded rows and sheets.
5. The typed mapping node selects one sheet/header and exact column indexes. If
   the evidence is ambiguous, `interrupt()` returns a clarification question.
   A yes/no question includes the exact proposed mapping that “yes” would accept.
6. The next text-only turn resumes the same graph with `Command(resume=...)`.
   Mapping answers bypass the general request router: a clear affirmative
   deterministically accepts the pending proposal, while other answers are
   interpreted using only the pending question, current answer, optional
   proposal, and bounded file profile. Full message history is not required.
7. Deterministic validation reloads the immutable upload, applies row limits,
   validates transformations, and creates a mapping fingerprint.
8. Deterministic firm handling either proceeds or interrupts with bounded
   discrepancies and explicit allowed choices.
9. The authoritative source is copied into an immutable corporation-scoped
   snapshot. The model never sees the full reference.
10. Normalization, candidate generation, scoring, decisions, duplicate
    detection, and counts run in Python under the checked-in matching policy.
11. A durable match session is saved and a four-sheet workbook is generated,
    verified, hashed, and published as an immutable artifact.
12. The graph ends. Ambiguous and unmatched records appear on **Review
    Required**, with blank **User Decision**, **Selected CRD**, and **Reviewer
    Notes** columns for offline use.
13. The user downloads and may edit that copy locally. Those edits are not sent
    back to or validated by the application; a new source attachment starts a
    new matching run.

Progress events use user-facing labels such as reading the upload, identifying
columns, validating rows, matching advisors, and publishing the workbook. They
do not stream model tokens, tool calls, plans, or subagents. On API restart, the
current conversation starts fresh by design; previously published advisor
evidence remains available for audit through the durable repository.
