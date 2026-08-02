# Advisor database tool contract

`find_all_advisors` creates a complete authoritative snapshot only after input validation and user clarification are complete. Call it exactly once for each new match run.

The snapshot is an immutable protected file scoped to the active corporation and conversation. The model receives only an opaque `reference_snapshot_id`, row count, ordered columns, source kind, schema version, retrieval time, hash, and optional query ID. It never receives the advisor rows or a filesystem path.

`create_advisor_match` and later exact-CRD proposals resolve the opaque ID internally, verify its path, hash, schema, and row count, and reuse the same session snapshot across turns. Errors are explicit for an empty or oversized source, invalid schema, malformed or duplicate master CRDs, missing snapshot, cross-corporation access, or integrity failure. Partial snapshots are never returned.

The synthetic adapter reads the checked-in development table. A production Snowflake adapter should implement the same `AdvisorReferenceSource` boundary. At scale, use a stable database snapshot and server-side exact lookup plus deterministic candidate blocking; bounded review pages and the opaque manifest contract remain unchanged.
