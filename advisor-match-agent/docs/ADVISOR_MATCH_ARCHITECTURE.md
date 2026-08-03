# Advisor Match implementation architecture

Advisor Match Agent has three user-facing stages and one strict ownership rule: the model interprets bounded evidence and conducts the conversation; deterministic application code owns every identity decision and workbook mutation.

The interactive workflow is also available as [advisor_match_workflow.html](advisor_match_workflow.html).

## Stage 1: interpret and validate

FastAPI stores the uploaded CSV or XLSX once in protected storage and gives it an opaque, corporation-and-conversation-scoped attachment ID. `inspect_advisor_upload` resolves that ID and reads at most the configured preview bounds with `header=None`. It therefore does not assume the first row is a header. For each CSV or bounded workbook sheet it returns:

- physical raw-row previews;
- several plausible header rows with exact header values, patterns, samples, and deterministic synonym suggestions;
- a headerless view using generated display labels such as `Column A`;
- the source hash and truncation warnings.

The agent selects exactly one worksheet, a headed or headerless interpretation, and an `InputMapping`. It asks the user when more than one interpretation is plausible.

`validate_advisor_input` then reopens the upload and validates the exact worksheet, physical header row, zero-based indexes, and observed headers. Duplicate headers remain safe because the index is decisive. Headerless references use `header=null`.

Validation loads only after the structural references pass. It skips completely blank rows, excludes preamble rows above the selected header, preserves physical row numbers, enforces the input-row limit, persists a corporation-and-conversation-scoped continuation checkpoint, and returns:

- the canonical mapping and exact selected columns;
- data, blank, and preamble counts;
- the missing-firm checkpoint count and a bounded sample;
- a fingerprint over the source SHA-256 and canonical mapping.

An input with no mapped firm column requires one conversational checkpoint, even when CRD or email evidence is available. Validation separately counts usable-name rows that lack firm, valid CRD, and valid email. The agent always asks whether one firm applies to every advisor. If the user supplies one in a later turn, `apply_firm_to_advisor_upload` requires the exact firm value to appear in that current user message and operates only on the latest persisted validation checkpoint from an earlier run. It deterministically creates a same-format immutable derived attachment, appends a firm column, fills only validated nonblank advisor rows, and returns an updated exact mapping. The original upload remains unchanged. The derived attachment must pass `validate_advisor_input` before reference retrieval or matching; `create_advisor_match` enforces that exact checkpoint. If no firm is available, the user may explicitly continue with weaker evidence.

`get_current_advisor_input` returns the latest persisted bounded validation checkpoint so a later clarification turn can resume with exact attachment and mapping identifiers rather than reconstructing them from model prose.

## Stage 2: retrieve and match

Only after validation and clarification does the agent call `create_advisor_match`. The tool retrieves or reuses the authoritative source for that immutable attachment, validates and projects it into a protected corporation-and-conversation-scoped CSV, and builds temporary exact CRD, email, and normalized-name indexes during the same stream. The model receives only an opaque manifest—not a path or advisor rows.

`create_advisor_match` accepts the attachment ID, exact mapping, mapping fingerprint, and the explicit missing-firm continuation flag. It:

1. resolves the attachment in the current corporation and conversation, verifies its protected path and hash, and revalidates the mapping fingerprint;
2. reuses the attachment's completed snapshot or atomically creates it from one authoritative-source iteration;
3. validates the protected path, hash, schema, row count, required names, and unique CRDs;
4. runs deterministic indexed matching;
5. persists the structured session;
6. releases the temporary index;
7. generates and reopens `advisor_matches.xlsx` for verification;
8. atomically publishes the verified workbook under an opaque artifact ID tied to the active run, match session, and revision.

The reference snapshot is created once per immutable attachment. Mapping corrections, match retries, and later review turns reuse it.

## Deterministic policy

The matching engine applies policy version 5 in order:

1. Exact trimmed CRD is decisive; CRDs are opaque strings with no digit validation or numeric extraction. Other conflicts become warnings.
2. Unique normalized email is decisive after CRD. A non-unique authoritative email is ambiguous.
3. A usable name produces an exact normalized first/last key; middle tokens are ignored, and uncommaed full names use their first and last tokens.
4. Exact indexed name requires exact/wildcard/close firm or exact city and state.
5. General fuzzy-name matching is not performed.
6. Curated nicknames and name-only evidence create review candidates but never auto-match.
7. Strong firm or state conflicts block name-based auto-matching.
8. ZIP is contextual only; street address is outside the workflow.
9. Unresolved indexed candidates are `Ambiguous Match`; missing-name-key, invalid, or unsupported rows are `No Match` with a row-level reason.

