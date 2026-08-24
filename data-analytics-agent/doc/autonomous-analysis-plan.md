# Autonomous Analysis Implementation Plan

## Objective

Evolve the current source-bound, human-reviewed analytics POC into an agent
that can autonomously complete a multi-step analysis, automatically present a
useful visualization for each data-bearing answer, and run SQL or statistical
Python with independently configurable approval requirements.

The intended end-to-end experience is:

1. The user asks a simple or complex business question.
2. The coordinator decides whether one retrieval is sufficient or an
   analytical plan is required.
3. For a complex request, the coordinator creates and maintains a plan, calls
   the existing specialists sequentially, evaluates each artifact, and runs
   additional SQL or statistical analysis when it materially improves the
   answer.
4. Every data-bearing answer attempts to create one business-useful visual
   automatically. Explicit chart types remain authoritative.
5. SQL and statistical Python either execute automatically or pause for review
   according to independent deployment settings.
6. The final response synthesizes all supporting evidence and preserves exact
   application-owned provenance.

## Product decisions

### Keep the coordinator as the analyst

Do not add a fourth research/planning subagent in this release. The coordinator
already owns conversation context, planning middleware, specialist delegation,
artifact inspection, and final synthesis. Strengthen that role instead.

The existing specialists remain atomic:

- one text-to-SQL assignment creates one reviewed or automatically executed
  saved SQL result;
- one statistical assignment analyzes one saved result;
- one visualization assignment creates one chart over one saved result;
- reporting composes any required same-conversation artifacts.

Multi-step analysis comes from repeated, sequential specialist assignments in
one coordinator run. Do not run concurrent text-to-SQL delegations: later
queries should be allowed to depend on earlier evidence, and review mode must
never create simultaneous SQL interrupts.

### Automatically attempt a useful visual, not an arbitrary chart

After every successful database-answer turn, the coordinator must select the
most decision-relevant chart-ready result and invoke `data-visualization`
without requiring an explicit chart request.

The visualization specialist chooses a supported chart type when the user did
not specify one. It may return `cannot_create` for empty, scalar-only,
identifier-heavy, or otherwise non-chartable results. In that case, retain a
useful table or scalar presentation; do not fabricate a one-mark chart merely
to satisfy the automation rule. A future KPI-card presentation type is outside
this release unless it is necessary to meet an accepted test case.

Intermediate investigation queries are not charted automatically. Generate
the visual after the coordinator has selected the evidence that belongs in the
user-visible answer. Explicit reports may contain multiple charts through the
existing `ReportSpec`.

### Configure SQL and Python approval independently

Add two deployment settings:

```text
REQUIRE_SQL_APPROVAL=false
REQUIRE_PYTHON_APPROVAL=true
```

These are independent booleans for the first release. Do not introduce an
`auto` risk classifier or conversation-level override yet.

- SQL defaults to autonomous execution because registered backends are
  read-only, validated, capped, and time-limited.
- Statistical Python defaults to review because the current trusted-local
  subprocess is bounded but not a production isolation boundary.
- Both values remain configurable so a deployment can review everything or
  run both execution types autonomously.

Disabling approval removes only the interrupt. It must not bypass validation,
source/thread scoping, timeouts, row caps, truncation checks, execution
budgets, exact executed-code provenance, or artifact storage.

### Make multi-result evidence explicit

The singular top-level `result_id` and `sql` contract cannot represent a
multi-step answer. Replace it rather than adding a hidden compatibility layer.

Introduce an application-owned result reference such as:

```python
class ResultReference(StrictModel):
    result_id: str
    executed_sql: str
    originating_question: str
    short_label: str
```

Revise the provider-facing coordinator response to return:

```python
primary_result_id: str | None
supporting_result_ids: list[str]
```

The trusted run manager must validate every ID against the current source and
conversation, deduplicate it, ensure that the primary result appears in the
supporting list, and resolve exact SQL and metadata from `ResultStore`.

Revise `FinalAnswer` to carry:

```python
primary_result_id: str | None
results: list[ResultReference]
```

Remove the obsolete singular `sql` and `result_id` fields from the API
contract, UI, tests, and documentation. Increment `API_CONTRACT_VERSION`.

Keep one top-level `chart` in this release; it must reference one of the final
answer's result references. Keep one top-level statistical-analysis attachment
unless an implementation test demonstrates a current requirement for multiple
statistical attachments. Reports retain their existing multi-artifact model.

