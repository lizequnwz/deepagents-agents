# Improving the analytics workspace assistant

17 October 2026. Comparative assessment and delivery rationale for the next version.
The [handoff](../../HANDOFF.md) remains the single active product plan. This document
supports its priorities; it does not describe delivered runtime behavior or authorize
provider studies. No application code was changed for this assessment.

The user subsequently prioritized all seven analytical capability families over the
initial workspace-authoring sequence below. See the [implementation outcome](capability-expansion-2026-10-17.md)
and current handoff for delivered scope and next priorities. This assessment remains
a record of the research and inspected baseline.

## Recommendation

Build the analytics workspace assistant already selected in the handoff. Extend the
current coordinator, SQL specialist, Python specialist, saved datasets and reporting
system. The next useful product should complete this journey:

**Find a calculation in a project → understand its business definition → discover
approved data → propose a repair → check the calculation → publish supported findings.**

Three investments reinforce one another:

1. Make completion, metric meaning and published numbers more dependable.
2. Add bounded workspace understanding and a few complete analytical workflows.
3. Remove repeated work through measured, isolated changes.

Keep FastAPI, Streamlit, Deep Agents, SQLGlot, DuckDB, Arrow/Parquet and fresh-process
Python. Borrow product patterns from the reference projects rather than their platforms.
Read-only workspace work can proceed alongside targeted correctness repairs; it need
not wait for every historical experiment or every later analytical method.

## What was reviewed and what the evidence establishes

