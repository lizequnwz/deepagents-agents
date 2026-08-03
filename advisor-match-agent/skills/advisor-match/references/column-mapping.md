# Column mapping

Inspect bounded raw rows instead of assuming row 1 is a header. Consider one later header row or a headerless table. Automatically proceed only when one worksheet, header interpretation, and field mapping are clear. Ask when multiple interpretations are plausible.

`InputMapping.header_row` is the one-based physical header row, or `null` for headerless input. Headed `ColumnRef` values contain both the zero-based index and exact observed header. Headerless references contain the index and `header=null`; generated labels such as `Column A` are display aids only.

Call `validate_advisor_input` before retrieving the advisor reference. It reopens the source, validates the exact worksheet/index/header bindings, reports blank and preamble rows, and returns a fingerprint tied to the source hash and canonical mapping.

Preserve source column order and values. Skip entirely blank rows. Rows above a selected header are preamble. Never infer identity data from unrelated columns. If the firm column is absent and the missing-firm checkpoint fires, always ask whether one firm applies to every advisor. An explicit user-supplied all-rows firm may be added only through `apply_firm_to_advisor_upload`, which creates an audited immutable derived attachment. Validate its returned attachment and exact mapping. If no firm is available, require explicit permission to continue with weaker evidence. All other corrections require a new upload.
