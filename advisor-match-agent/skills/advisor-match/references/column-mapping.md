# Column mapping

Inspect bounded raw rows instead of assuming row 1 is a header. Consider one later header row or a headerless table. Automatically proceed only when one worksheet, header interpretation, and field mapping are clear. Ask when multiple interpretations are plausible.

`InputMapping.header_row` is the one-based physical header row, or `null` for headerless input. Headed `ColumnRef` values contain both the zero-based index and exact observed header. Headerless references contain the index and `header=null`; generated labels such as `Column A` are display aids only.

Call `validate_advisor_input` before retrieving the advisor reference. It reopens the source, validates the exact worksheet/index/header bindings, reports blank and preamble rows, and returns a fingerprint tied to the source hash and canonical mapping.

Preserve source column order and values. Skip entirely blank rows. Rows above a selected header are preamble. Never infer identity data from unrelated columns. A missing firm column alone does not block rows with CRD or valid email evidence. When a usable-name row lacks firm, CRD, and valid email, `create_advisor_match` asks for one all-rows firm or explicit permission to continue with weaker evidence. An explicit all-rows firm is applied only to copied mapped values as an audited session override; the source attachment, mapping, and fingerprint remain unchanged. All other corrections require a new upload.
