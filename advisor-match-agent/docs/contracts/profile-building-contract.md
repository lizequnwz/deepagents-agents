# Placeholder advisor profile report contract

Advisor profile reporting is a supported, bounded workflow. Version 1 produces
one deterministic UTF-8 HTML document with a valid shell and an empty body. It
does not fetch, infer, or simulate advisor profile content.

The report source is exactly one of:

- a corporation- and conversation-scoped persisted match session, using only
  automated `Matched` decisions with a non-null matched advisor; or
- an immutable CSV/XLSX attachment with one validated worksheet, header row,
  and physical CRD column.

CRDs are opaque strings. Deterministic code trims surrounding whitespace,
discards blanks, and deduplicates while preserving first-seen order. Leading
zeros, punctuation, case, and nonnumeric identifiers are preserved. Master-data
membership is not required.

Ambiguous worksheet, header, or CRD-column choices require a bounded graph
clarification. The mapping is bound by physical zero-based column index and
exact observed header. The service reopens the protected attachment and checks
its hash, mapping fingerprint, row limit, and mapping before generation.

Every intentional request creates a new immutable `advisor_profile_report.html`
artifact and an additive durable report record containing its scoped source,
normalized CRDs and counts, mapping evidence where applicable, path, size,
SHA-256, and creation time. Empty inputs, cross-corporation sources, stale
mappings, corrupt files, and unsafe paths create no artifact.
