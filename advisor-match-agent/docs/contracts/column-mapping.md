# Column mapping

Inspect bounded raw rows instead of assuming row 1 is a header. A mapping names
one exact worksheet (`null` only for CSV), a one-based physical header row (or `null`
for headerless input), and at most one physical `ColumnRef` per canonical field.
Headed references carry zero-based `index` plus the exact observed `header`;
headerless references carry the index and `header=null`. The index disambiguates
duplicate headers.

Match identity must include at least one of CRD, email, full name, or the paired
first-name and last-name fields. Full name and split names are alternatives.
Profile mapping contains exactly one CRD binding.

The mapping model sees only the bounded profile and has at most three structured
attempts. It may return a proposal or a clarification description. It must not
silently guess among plausible choices. The UI can correct every proposal or
provide a complete mapping itself.

Before reference retrieval or profile generation, deterministic validation
reopens the resent in-memory bytes, checks SHA-256, worksheet, row, exact
index/header bindings, row limits, and mapping fingerprint. Entirely blank rows
are skipped, rows above the chosen header are preamble, and original source
order and values are preserved.

A missing firm does not block CRD or valid-email evidence. For weaker name-only
rows, firm handling is an explicit form choice: use the source, apply one firm
to all copied mapped rows, or continue without firm. An all-rows override never
alters source bytes or `Original Input` and is recorded in output metadata.