## Implementation milestones

## Milestone 1: Configurable execution approval

### Settings and construction

1. Add `require_sql_approval` and `require_python_approval` to
   `data_analytics_agent/config.py`, using the environment variables and
   defaults above.
2. Pass the settings into `build_text_to_sql_subagent` and
   `build_statistical_analysis_subagent`.
3. Construct `HumanInTheLoopMiddleware` only when the corresponding setting is
   true. Do not register a no-op or compatibility middleware in autonomous
   mode.
4. Generate approval-aware specialist prompts:
   - review mode says execution pauses for approve/edit/reject;
   - autonomous mode says validated code executes immediately;
   - both modes require completion only after successful execution.
5. Keep the same execution tools and result stores in both modes.

### API and UI

1. Add `sql_approval_required` and `python_approval_required` to the health or
   data-source capability response.
2. Show the active modes as read-only sidebar metadata.
3. Do not render approval controls when a run executes autonomously.
4. Preserve the existing review UI and decision API when review is enabled.

### Required tests

- SQL review enabled produces the existing interrupt.
- SQL review disabled executes without an interrupt and preserves exact SQL.
- Python review enabled produces the existing interrupt.
- Python review disabled executes without an interrupt and preserves exact
  Python and outputs.
- All four setting combinations construct and complete correctly.
- Autonomous validation failures fail safely without creating an approval.
- Execution budgets remain effective across both modes.

## Milestone 2: Multi-step coordinator analysis

### Coordinator policy

Rewrite `AGENTS.md` and `_coordinator_prompt` around two paths:

- **Direct analysis:** use one text-to-SQL assignment when one result can
  completely answer the question.
- **Investigation:** for reports, root-cause questions, broad comparisons,
  multi-part questions, or requests whose answer requires different grains,
  use `write_todos`, gather multiple results sequentially, and revise the plan
  after each result.

The investigation instructions must require the coordinator to:

1. Define the business objective, subquestions, required result shapes, and
   material assumptions.
2. Delegate one complete text-to-SQL assignment at a time.
3. Inspect returned profiles and bounded samples before choosing the next step.
4. Use statistical analysis when uncertainty, relationships, distributions,
   forecasting, significance, or diagnostics materially improve the answer;
   do not require the user to name a statistical method.
5. Reuse suitable untruncated results and avoid duplicate queries.
6. Reconcile totals, filters, populations, date windows, and grains before
   synthesis.
7. Stop when the evidence supports the answer, the configured budget is
   exhausted, or a material ambiguity requires clarification.
8. Preserve all result IDs that materially support the final claims.

Retain the rule that text-to-SQL delegations are sequential. Remove wording
that implies a request should normally terminate after the first database
result.

### Evidence contract and trusted attachment

1. Implement the multi-result provider and final-answer schemas described
   above.
2. Update `RunManager` to resolve authoritative result references and reject
   unknown, duplicate, cross-thread, or cross-source claims.
3. Preserve deterministic ordering: primary result first, then supporting
   results in coordinator-supplied order.
4. Update the conversation store and rehydration path to retain all evidence
   references.
5. Update result presentation so every supporting artifact has an expandable
   table, exact SQL, provenance, and CSV download.
6. Keep model-facing rows bounded to the existing profile plus `head(10)`.

### Budgets and stopping behavior

Reuse the existing coordinator, task, tool, and SQL-execution budgets. Verify
that counters remain run-scoped across repeated invocations of the same named
specialist. Do not add a second planning-budget system. Change defaults only if
an end-to-end test proves that the current limits prevent the intended
three-step investigation.

### Required tests

- A simple question performs one SQL assignment.
- A complex fake-model scenario performs at least two sequential SQL
  assignments and synthesizes both artifacts.
- A later SQL assignment receives enough context to depend on an earlier
  result without copying full rows into the task message.
- The final answer exposes all and only the scoped supporting results.
- Totals or result provenance cannot be invented by the coordinator.
- Investigation resumes correctly after one or more SQL/Python review cycles.
- Rejection feedback revises only the pending step and does not lose prior
  evidence.
- Task and SQL execution limits terminate runaway investigations.
- Report generation can gather several results sequentially under both
  approval modes.

## Milestone 3: Automatic visualization

### Routing changes

1. Remove the explicit-chart-only policy from `AGENTS.md`, the coordinator
   prompt, specialist description, documentation, and tests.
