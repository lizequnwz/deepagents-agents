# Conversational review

After reporting the interpreted mapping and counts, use `list_advisor_match_results` with pages of 10 or fewer. Review `Ambiguous Match` first, then offer `No Match` rows ordered or grouped by reason. Show automated `Matched` rows only when requested. Status filters accept count keys, display labels, and `unmatched` as an alias for `no_match`.

Present source row numbers and candidate CRDs with qualitative supporting, conflicting, and ZIP-context evidence. Do not expose internal scores or assume which same-name row or candidate the user means. Apply a presented candidate or confirm No Match only after explicit direction.

An unlisted advisor requires an exact CRD. Resolve it with `propose_crd_match`, show the authoritative result, and wait for a subsequent confirmation turn before applying it. The only conversational input augmentation is one explicitly user-supplied firm applied to all validated advisor rows inside `create_advisor_match`. It is audited in the session and workbook without modifying or deriving the upload. Other factual corrections require a corrected upload and new match session.

If a prior turn failed after matching, use `get_current_advisor_match` rather than rerunning. Approval may retain unresolved exceptions. The agent never reads or edits the Excel workbook; the application persists structured decisions, appends before/after audit records, and regenerates the verified workbook after every change.
