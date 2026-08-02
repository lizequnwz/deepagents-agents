# Conversational review

Use `list_advisor_match_items` with pages of 10 or fewer. Filter by status, source row, or a name already present in the uploaded session. Status accepts the count keys `matched`, `ambiguous_match`, and `no_match`, their display labels, and `unmatched` as an alias for `no_match`.

If a prior turn failed after creating a workbook or the user asks to continue, use `get_current_advisor_match_session` to recover the latest session in the current conversation. Do not rerun matching merely to recover its session ID.

Present the source row and candidate CRDs with firm/location evidence. Do not assume which same-name row or candidate the user means. Apply listed candidates only after explicit confirmation.

An unlisted advisor requires an exact CRD. Resolve it with `propose_manual_crd_override`, show the authoritative result, and wait for a subsequent confirmation before applying the proposal.

The agent never reads or edits the Excel workbook. The application persists structured decisions and regenerates the workbook after every change.