| Input | Reviewed version and scope |
|---|---|
| This project | Clean starting checkout at `50048c6dfc49e65cb46196d7779a5c00640ed5f9`; HANDOFF, capability inventory, current architecture, retained reviews/studies, relevant implementation and tests |
| DB-GPT | Source at [`361eb34476970ae4dba6d33454a45669ec6851bb`](https://github.com/eosphoros-ai/DB-GPT/commit/361eb34476970ae4dba6d33454a45669ec6851bb), commit dated 11 October 2026 |
| Data Formulator | Source at [`5477f0e236426dc8f74a498ec400414fba7fbc0f`](https://github.com/microsoft/data-formulator/commit/5477f0e236426dc8f74a498ec400414fba7fbc0f), commit dated 15 August 2026 |
| Conference package | Daily notes, application roadmap/demo notes, grounding/evaluation reviews and source audits under the supplied `ai-engineer-nyc-2026` directory |

The upstream implementations were inspected, not executed. No comparative accuracy,
deployment-security or usability claim follows from reading their code. The conference
archive mixes attendee recollections, program research, proposed transfers and editorial
synthesis; its field guide includes pre-conference planning. These are inputs to local
hypotheses, not measured improvements in this app.

Current local verification: **107 tests passed** across Snowflake, semantic grounding,
forecast evaluation, execution budgets and reporting. One existing Starlette/httpx
deprecation warning appeared. This was a focused run, not a full-suite rerun. No model,
warehouse, browser or upstream application was invoked. Historical suite counts and
the unfinished provider studies retain their original limits.

## Start from the capabilities that already work

The app already has reviewed uploads, typed saved snapshots, explicit analytical
inputs, shared population filters, warehouse refresh, iterative Python, forecast
evaluation, versioned charts, required HTML reports, portable replay and interruption
recovery. These are foundations, not new roadmap features. See the
[delivery inventory](../roadmap/implementation-progress.md).

The broader workspace, general project research, code authoring and assignment-scoped
source selection remain planned. Current runtime policy still permits one configured
source or one reviewed uploaded table per conversation. Reading more documents must
not silently broaden analytical permissions.

### Concrete gaps confirmed in the current code

| Gap | Current evidence | Required improvement |
|---|---|---|
| Joined counts can bypass business-grain checks | [Fan-out checks](../../data_analytics_agent/semantic_sql.py) inspect `Sum`/`Avg`; source execution permits empty `metric_names` | Distinguish business KPI, explicit custom calculation and raw extract; validate counted entity, distinctness, denominator and join grain |
| Snowflake result types depend on returned values | [Adapter](../../data_analytics_agent/backends/snowflake.py) infers arrays per batch and emits strings for empty results | Use declared cursor result metadata, including decimals/dates/timestamps, all-null and empty batches |
| Completed forecasts need not use the strong evaluator | [finish_analysis](../../data_analytics_agent/agents/data_analysis/tools.py) accepts an optional descriptor and otherwise requires only a successful execution | Declare forecast intent with the assignment; require saved final predictions and evaluation, or a supported partial outcome |
| Exploratory outputs can remain in the final report | [Report resolution](../../data_analytics_agent/reporting/tools.py) includes outputs from every successful execution | Select final output references; retain superseded attempts in inspectable provenance, with only necessary producers in runnable replay |
| Metric meaning is lost in saved SQL reshaping | [query_saved_results](../../data_analytics_agent/agents/text_to_sql/tools.py) saves SQL bindings without `metric_columns` | Propagate identity through provably transparent projections; withhold it for altered calculations |
| Refresh checks shape more strongly than meaning | [Refresh binding](../../data_analytics_agent/presentation.py) checks fields/types and copies the previous grain text | Compare declared keys, time bucket, measures and scope, and check full-result key uniqueness |
| Quantitative prose and units remain less constrained than cards | [Report schemas](../../data_analytics_agent/reporting/schemas.py) allow free narrative values and prefixes/suffixes | Reuse stored-value/comparison bindings for material quantitative leads, callouts and infographic values |
| Hard call limits skip the partial-report recovery path | [Budget middleware](../../data_analytics_agent/execution_budget.py) raises errors; [run manager](../../data_analytics_agent/run_manager.py) specially recovers wall-clock exhaustion | Normalize budget exhaustion and finish from committed evidence within a bounded presentation allowance |

These are code-established gaps and associated risks. They are not eight newly observed
production failures. Passing existing tests does not cover missing acceptance cases.

## Lessons to adopt selectively

### DB-GPT: workspace tools and disciplined extensions

Adopt bounded list/glob/search/line-read tools over approved project roots. DB-GPT binds
workspace identity in application code and supports targeted lexical access; its
[workspace tools][db-workspace] are a useful reference. Start with Markdown, SQL, Python,
YAML and plain text, stable path/hash/line citations, and documentation research.
Add richer document parsing only when a task needs it. Reuse existing permission and
artifact mechanisms rather than building a knowledge platform.

Keep documents separate from analytical tables. DB-GPT's [session-file domain][db-files]
provides useful attachment identity/lifecycle patterns. A design document may explain a
metric; its preview is not an analytical population, accepted metric or permission.

Use existing skills for repeatable query repair, semantic authoring, change explanation
and reconciliation. DB-GPT's [skill tool][db-skills] demonstrates dynamic loading, but
this app already has that mechanism. Its [CSV workflow][db-csv] also illustrates why
computation and narration should remain separate. Do not require full EDA or a
"root cause" narrative for every question.

Use hierarchical object/field narrowing from its [schema retriever][db-schema]. Keep
lexical discovery first, then test whether embeddings rescue actual vocabulary misses.
For future workspace outputs, borrow bounded previews and rereading from its
[context storage][db-context], reusing this app's saved references. Avoid a second store
or compaction system.

Treat isolation as a concrete execution design. DB-GPT's [runtime factory][db-runtime]
defaults to local execution; explicitly selected container execution refuses local
fallback if initialization fails. Its [network setting][db-network] defaults to enabled
networking. The README's sandbox wording therefore does not establish isolated defaults.
Before exposing arbitrary workspace execution, choose one isolation implementation,
copy only declared inputs, withhold source credentials, disable network by default,
bound resources, collect artifacts and test cancellation/cleanup. Retain the current
local runner for the existing local product until that separately scoped design is needed.

Do not adopt AWEL, a connector marketplace, several sandbox backends, a vector service
or generic SQL tool execution. The reviewed [SQL chat tool][db-sql] uses a prefix guard
and bounded Markdown preview; it is not a replacement for this app's SQL validation,
complete typed evidence and source ownership.

### Data Formulator: direct manipulation and visible exploration

Adopt field-aware chart controls from [ChartQuickConfig][df-chart]. Extend the current
title/label/palette/type edits with validated x/y/series choices for bar and line charts
over existing complete saved data. Show only compatible options. Changing a field or
series binding starts an analytical turn, even without new computation: switching revenue
to units can invalidate the previous explanation. Reuse saved inputs, create a validated
chart/report revision and revalidate affected summaries and value bindings. Any new
aggregation, filter, calculated field or population change also needs an analytical turn;
the display path must not create hidden analytical transformations.

Add "Explore from this result" and a compact branch history before building a canvas.
Data Formulator distinguishes an [authored parent from actual derived inputs][df-lineage].
Keep that distinction: navigation history explains where an exploration began;
`parent_result_ids` and exact input bindings establish computation lineage. Reuse existing
immutable chart/report/result IDs and compare revisions without changing their originals.

Offer up to three useful actions for a selected complete snapshot, initially from
deterministic templates: compare supported periods, explain a change, inspect a segment.
Data Formulator's [suggestion caching][df-suggestions] and [focused/peripheral context][df-context]
are useful patterns. Cache by immutable input and accepted-definition version; suggestions
must use known fields, grain and supported relationships. Selection starts the ordinary
scoped workflow. Avoid another suggestion agent unless it earns its cost.

Use visible, reviewed workspace knowledge rather than silent learning. Its
[knowledge panel][df-knowledge] makes reusable rules editable. Start with proposed/accepted
definitions carrying source references and a version; stale or conflicting definitions
must remain visible. User corrections alone do not establish shared business truth.

Reject permissive generative restyling: the upstream [style prompt][df-restyle] permits
filters, aggregates and calculated fields, while its [guardrail][df-restyle-guard]
primarily removes the top-level data block. Preserve this app's stronger presentation
allowlist. Also reject a frontend rewrite, a full graph layout system, unconstrained
Markdown reporting and importing the unified upstream agent loop wholesale. Reporting
already belongs to the coordinator; SQL/Python separation has useful execution ownership.

### Conference lessons: evaluate accepted work and change one thing at a time

The most directly applicable sources are the package's
[grounding review](/Users/charlie/Documents/Codex/2026-10-10/che/github-package/ai-engineer-nyc-2026/work/applications-grounding-review.md)
and [evaluation review](/Users/charlie/Documents/Codex/2026-10-10/che/github-package/ai-engineer-nyc-2026/work/applications-eval-review.md),
which examine this repository specifically. Their code observations were checked again
for this assessment.

- Treat a fact as a value plus population, period, unit, definition and source version.
  Strengthen current contracts and value bindings before adding a generic verifier.
- Turn expert task procedures and actual failures into small reviewed skills and regression
  cases. The [Range notes](/Users/charlie/Documents/Codex/2026-10-10/che/github-package/ai-engineer-nyc-2026/outputs/ai-engineer-nyc-2026-day-2-notes.md:169)
  motivate this mechanism; they do not establish capacity or ROI in this app.
- Scope context to the current task while preserving required definitions. The
  [Bridgewater notes](/Users/charlie/Documents/Codex/2026-10-10/che/github-package/ai-engineer-nyc-2026/outputs/ai-engineer-nyc-2026-day-1-notes.md:27)
  support a retrieval hypothesis, not a retrieval-size default or measured speedup here.
- Measure accepted task quality, first-correct time, all-attempt cost and review effort.
  Adoption, a successful report and smaller prompts are insufficient success criteria.
- Simplify through isolated experiments. The
  [Ramp notes](/Users/charlie/Documents/Codex/2026-10-10/che/github-package/ai-engineer-nyc-2026/outputs/ai-engineer-nyc-2026-day-2-notes.md:124)
  do not establish an optimal number of skills. Locally, the retained prompt-removal
  candidate failed all three metadata repetitions after a unique terminal instruction
  was removed. Preserve that lesson and its test-dependent receipts.

## Target design: small contracts, existing components

Keep three distinct concepts within the current storage and graph design:

| Concept | Minimum useful contents | Authority |
|---|---|---|
| Workspace context | Approved roots/URLs; referenced path or URL, hash/version, relevant lines; accepted definitions and decisions | Helps understand the task; does not authorize data execution |
| Analytical assignment | Question; approved source/objects; exact saved inputs; population; measure/custom formula; grouping/date role; known grain/units/completeness | Defines one specialist's task and source permission |
| Final evidence | Selected saved outputs, calculations and checks; limitations; published findings and report references | Supports the answer and reproducible artifact |

Extend current dataset and assignment models where the first workflow needs structured
keys, time bucket, units, metric identity and definition version. Permit explicit unknown
values; do not introduce a universal ontology or arbitrary analysis-method registry.
Reuse SQLGlot lineage for transparent SQL, Arrow metadata for types, existing stores for
references, and existing review/correction/publication mechanisms.

Workspace chats should create and restart without a dataset or initializing a default
warehouse. Source execution remains unavailable until application code validates a
deliberate approved source/object binding and population for the assignment. Bound tools
retain exact source/input checks and reject artifacts from another source or outside the
selected population; broader retrieval still requires the existing scope-expansion
decision. Begin with one warehouse and approved schemas per assignment. Cross-schema
access within that warehouse is distinct from federation, multiple uploaded tables or
warehouse/file enrichment. No new user-visible mode is required.

SQL keeps warehouse execution and descriptive shaping. Python uses complete named saved
inputs and can request more data through the existing clarification/SQL path. Source
assignments remain sequential. Independent Python tasks may share complete inputs with
bounded concurrency. Never use a chart sample as an analytical input.

Draft definitions, raw exploration and reviewed business metrics must be distinguishable.
A proposed join or matching column name does not establish an accepted relationship.
Reports remain required for data-backed findings; explanation/research can be short,
and authoring can produce a proposed file/diff. General workspace tools cannot bypass
exact execution review, source ownership or evidence capture.

## Delivery sequence and acceptance

Each slice leaves a usable product. The order below is a dependency proposal, not a
calendar estimate. Evaluation and deletion work accompany every slice.

### 0. Close specific correctness contracts

Split this work into focused changes, rather than one large schema refactor:

| Change | Main implementation surfaces | Acceptance cases |
|---|---|---|
| 0a. KPI/count contract | SQL tool and semantic validator | Two invoices joined to three lines cannot publish three as invoice count; legitimate line counts, distinct entities, rates and custom formulas remain expressible; raw extracts stay simple |
| 0b. Declared Snowflake result types | Snowflake adapter and typed extraction | Empty/all-null decimals/dates/timestamps retain declared types; leading all-null batches do not break later batches; precision and timestamp semantics survive |
| 0c. Final analysis completion | Analysis assignment, `finish_analysis`, report resolution, exports | Forecast intent cannot be hidden by omitting its descriptor; predictions/scores/windows are required for completion; an exploratory estimate replaced by a corrected estimate is excluded from final outputs but retained in provenance |
| 0d. Meaning through reshape/refresh | Saved SQL lineage, analytical scope, refresh binding | Aliases/projections preserve canonical identity; scaled/reaggregated outputs do not inherit it; same-schema changed grain/duplicate keys/changed measures cannot masquerade as equivalent refreshes; typed empty valid refresh remains supported |
| 0e. Bound quantitative claims | Existing report schemas/resolvers/publication | Bound headline/card/callout values agree after rounding; unsupported currencies/percent semantics and out-of-scope references fail; unknown units remain unknown |
| 0f. Budget completion | Budget middleware and run manager | Coordinator or specialist model/tool/time exhaustion preserves committed evidence, stops computation and produces supported partial findings/report when possible; no evidence yields an honest explicit unfinished outcome |

For 0d, check declared contracts and full-result keys; arbitrary semantic equivalence
cannot be proved from output shape. Unknown equivalence should request a scope decision,
not copy the old grain label. For 0e, start with material quantitative components and
reuse the metric resolver; do not build regex policing of all prose or claim universal
narrative verification. For 0f, reserve bounded presentation capacity without resetting
computation limits or reopening SQL/Python execution after exhaustion.

### 1. Add read-only workspace understanding

Allow a conversation without a selected analytical source. Add approved-root file
listing, glob/lexical search, bounded reading and documentation research. Keep retrieved
content as data; use hashes/versions and exact citations. Start with plain project files
and bounded path/hash references. Limit bytes/results across the whole turn, not only each call.
Keep accepted definitions explicit and separate from discovered text.

Acceptance: find a retention definition and implementation, identify a denominator mismatch
with cited lines, answer a metadata-only question without SQL or a report, and refuse
out-of-root/symlink escapes. Create/restart a source-neutral chat with the warehouse
unavailable; source tools must remain unusable before an approved assignment binding.
After binding, reject cross-source artifacts and preserve selected-population expansion
rules. A changed file invalidates its cached reference; restart and follow-up preserve
citations. No document grants new source access. This independent slice can proceed
while slice 0 is completed.

### 2. Discover approved objects and draft semantics

Fix qualified database/schema/object identity in the Snowflake readiness path before
claiming cross-schema support. Add bounded physical metadata browsing across approved
schemas. Narrow fields/dates with selected objects and measure dependencies. Support
proposed metric definitions, date roles and relationships with explicit review status.
Permit explicitly scoped raw-data exploration without labeling a custom calculation as
a curated metric. Keep reviewed OSI meaning authoritative.

Acceptance: same-named tables in two schemas remain distinct; inaccessible/unapproved
objects stay excluded; proposed joins never execute as accepted relationships; ambiguous
dates produce useful clarification. A sales/returns/targets example aggregates separate
facts to compatible grain, preserves unmatched groups and reconciles separate totals.
Local fake-adapter/synthetic fixtures precede any separately authorized warehouse checks.

### 3. Complete the project-to-checked-result journey

Add SQL/Python authoring as an inspectable proposed diff using existing workspace and
review records. Begin with static checks and the existing owned SQL/Python execution
paths. Save exact accepted/executed code and distinguish a draft from a checked change.
Apply bounded file edits only within declared writable workspace scope; recheck file
identity before applying a diff. Do not expose arbitrary shell execution as a shortcut.

Acceptance: locate the definition and query, propose a denominator repair, validate the
SQL, run against approved data, save the comparison and explain the result in an HTML
report with the proposed diff attached. A rejected/stale diff changes nothing. Source
expansion uses the existing explicit decision. A failed check cannot become a verified
finding. New unrestricted code checking waits for an explicit isolation design.

### 4. Deliver change explanation and reconciliation

Add two tested skills over complete saved evidence. Start with SQL descriptive
decomposition; use Python only when inference or another analytical method requires it.

- **Explain a change:** total change, segment contributions, reconciled residual,
  denominator/composition shifts and limitations. Arithmetic contribution is not cause.
- **Reconcile:** align measure definitions, dates, units, grain and populations; preserve
  unmatched entities and explain exactly why totals differ.

Acceptance: contributions plus residual equal the total under declared tolerances;
duplicates, missing groups, zero denominators and unit mismatches have explicit outcomes.
Save contribution/reconciliation tables, use a purposeful waterfall where useful, and
bind quantitative interpretation to final outputs. Add cohorts/retention or funnels only
after selecting a concrete task with eligibility, event ordering and observation-window
rules. Rolling forecast evaluation follows the completed-forecast contract, not vice versa.

### 5. Make saved evidence easier to explore

Deliver in this order: compatible field/encoding controls → selected-input action
suggestions → branch history and comparison. Use the current chart renderer, scope forms,
and immutable results. Only display-only edits use the current atomic presentation path,
which preserves report prose. Field/series rebinding uses an analytical turn and revalidates
affected explanations and value bindings, reusing saved data when sufficient. Begin with
a simple branch list and two comparable revisions; a graph canvas is unnecessary.

Acceptance: a presentation edit performs no source/model call and preserves numerical
meaning; a filter/aggregation creates a new analytical turn; stale edits preserve the old
view; changing revenue to units cannot retain the revenue narrative; analytical actions
use the complete parent input. Users can identify the current
population and distinguish an original, a branch and a refresh. Rendering tests cover
offline HTML, console/CSP errors, wide tables, narrow windows, keyboard access and print;
human task observations establish usability separately.

## Simplification and ablation program

Do not postpone simplification until the end. Delete genuinely unused code and obsolete
documentation when references and checks establish they are unused. Remove replaced
paths after adoption; use a fresh storage contract when needed, without migrations,
compatibility readers or production experiment flags.

For behavior, isolate one hypothesis in an evaluation checkout. Keep correctness fixes
and shared product behavior identical in both variants. Reuse the current runner,
receipts, grader and comparator. These are proposed experiments, not adopted removals:
verify each hypothesized source of redundant work still exists in current traces; drop
obsolete experiments rather than recreating redundant behavior for a comparison.

| Order / candidate | Compare | Evidence and decision rule |
|---|---|---|
| A1. Redundant discovery | Current routing versus SQL-owned detailed grounding with no repeated coordinator lookup | Reuse the retained routing protocol. Metadata-only discovery stays; grade role/date/join coverage and every complete snapshot; adopt only without new quality/boundary failures and with its 15% speed gate |
| A2. Repeated policy text | Remove one demonstrably duplicated instruction, retaining a single effective owner | Inventory AGENTS, owner prompts, skills and tool descriptions first. Preserve terminal response, publication and report-completion instructions. Exercise direct metadata, clarification, failure and recovery; the rejected broad patch remains rejected |
| A3. Context payloads | Current handoff versus focused references plus compact peripheral index | Same definitions/inputs/task; check missing-context errors, repeated reads, task correctness, token volume and first-correct time; reference reduction cannot hide evidence |
| A4. Parallelism | One Python worker versus current bounded workers on genuinely independent tasks | Same complete inputs; assess accepted outcomes, peak combined memory, latency, ordered reviews and interruption/restart. Use serial execution if concurrency adds resource cost without useful gain |
| A5. Loading/materialization | Current full Arrow/pandas loading versus narrow complete inputs and trusted Arrow/DuckDB scanning | Mechanical comparison of full outputs, nulls/types and lineage; measure peak memory and scan time. Preserve external-access-disabled agent SQL. Avoid automatic row sampling or another compute service |
| A6. Workflow knowledge | Generic method guidance versus one focused change/reconciliation skill | Grade complete tasks, independent reconciliations, clarification quality, invented causes and review effort; adding a skill must improve an observed task |
| A7. Interaction cost | Conversational edits versus direct validated controls; deterministic versus generated suggestions | First test valid outcomes, then observe successful edits/population recognition and measure time/provider cost; use deterministic suggestions unless generation adds demonstrated value |

Retain role-batching and join-feedback protocols for their exact hypotheses. Batched
discovery/structured feedback are already delivered, while their comparative model
studies remain incomplete. A local payload reduction does not establish a live speedup.
Do not introduce legacy runtime modes merely to recreate historical variants.

Specialist removal, a single-agent replacement and file-only delegation bypass are
later hypotheses if telemetry identifies material handoff cost. The current evidence
does not justify them. Keep SQL source ownership, review/corrections, reporting, scope
binding and recovery. Check installed dependency behavior before deleting apparent
middleware duplication; the installed Deep Agents implementation merges middleware by
name, so a second-looking declaration is not itself proof of a duplicate runtime layer.

Split cohesive API/store responsibilities only when a delivery slice touches them and
the split gives clear ownership. Moving methods into many files is not a demonstrated
latency or maintainability improvement. Reject a generic event bus, universal critic,
method registry, persistent kernel and second artifact renderer/storage layer.

## Evaluation that can support decisions

Extend the existing 40-case synthetic corpus and grading workflow rather than starting
another framework. Add known outcomes for the gaps above and full workspace journeys.
Grade numerical values at named stored bindings, full key/group coverage, measures,
population, date roles, join grain, units, final-output selection and report agreement.
The current live test's "expected total anywhere" and analytical keyword checks remain
smoke diagnostics, not numerical or method correctness criteria.

Build a small offline calibration pack containing wrong population with correct
arithmetic, same-row-count wrong joins, invented currency, missing clarification,
unsupported refresh equivalence and conflicting report numbers. Version the rubric;
blindly double-review a sample and adjudicate disagreement. Keep development/regression
cases separate from final assessment by exposure history, not filename alone. Do not
train prompts or retrieval examples on the final assessment answers.

For behavioral provider studies, retain three fresh repetitions per variant, frozen
fixtures/settings/dependencies, all failed/partial receipts, independent snapshot
reviews and first-attempt errors. Existing semantic speed protocols require at least
15% lower median paired active time to the first correct snapshot with no new quality
or boundary regression. Quality candidates must resolve their declared paired failures
without new first-attempt/outcome regressions. Incomplete or unreviewed evidence remains
inconclusive. These gates support the declared change, not broad equivalence of agents.

Track accepted-task rate and serious false passes first; then first-correct active time,
repairs/redundant calls, known or explicitly estimated all-attempt cost, active review
minutes and peak memory. Keep missing usage/cost unknown. Exclude approval waits from
active machine time; do not confuse waiting with reviewer labor. Preserve failures in
cost accounting while keeping invalid pairs out of quality-qualified speed estimates.

Verification remains local under the existing handoff. New provider trials need explicit
authorization for provider and fixture contents; this plan does not request or imply it.
Human usability studies and broader warehouse checks remain separately evidenced work.

## First implementation choices

Start with **0a, the KPI/count-grain contract**, including a failing joined-count fixture
and legitimate extract/custom-calculation controls. Ship **0b, declared Snowflake types**
as an independent repair. In parallel, build **slice 1, read-only workspace understanding**.
These give both a correctness improvement and a visible new capability without waiting
for a platform redesign or a large provider experiment.

Next complete forecast/final-output evidence and metric/refresh meaning before releasing
new analytical branching or cross-schema results. Keep the source-neutral workspace UI
working while analytical assignment contracts grow. Choose the next removal experiment
from observed redundant calls or memory pressure, not a desired reduction in agent count.

[db-workspace]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/kb_tools.py#L12-L142
[db-files]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-serve/src/dbgpt_serve/session_file/domain.py#L9-L101
[db-skills]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/skill_tools.py#L9-L210
[db-csv]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/skills/csv-data-analysis/SKILL.md
[db-schema]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-ext/src/dbgpt_ext/rag/retriever/db_schema.py#L121-L234
[db-context]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-core/src/dbgpt/agent/core/context/storage.py#L305-L440
[db-runtime]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-sandbox/src/dbgpt_sandbox/sandbox/execution_layer/runtime_factory.py#L14-L51
[db-network]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-sandbox/src/dbgpt_sandbox/sandbox/execution_layer/base.py#L47-L65
[db-sql]: https://github.com/eosphoros-ai/DB-GPT/blob/361eb34476970ae4dba6d33454a45669ec6851bb/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py#L9-L112
[df-chart]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/ChartQuickConfig.tsx#L182-L236
[df-lineage]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/components/ComponentType.tsx#L418-L447
[df-suggestions]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/SimpleChartRecBox.tsx#L397-L423
[df-context]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/agents/context.py#L56-L127
[df-knowledge]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/KnowledgePanel.tsx#L4-L12
[df-restyle]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/agents/agent_chart_restyle.py#L38-L56
[df-restyle-guard]: https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/agents/agent_chart_restyle.py#L300-L325
