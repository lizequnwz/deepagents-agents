# Workbook contract

Always generate and verify `advisor_matches.xlsx`, then publish it under an opaque artifact ID, with sheets in this order:

1. `Matched`: one row per effective match with compact input/advisor identity, qualitative evidence, and decision provenance.
2. `Review Required`: one row per presented candidate, or one row for a No Match with no candidates.
3. `Original Input`: source values in original column order with physical row numbers. Session-level firm overrides never alter this sheet.
4. `Run Summary`: session/revision, interpreted mapping, input counts, status counts, source/reference hashes, snapshot ID, policy version, review state, and any audited all-rows firm override.

The default view is human-first. Combine readable names and locations, keep technical audit columns at the far right and hidden by default, freeze header rows, add filters, use styled headers, alternating fills and status colors, wrap text, and size columns to cover headers plus bounded content.

Write every user-controlled string as text to prevent formula injection. Keep CRD and ZIP as text. After every creation or review change, reopen the workbook, verify the four sheets, reject formulas, and reconcile Matched plus unique Review Required items to Original Input. Only then atomically publish and register the immutable artifact with its run, session, revision, size, and hash.
