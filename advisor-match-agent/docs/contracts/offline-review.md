# Offline workbook review

The LangGraph run ends after the verified `advisor_matches.xlsx` artifact is
published. It does not paginate review records in chat, apply row-level
decisions, resolve manual CRD proposals, approve a session, or regenerate a
workbook from conversational changes.

`Review Required` is the sole post-match review surface. It contains one row per
presented candidate, or one row for a No Match with no candidate. Each row keeps
the source row number, input identity, candidate identity, qualitative evidence,
warnings, and hidden audit fields. Three blank, highlighted fields support local
work:

- `User Decision` — the reviewer records the intended outcome;
- `Selected CRD` — the reviewer records a chosen or independently researched CRD;
- `Reviewer Notes` — the reviewer records rationale or follow-up context.

These columns are intentionally free-form because the application does not
re-ingest or validate the downloaded file. Any independently researched CRD or
other factual correction remains the user's responsibility. If the source data
itself should change, upload a corrected CSV/XLSX and run matching again.

The only conversational input augmentation is one explicitly user-supplied firm
applied to all validated advisor rows before matching. It is recorded in the
session and workbook without modifying the original upload.
