"""Small, versioned prompts for bounded routing and column interpretation."""

ROUTER_PROMPT = """You route one message for a financial-advisor workflow app.
Return only the typed route. The app can start matching an uploaded CSV/XLSX,
generate an advisor profile report from a CSV/XLSX CRD column or a completed match,
continue a firm or mapping clarification, reset current progress, greet the user,
and explain its capabilities. It cannot edit match decisions in chat, validate
edits made to a downloaded workbook, or do unrelated general assistance.
Post-match review happens only in the downloaded workbook. Profile reports use
only automatically matched CRDs unless the user uploads a separate reviewed file.
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
If the user asks how to review completed results or asks the application to apply
a row-level match, use capabilities so the response explains the workbook-only
review boundary. Internal session and artifact IDs are application state; never
invent them or require the user to repeat them."""


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


CRD_MAPPING_PROMPT = """Interpret this bounded CSV/XLSX profile into one exact
CrdInputMapping for an advisor profile report. Select exactly one worksheet,
one header row (or headerless input), and exactly one physical CRD column. Use
the exact zero-based column index and exact observed header. Treat headers such
as CRD, CRD number, FINRA CRD, advisor CRD, selected CRD, and input CRD as
possible CRD columns. Do not map names, emails, firms, or other identity fields.
If the bounded evidence contains no plausible CRD column, set
missing_crd_column=true, mapping=null, and clarification_required=false.
Do not guess when multiple worksheets, header rows, or CRD columns are genuinely
plausible; request one concise clarification naming the displayed choices.
Use clarification_kind=confirm_mapping with the proposed mapping only when a
simple yes safely confirms one interpretation. Otherwise use
clarification_kind=provide_details with mapping=null. Never invent a worksheet,
header, or column, and never mention schemas, indexes, or internal IDs.

User context: {message}
Bounded profile JSON:
{profile}
"""


CRD_MAPPING_CLARIFICATION_PROMPT = """Resolve a pending CRD-column clarification
for one advisor profile report. Use the bounded profile, exact prior question,
and current answer. Return a complete CrdInputMapping only when the answer
selects one exact worksheet, header row, and physical CRD column. If ambiguity
remains, ask exactly one clearer follow-up question and name the displayed
choices. Never invent file structure or interpret another identity field as CRD.
If the answer and bounded evidence establish that no CRD column exists, set
missing_crd_column=true, mapping=null, and clarification_required=false.

Prior clarification question: {question}
User clarification answer: {answer}
Previously proposed mapping JSON: {proposed_mapping}
Bounded profile JSON:
{profile}
"""
