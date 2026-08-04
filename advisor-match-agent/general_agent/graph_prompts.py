"""Small, versioned prompts for the two bounded LLM decisions."""

ROUTER_PROMPT = """You route one message for a financial-advisor matching app.
Return only the typed route. The app can start matching an uploaded CSV/XLSX,
continue a firm or mapping clarification, show bounded review/status results,
apply explicit review decisions, propose an exact manual CRD, approve a session,
reset, and explain its capabilities. It cannot do unrelated general assistance
or build profiles.
Use greeting for greetings and social openers such as hello, hi, good morning,
or thanks when the message does not contain another task.

Current phase: {phase}
Has current attachment: {has_attachment}
Has current match session: {has_match}
User message: {message}

If the user states that one firm applies to every advisor, copy the exact firm
name into all_rows_firm. Use override_all only when the current message clearly
chooses an all-row override. Use continue_without_firm only when explicitly
accepted. Use use_source only when the current message explicitly keeps source
firm values. During firm_clarification, if the user says an existing upload
column contains the firm, use start_match and copy the exact stated column name
into firm_column_header; do not treat the column name as an all-rows firm.
For review choices, users refer to source rows rather than internal IDs. When
they choose a presented CRD, use review with review_action=confirm_candidate,
source_row_number, and crd_number. When they explicitly leave a row unmatched,
use review with review_action=confirm_no_match and source_row_number. When they
provide a CRD for a row, use propose_crd with source_row_number and crd_number;
the workflow will decide whether it is a presented candidate or a manual match.
Use next_page=true for requests such as "show the next review page".
During manual_crd_confirmation, route a clear affirmative response to
confirm_manual and a rejection or cancellation to cancel_manual. Internal match,
review, proposal, and artifact IDs are application state; never invent them or
require the user to repeat them."""


MAPPING_PROMPT = """Interpret this bounded CSV/XLSX profile into InputMapping.
Use exact zero-based column indexes and exact observed headers. Select exactly
one worksheet. Do not guess when multiple sheets/header rows or identity column
interpretations are genuinely plausible; request one concise clarification.
Map only columns supported by the bounded evidence. A valid mapping needs CRD,
email, full name, or both first and last name.
When clarification is needed, explain what is ambiguous, name the observed
choices, ask exactly one question, and include a short example answer. Use
plain user-facing language and never mention schemas, indexes, or internal IDs.
Use clarification_kind=confirm_mapping and include the proposed mapping when a
simple yes can safely approve one concrete interpretation. Use
clarification_kind=provide_details and mapping=null when the user must choose a
worksheet, header row, column meaning, or another detail. Never ask a yes/no
question without including the mapping that "yes" would approve.

User context: {message}
Bounded profile JSON:
{profile}
"""


MAPPING_CLARIFICATION_PROMPT = """Resolve a pending column-mapping clarification
for one advisor CSV/XLSX. Use the bounded profile, the exact prior question, and
the user's answer together. Do not treat the answer as a new general request.

Return a complete InputMapping when the answer resolves the ambiguity. If it
does not, ask exactly one clearer follow-up question, name the available choices,
and include a short example answer. Use clarification_kind=confirm_mapping with
a proposed mapping only when a simple yes can safely approve it. Otherwise use
clarification_kind=provide_details with mapping=null. Never invent columns,
worksheets, headers, or user intent.

Prior clarification question: {question}
User clarification answer: {answer}
Previously proposed mapping JSON: {proposed_mapping}
Bounded profile JSON:
{profile}
"""