2. After the analytical evidence is complete, choose the primary or most
   explanatory chart-ready result and delegate once to `data-visualization`.
3. Include in the task assignment:
   - original user question;
   - selected result ID;
   - the role that result plays in the answer;
   - explicit chart type, if supplied;
   - required result shape;
   - explicit row count or `no row count requested`.
4. Let the visualization specialist choose the chart type when none was
   requested.
5. Honor the existing one-reshape recovery cycle when a useful chart requires
   a different result shape, but count the reshape as another investigation
   step and preserve both artifacts only if both support the answer.
6. Validate that the returned chart's result ID is present in the final
   answer's evidence references.

### Required tests

- A chartable SQL answer automatically produces a chart without chart words in
  the user question.
- An explicit chart type remains a hard requirement.
- A time series selects a line/area-compatible chart; a categorical comparison
  selects a bar-compatible chart in deterministic fake-model tests.
- An empty or non-chartable result completes with no fabricated chart.
- A complex investigation charts the selected final evidence, not every
  intermediate result.
- A report can still include multiple charts through `ReportSpec`.
- Disabling the visualization feature produces a complete data answer and a
  clear capability status without another specialist call.

## Milestone 4: Documentation, examples, and end-to-end verification

Update:

- `README.md`;
- `doc/architecture.md`;
- `doc/using-the-agent.md`;
- `doc/safety-and-hitl.md`;
- `doc/reporting-capability.md` where multi-result behavior affects reports;
- architecture and sequence diagrams;
- `.env.example` or the project's existing settings template;
- curated activity labels and capability descriptions in Streamlit.

Document three example journeys:

1. simple question, autonomous SQL, automatic chart;
2. complex multi-query investigation with one statistical step;
3. fully reviewed investigation that pauses and resumes several times.

Run the complete deterministic suite and the opt-in live smoke test when model
credentials are available. The baseline before this change was 171 passed, 1
skipped.

## Primary files expected to change

- `AGENTS.md`
- `data_analytics_agent/config.py`
- `data_analytics_agent/coordinator.py`
- `data_analytics_agent/schemas.py`
- `data_analytics_agent/run_manager.py`
- `data_analytics_agent/stores.py`
- `data_analytics_agent/api.py`
- `data_analytics_agent/agents/text_to_sql/agent.py`
- `data_analytics_agent/agents/statistical_analysis/agent.py`
- `data_analytics_agent/agents/visualization/agent.py`
- `data_analytics_agent/ui/components.py`
- `streamlit_app.py`
- relevant tests under `tests/`
- user and architecture documentation under `doc/`

Prefer changing these existing seams over introducing new packages or a custom
LangGraph. Use the current dependencies and Deep Agents planning, subagent, and
HITL middleware.

## Acceptance criteria

The release is complete when all of the following are true:

- A simple business question still follows the smallest working path.
- A complex question can autonomously execute multiple sequential SQL analyses
  in one run and use the collected evidence in a direct business answer.
- The coordinator can invoke statistical analysis without the user explicitly
  naming a test when it is methodologically useful.
- Every chartable data answer attempts and normally returns an automatically
  selected, validated chart.
- Explicit chart requests and types remain authoritative.
- Non-chartable results do not receive misleading charts.
- SQL and Python approval are independently configurable.
- Autonomous execution preserves all current validation, scoping, limits, and
  exact provenance.
- Reviewed execution preserves approve/edit/reject and repeated-resume flows.
- Multi-step answers expose every material SQL result through trusted,
  source/thread-scoped references.
- Reports continue to combine multiple SQL and statistical artifacts.
- The API contract contains no obsolete singular result fields.
- The full deterministic test suite passes.

## Non-goals

- parallel SQL delegation;
- cross-source conversations or joins;
- durable production storage;
- proactive scheduled monitoring;
- a new reporting renderer;
- arbitrary model-generated Plotly/Python for regular charts;
- per-conversation approval overrides;
- production Python sandboxing;
- preserving the old singular result API alongside the new evidence contract.

## Recommended delivery order

Deliver each milestone as a working end-to-end increment:

1. configurable approval modes;
2. multi-result contract and multi-step coordinator;
3. automatic visualization;
4. UI/documentation polish and complete verification.

Do not begin by replacing the coordinator with a custom graph. First prove the
target experience using the planning, delegation, skills, checkpointer, and
conditional HITL mechanisms already present in Deep Agents.