Malformed individual email or name values become warnings or row-level results. Any nonblank trimmed input CRD is usable as an opaque identifier. Completely blank rows are not advisor records. Duplicate input rows remain separate decisions and receive a duplicate-group marker.

Explicit evidence precedence ranks candidates. Close-firm similarity remains bounded within the small exact-name candidate group and its numeric value is never returned to the model or workbook.

## Stage 3: conversational review

The agent reports the interpreted mapping and counts, then pages through ambiguous rows first and no-match rows second. Automated matches are listed only when requested. Review payloads contain source row numbers, candidate CRDs, total candidate counts, truncation flags, and qualitative supporting, conflicting, and ZIP-context evidence.

The only review mutations are:

- confirm a presented candidate;
- confirm No Match;
- propose an exact unlisted CRD and confirm it in a later user turn.

The effective decision remains stored on each row. Before/after decision JSON is appended to the audit table in the same SQLite transaction as the session update. The original automated status remains on overridden rows. The unused `reopen` action and general conversational input editing are not supported. The one exception is pre-match all-rows firm augmentation through the typed deterministic tool; all other corrections require a new upload and session.

Approval may retain unresolved exceptions. A later explicit review choice creates another session revision and regenerates the workbook.

## Persistence and isolation

SQLite stores:

- corporation-scoped match sessions and input summaries;
- derived-input provenance, including the source attachment/hash, user-supplied firm, affected-row count, and appended column;
- opaque reference manifests and protected snapshot paths;
- before/after review audit records;
- two-turn manual-CRD proposals.

Protected attachments, reference files, and workbook artifacts live under `.data/users/<corp-id>/`, where `<corp-id>` is the validated readable corporation ID. Every lookup includes `corp_id`; attachments and snapshots also belong to one conversation. The agent cannot read uploads, snapshots, sessions, or workbooks through generic filesystem tools.

There is no generic chat/shared workspace, file browser, arbitrary file upload, or filesystem-wide artifact diff. The only virtual filesystem is the read-only installed-skill tree under `.data/runtime/skills`. Loopback-only services, `virtual_mode=True`, symlink/traversal rejection, disabled general-purpose subagent, limits, cancellation, and restart recovery remain in force.

The protected file layout is deliberately small:

```text
.data/
├── application.sqlite3
├── checkpoints.sqlite3
├── runtime/skills/advisor-match/
└── users/<corp-id>/
    ├── attachments/<attachment-id>/<original-or-derived-name>
    ├── advisor_references/<snapshot-id>/advisor_reference.csv
    └── artifacts/<run-id>/<artifact-id>/advisor_matches.xlsx
```

SQLite is the source of truth for ownership, hashes, sessions, decisions, audits, and artifact revisions. Files are never discovered by comparing a before/after directory manifest.

## Workbook projection

The workbook remains a deterministic four-sheet projection:

1. `Matched`—17 human-facing columns by default, with technical audit fields hidden at the right.
2. `Review Required`—20 human-facing columns, including candidate-pool size and truncation, and one row per presented candidate or no-match item.
3. `Original Input`—physical row number plus source columns in original order.
4. `Run Summary`—mapping, row counts, status counts, hashes, source-transformation provenance, snapshot ID, policy, and revision.

Names and locations are combined for readability. Headers are styled and frozen; filters, bounded widths, alternating fills, status colors, wrapping, and text-safe CRD/ZIP values are applied. User-controlled strings are forced to text to prevent formula injection. Verification rejects formulas and reconciles effective decision rows to Original Input before the file is atomically published and registered in SQLite.

## Production source replacement

The current source is a synthetic 40-row CSV. A future Snowflake adapter can stream the same projected `AdvisorReferenceSource` schema once per uploaded attachment without changing agent instructions or review contracts. The application writes the immutable snapshot and builds compact exact indexes in one pass; it never compares each uploaded name with the complete master. The model still receives only manifests and bounded candidate pages.

## Deferred profile building

Advisor profile building remains an unregistered `# TODO`. A future tool must accept an approved match session, use effective Matched CRDs only, preserve corporation scope, and create separate auditable artifacts.
