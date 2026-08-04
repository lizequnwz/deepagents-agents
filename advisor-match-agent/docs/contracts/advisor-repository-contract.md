# Advisor repository contract

`create_advisor_match` creates a complete authoritative snapshot only after input validation and user clarification are complete. Retrieval is keyed by the immutable attachment, so retries and mapping corrections reuse the completed snapshot instead of retrieving the source again.

The snapshot is an immutable protected file scoped to the active corporation and conversation. The model receives only an opaque `reference_snapshot_id`, row count, ordered columns, source kind, schema version, retrieval time, hash, and optional query ID. It never receives the advisor rows or a filesystem path.

The matching service and later exact-CRD proposals resolve the opaque ID internally, verify its path, hash, schema, and row count, and reuse the same attachment snapshot across turns. Errors are explicit for an empty or oversized source, invalid schema, blank trimmed master CRDs, missing snapshot, cross-corporation access, or integrity failure. Duplicate trimmed master CRDs return a controlled authoritative-source blocker with bounded CRD occurrence counts; they never create a completed snapshot, match session, or workbook. Partial `.building` snapshots are never registered or returned.

The synthetic adapter reads the checked-in development table. A production Snowflake adapter should implement the same streaming `AdvisorReferenceSource` boundary. The application builds exact CRD, email, and normalized first/last-name indexes during that single retrieval; bounded review pages and the opaque manifest contract remain unchanged.
