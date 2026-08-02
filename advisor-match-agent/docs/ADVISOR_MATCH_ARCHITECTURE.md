# Advisor Match implementation architecture

Advisor Match Agent has three user-facing stages and one strict ownership rule: the model interprets bounded evidence and conducts the conversation; deterministic application code owns every identity decision and workbook mutation.

The interactive workflow is also available as [advisor_match_workflow.html](advisor_match_workflow.html).

## Stage 1: interpret and validate

`inspect_advisor_upload` reads at most the configured preview bounds with `header=None`. It therefore does not assume the first row is a header. For each CSV or bounded workbook sheet it returns:

- physical raw-row previews;
- several plausible header rows with exact header values, patterns, samples, and deterministic synonym suggestions;
- a headerless view using generated display labels such as `Column A`;
- the source hash and truncation warnings.

The agent selects exactly one worksheet, a headed or headerless interpretation, and an `InputMapping`. It asks the user when more than one interpretation is plausible.

`validate_advisor_input` then reopens the upload and validates the exact worksheet, physical header row, zero-based indexes, and observed headers. Duplicate headers remain safe because the index is decisive. Headerless references use `header=null`.

Validation loads only after the structural references pass. It skips completely blank rows, excludes preamble rows above the selected header, preserves physical row numbers, enforces the input-row limit, and returns:

- the canonical mapping and exact selected columns;
- data, blank, and preamble counts;
- the missing-firm checkpoint count and a bounded sample;
- a fingerprint over the source SHA-256 and canonical mapping.

Rows with a usable name but no firm, valid CRD, or valid email require one conversational checkpoint. The user can provide a corrected upload or explicitly continue. The agent cannot edit source values conversationally.

## Stage 2: retrieve and match

Only after validation and clarification does the agent call `find_all_advisors`. The tool validates and projects the authoritative schema into a protected, immutable, corporation-and-conversation-scoped CSV. The model receives only an opaque snapshot ID and manifest—not a path or advisor rows.

`create_advisor_match` accepts the upload path, exact mapping, mapping fingerprint, opaque reference ID, and the explicit missing-firm continuation flag. It:

1. revalidates the upload and mapping fingerprint;
2. resolves the reference ID through the corporation-scoped store;
3. validates the protected path, hash, schema, and row count;
4. runs deterministic matching;
5. persists the structured session;
6. generates and reopens `advisor_matches.xlsx` for verification.

The reference snapshot is fresh for every new match session and remains fixed throughout later review turns.

## Deterministic policy

The matching engine applies policy version 2 in order:

1. Exact CRD is decisive; other conflicts become warnings.
2. Unique normalized email is decisive after CRD. A non-unique authoritative email is ambiguous.
3. A usable name is a multi-part full name or both first and last name.
4. Exact name requires an exact/close firm or exact city and state.
5. Fuzzy name requires policy score, runner-up margin, and independent support.
6. A fuzzy name plus fuzzy firm cannot auto-match without exact city and state.
7. Nickname aliases and name-only evidence create candidates but never auto-match.
8. Strong firm or state conflicts block name-based auto-matching.
9. ZIP is contextual only; street address is outside the workflow.
10. Plausible unresolved rows are `Ambiguous Match`; insufficient, invalid, or unsupported rows are `No Match` with a row-level reason.

Malformed individual CRD, email, or name values become warnings or row-level results. They do not abort other rows. Completely blank rows are not advisor records. Duplicate input rows remain separate decisions and receive a duplicate-group marker.

Internal scores rank candidates; they are not probabilities and are never returned to the model or workbook.

## Stage 3: conversational review

The agent reports the interpreted mapping and counts, then pages through ambiguous rows first and no-match rows second. Automated matches are listed only when requested. Review payloads contain source row numbers, candidate CRDs, and qualitative supporting, conflicting, and ZIP-context evidence.

The only review mutations are:

- confirm a presented candidate;
- confirm No Match;
- propose an exact unlisted CRD and confirm it in a later user turn.

The effective decision remains stored on each row. Before/after decision JSON is appended to the audit table in the same SQLite transaction as the session update. The original automated status remains on overridden rows. The unused `reopen` action and conversational input editing are not supported. A corrected upload creates a new session.

Approval may retain unresolved exceptions. A later explicit review choice creates another session revision and regenerates the workbook.

## Persistence and isolation

SQLite stores:

- corporation-scoped match sessions and input summaries;
- opaque reference manifests and protected snapshot paths;
- before/after review audit records;
- two-turn manual-CRD proposals.

Protected reference files live outside the agent-visible workspace. Every lookup includes `corp_id`; snapshots also belong to one conversation. The agent cannot read uploads, snapshots, sessions, or workbooks through generic filesystem tools.

The existing loopback-only services, `virtual_mode=True`, symlink/traversal rejection, skill-only filesystem access, disabled general-purpose subagent, limits, cancellation, recovery, and immutable turn artifacts remain unchanged.

## Workbook projection

The workbook remains a deterministic four-sheet projection:

1. `Matched`—17 human-facing columns by default, with technical audit fields hidden at the right.
2. `Review Required`—18 human-facing columns and one row per candidate or no-match item.
3. `Original Input`—physical row number plus source columns in original order.
4. `Run Summary`—mapping, row counts, status counts, hashes, snapshot ID, policy, and revision.

Names and locations are combined for readability. Headers are styled and frozen; filters, bounded widths, alternating fills, status colors, wrapping, and text-safe CRD/ZIP values are applied. User-controlled strings are forced to text to prevent formula injection. Verification rejects formulas and reconciles effective decision rows to Original Input before the file is published.

## Production source replacement

The current source is a synthetic 40-row CSV. A Snowflake adapter can implement the same `AdvisorReferenceSource` protocol without changing agent instructions or review contracts. At production scale, replace full in-memory fuzzy comparison with stable database snapshots, exact CRD/email lookup, and deterministic candidate blocking. The model must still receive only manifests and bounded candidate pages.

## Deferred profile building

Advisor profile building remains an unregistered `# TODO`. A future tool must accept an approved match session, use effective Matched CRDs only, preserve corporation scope, and create separate auditable artifacts.
