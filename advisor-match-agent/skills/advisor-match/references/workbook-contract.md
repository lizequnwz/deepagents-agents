# Workbook contract

Always create `/advisor_matches.xlsx` with sheets in this order:

1. `Matched`: one row per effective match, including authoritative advisor fields and decision provenance.
2. `Review Required`: ambiguous candidate rows and no-match rows, with at most three candidates per source row.
3. `Original Input`: selected source values in original row and column order.
4. `Run Summary`: session, counts, mapping, source/reference hashes, policy version, warnings, and review state.

Write all user-controlled strings as text to prevent formula injection. Keep CRD and ZIP as text. The deterministic tool must reopen and reconcile the workbook before returning it.
