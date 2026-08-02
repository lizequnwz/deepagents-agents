# Advisor Match implementation architecture

## State ownership

The language model orchestrates a narrow workflow; it does not own match state or workbook contents.

1. A bounded file profile gives the model sheet names, headers, patterns, and at most three sample rows.
2. The database tool creates a run-scoped reference snapshot and returns only a manifest.
3. Deterministic matching persists every row as a typed decision in a corporation-scoped SQLite match session.
4. The agent reads review state only through filtered pages of at most 20 items (the skill directs pages of 10).
5. User choices mutate typed session decisions. The workbook is regenerated and verified from those decisions.

This is how the main agent knows what is matched or ambiguous: it holds the match-session ID and asks the list tool for bounded, structured views. It does not need—and cannot access—the whole Excel file.

## Conversational revision

For a presented candidate, an explicit user choice can be applied in the current follow-up turn. Same-name rows must be disambiguated by source row or CRD. For an unlisted candidate, the agent must receive an exact CRD, resolve and display it, then wait for a later run/user turn; code rejects same-run confirmation.

The original upload is immutable. Applying “John Smith should be CRD 99000002” changes the persisted decision, records before/after audit data, and regenerates `advisor_matches.xlsx`. It never edits a cell in the uploaded workbook.

## Components

- `advisor_matching/profiler.py` and `input_loader.py`: bounded parsing and typed mappings.
- `advisor_matching/source.py`: replaceable source protocol and synthetic adapter.
- `advisor_matching/matcher.py`: versioned matching hierarchy and top-three candidates.
- `advisor_tools.py`: only workflow operations exposed to the model.
- `store.py`: sessions, audit decisions, and two-turn manual-override proposals.
- `advisor_matching/workbook.py`: safe four-sheet projection and reconciliation.
- `advisor_backend.py`: read-only skill filesystem plus run/corporation context; no shell.

## Production database replacement

The checked-in 40-row synthetic source exercises the initial whole-snapshot contract. For Snowflake-scale data, preserve the manifest and review schemas while replacing full-table transfer with stable-snapshot, server-side exact lookup and blocked candidate retrieval. Production acceptance at 50,000 input rows and 1,000,000 master rows requires indexed/blocking candidate generation and load/performance testing; the initial in-memory fuzzy implementation does not claim that scale.

## Deferred profile building

`ProfileBuildRequest` and the skill reference document the intended handoff. No profile tool is registered. A future implementation must accept an approved session, use effective Matched CRDs only, preserve corporation scope, and generate separate auditable artifacts.
