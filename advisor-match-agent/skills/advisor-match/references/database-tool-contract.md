# Advisor database tool contract

`find_all_advisors_in_database` creates an authoritative, run-scoped snapshot for deterministic matching. The model receives only its manifest, never the advisor rows.

## Initial synthetic implementation

Input: none. The active corporation/run context is injected by the application.

Output:

- `snapshot_virtual_path`: opaque `/tmp/advisor_reference.csv` token accepted by matching tools
- `row_count` and ordered `columns`
- `source_kind`, `schema_version`, `retrieved_at`, and `sha256`
- optional production `query_id`

Errors are explicit for a missing/empty source, invalid schema, malformed or duplicate CRDs, row-limit overflow, or unavailable run context. Partial snapshots are never returned.

The synthetic adapter reads the canonical checked-in table. A Snowflake adapter should implement the same `AdvisorReferenceSource` boundary and produce the same manifest without changing the matching skill or review contracts.

## Production retrieval

Returning an entire million-row table is an initial mock convenience, not the preferred production API. The Snowflake version should use a stable snapshot/version and server-side candidate retrieval by exact CRD/email plus normalized name blocks, with pagination and query IDs. Candidate pages must be bounded and deterministic. The model must still receive only manifests and small review pages; application code may use the snapshot or candidate index internally.
