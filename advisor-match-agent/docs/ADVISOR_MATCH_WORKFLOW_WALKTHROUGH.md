# Advisor Match workflow walkthrough

## Advisor Matching tab

1. The user uploads one CSV/XLSX and selects **Analyze columns**.
2. The UI sends the file to `/advisor-match/mapping`. The API returns bounded
   previews, its SHA-256, a structured proposal, warnings, and any deterministic
   validation summary.
3. The user confirms the worksheet, physical header row, and one physical
   column per canonical field. Identity requires CRD, email, full name, or both
   first and last name.
4. If policy identifies weak name-only rows without a firm, the form explicitly
   chooses source firm, one audited all-rows firm, or continuing without firm.
5. **Start Matching** sends the unchanged file bytes, analysis SHA-256, mapping,
   and firm configuration to `/advisor-match/match`.
6. The API validates the full file before retrieving a fresh authoritative
   reference, then runs deterministic matching and workbook verification.
7. The UI displays Matched, Ambiguous, and No Match counts and offers the
   generated workbook for download. Row-level decisions remain in the workbook.

## Profile Generation tab

1. The user uploads a fresh CSV/XLSX, or selects **Continue to profile
   generation** to switch tabs and hand off the generated workbook bytes.
2. `/advisor-profile/mapping` proposes the worksheet, header row, and physical
   CRD column using the same bounded mapping pattern.
3. The user confirms the proposal. `/advisor-profile/generate` receives the
   unchanged file bytes, analysis SHA-256, and exact mapping.
4. The API deterministically validates and extracts CRDs, trims blanks, and
   deduplicates in first-seen order.
5. The UI previews and downloads the returned placeholder HTML report.

No step polls a run, resumes an interrupt, reads a prior session, or downloads
an API-side artifact. The UI keeps source bytes and results only in ephemeral
Streamlit session state.
