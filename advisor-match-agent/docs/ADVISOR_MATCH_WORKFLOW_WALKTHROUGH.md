# Advisor Match and Profile Report Workflow Walkthrough

## Shared entry and routing

1. The user sends text with at most one CSV/XLSX attachment, or clicks an
   explicit workflow action.
2. A new attachment resets only that conversation's in-memory checkpoint.
3. An explicit `requested_workflow` selects matching or profile reporting
   deterministically. Otherwise the typed router interprets the current request.
4. One run remains active per corporation and conversation; progress continues
   through the existing polling and event pipeline.

## Advisor matching

1. Deterministic code creates a bounded worksheet/header/column profile.
2. The typed mapping node selects exact physical columns. Ambiguity pauses via
   `interrupt()` and resumes from the pending context with `Command(resume=...)`.
3. Validation reopens the immutable upload, applies row limits and
   transformations, and records a mapping fingerprint.
4. Firm handling, reference snapshots, normalization, candidate generation,
   scoring, duplicate detection, and identity decisions remain deterministic.
5. The service persists a match session and publishes a verified, hashed,
   immutable four-sheet `advisor_matches.xlsx`.
6. Ambiguous and unmatched rows remain an offline-review workflow; edited
   workbook copies are never re-ingested.

## Direct profile report from an upload

1. The shared inspection step produces the same bounded file profile.
2. `map_crd_input` identifies exactly one worksheet, header row, and physical
   CRD column. Multiple plausible choices interrupt for one bounded
   clarification; a missing CRD column stops without an artifact.
3. `validate_crd_input` reopens the protected attachment and validates its hash,
   row limit, exact header/index pair, and fingerprint.
4. Deterministic extraction trims surrounding whitespace, ignores blanks, and
   deduplicates opaque CRDs in first-seen order.
5. An empty usable set returns a controlled response and creates no report.

## Profile report after matching

1. A completed workbook is rendered with a **Generate advisor profile report**
   action carrying its exact `match_session_id`.
2. The API and service revalidate that ID against the corporation and
   conversation; the workbook itself is not parsed.
3. The service loads only automated `Matched` decisions with a matched advisor,
   excludes ambiguous/unmatched/candidate-only CRDs, and deduplicates repeats.

## Shared report publication

1. `generate_advisor_profile_report(crd_numbers)` returns deterministic UTF-8
   placeholder HTML with an empty body and no scripts or user content.
2. The service verifies minimal HTML structure, hashes the bytes, atomically
   replaces a temporary `.building.html` file, and persists an additive report
   record with source, CRDs, counts, mapping evidence, and artifact metadata.
3. Streamlit fetches the artifact through the existing scoped endpoint, renders
   a sanitized inline preview with `st.html`, and provides **Download HTML**.
4. Failures remove partial files and do not publish runtime artifacts or report
   records.

API restart still loses active conversations, checkpoints, and pending
interrupts by design. Previously published matching and profile-report evidence
remains available in the durable repository.
