# Data Analytics Agent: review and improvement plan

3 October 2026. This review covers the current working tree, including its
uncommitted changes, `HANDOFF.md`, current guides, agent code, and relevant tests.
Recommendations are proposals. No agent implementation was changed.

Later on 3 October, the user selected the broader analytics workspace direction.
The [handoff](../../HANDOFF.md) now owns that direction and the active priorities.
The analysis below remains useful evidence; its dedicated-analyst delivery order
is superseded. Completed release reviews were subsequently consolidated into
the [historical checks](README.md#earlier-implementation-checks).

## Analysis

The agent has a useful foundation. It preserves data, calculations, and reports.
It can continue an investigation across turns and recover after interruption.
The main opportunity is to make its answers more correct and its business tasks
more complete. More agents or a new execution framework are not the first need.

The strongest next version would let a user find approved data across a warehouse,
choose clear business measures, and get checked analysis across schemas. It would
show which population and calculation support each answer. It would also provide
tested workflows for common business questions.

### 1. What is already strong

- **Clear ownership.** The coordinator owns the answer and report. SQL owns source
  access and descriptive calculations. Python works with named saved datasets.
- **Durable evidence.** Typed data, exact code, lineage, charts, and reports survive
  restart. The application attaches references rather than asking the model to
  reproduce them.
- **Useful follow-ups.** Users can select a saved population, refine it, change a
  chart, or refresh warehouse evidence as a new revision.
- **Iterative analysis.** Python can inspect data, save intermediate datasets,
  repair code, and continue. A persistent kernel is not needed for these tasks.
- **Recovery and inspection.** Reviews, corrections, Stop/Resume, report retry,
  downloads, and portable replay are already supported.
- **A sound semantic boundary.** Candidate discovery is distinct from exact
  definitions. The validator checks declared objects, relationships, composite
  keys, and selected canonical measures. Many sum and average duplication risks
  are already blocked.

These features should remain the base for new work. They reduce the risk of
answering from the wrong data or losing a successful investigation.

### 2. SQL generation and query reasoning

The largest SQL gap is business correctness after a query becomes valid SQL.
The current checks provide useful protection, but they do not prove that every
query answers the question at the correct grain.

**A count can still be wrong after a valid join.** Canonical metric selection is
optional. Duplication checks inspect sums and averages, but do not cover ordinary
counts in the same way. A local synthetic probe joined two invoices to three
invoice lines. A query labeled `invoice_count` passed validation without a
canonical metric and returned three. Selecting the canonical invoice count
rejected that shape. Existing sum protection also worked.

Require the selected measure and counted population to be clear for a business
KPI. Check denominators, distinct counts, weighted rates, and the grain before and
after joins. Keep custom calculations available, with explicit definitions.
Raw extracts still need their own simple path.

**Query reasoning should leave a short, inspectable record.** For a complex query,
record the requested measure, population, grouping, date role, and join route.
Use this record to check coverage and explain corrections. Do not expose private
model reasoning or require a plan for a simple total.

Add targeted checks when a join or calculation can change the answer: duplicate
keys, unmatched rows, lost groups, and totals before and after a join. These checks
should support the requested analysis. Metadata-only questions should not trigger
data profiling.

For complex warehouse queries, consider an execution-plan check where the backend
supports it. Use it to catch invalid objects, dialect errors, and expensive query
shapes before a full run. It cannot establish business correctness. The
[dbt join design](https://docs.getdbt.com/docs/build/join-logic) provides a useful
reference for cardinality rules, separate fact aggregation, and plan validation.

### 3. Semantic discovery

The current lexical search is a reasonable first implementation. It searches
names, descriptions, and synonyms. It supports role batching and exact selection.
The problem to solve first is whether the agent selects the right meaning.

Discovery should follow business roles: measure, dimension, filter, time, and
relationship. Once a measure is selected, use its dataset dependencies to narrow
date and dimension candidates. Distinguish order date, shipment date, accounting
date, and customer creation date. A general request for a monthly result does not
identify the correct date by itself.

Add concise domain and ownership information. Make it easier to distinguish
current operational tables from archives, staging tables, and alternative metric
definitions. Show what is known, what is missing, and what needs clarification.
Do not turn a retrieval score into a confidence score for the answer.

The retained local probe found the expected roles with dataset hints. A broad date
browse omitted the target until the dataset was narrowed. This is a browsing
limit, not proof of a natural-language retrieval failure. Test held-out questions
without those hints before changing retrieval technology.

Use reviewed examples for repeated, observed query failures. Keep their source,
business meaning, review status, and catalog version clear. Keep evaluation
questions separate. The existing examples are context examples, not verified SQL.
Snowflake's
[Verified Query Repository](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository)
and the
[Genie knowledge store](https://docs.databricks.com/aws/en/genie-agents/concepts)
show useful patterns for reviewed business definitions and query examples.

A vector index should remain conditional. It is useful only if measured vocabulary
misses justify its added cost and maintenance.

### 4. Data discovery, schema discovery, and cross-schema work

Semantic discovery and physical schema discovery are different capabilities.
Today, the agent searches an approved semantic catalog. It does not provide a
general inventory of accessible warehouse schemas and tables.

**The Snowflake readiness path is a concrete cross-schema blocker.** It reads
columns from `CURRENT_SCHEMA()` and matches bare table names. Catalog loading
requires all declared physical sources to pass this check. The semantic binding
and SQL code already retain qualified source names, but that does not provide a
working cross-schema product end to end.

First make database, schema, and object identity consistent. Duplicate table names
in two schemas must remain distinct. Then add a bounded inventory of approved
schemas, tables, columns, types, descriptions, and relationships. Search this
inventory by business domain. Snowflake's
[Information Schema](https://docs.snowflake.com/en/sql-reference/info-schema)
already provides object metadata under the active role's privileges. Apply the
application's approved scope as well.

Keep physical facts separate from reviewed business meaning. A column type does
not establish a metric definition. A similar name does not establish a join.
New relationships can be proposed for review; they should not become authoritative
without review and appropriate checks.

**Cross-schema analytics should start inside one approved warehouse.** This fits
the current one-source conversation model. It does not require mixed warehouse
and file analysis. Start with shared dimensions and clear questions, such as
sales, returns, and targets by month and region. Aggregate each fact at the
compatible grain before combining it. Preserve unmatched groups and reconcile
the result to the separate totals.

Record alternate unique keys, relationship direction, and intended cardinality
when useful. Check actual duplicate keys for material analyses. Standard Snowflake
tables do not enforce primary, foreign, or unique key constraints, as its
[constraint documentation](https://docs.snowflake.com/en/sql-reference/constraints-overview)
explains. Declared keys alone do not prove that a join is safe.

Add temporal relationships later when a task needs attributes as they existed at
the transaction date. General federation and multi-file joins are separate product
choices, with larger population and provenance requirements.

### 5. Data meaning and data quality

Saved datasets have exact lineage, but their business metadata is less complete.
Grain, units, calendar meaning, exclusions, and some population changes still
depend on prose and specialist judgment. This limits reliable comparisons,
forecasting, refresh, and follow-ups.

Extend the existing dataset metadata with the meaning required by the task: what
one row represents, entity keys, units, date role, calendar, population filters,
and an explicit source cutoff if one exists. Allow unknown values. Do not infer a
currency or a complete reporting period from transaction dates or query time.
Retain the distinction between declared meaning and checked facts.

Add useful quality checks within requested analyses: missing values, duplicate
keys, missing periods, invalid categories, denominator changes, and unmatched
joins. Explain how each material issue changes the conclusion. Avoid a large
quality report for every simple question.

**The Snowflake adapter also has a type-preservation gap.** It infers Arrow types
from row values. Empty results become string columns; all-null columns become
null types. A fake-cursor probe confirmed this even when the cursor declared
number and date types. This can break the new typed empty refresh path. Preserve
declared result types throughout extraction, including empty and all-null batches.
The recent empty-dataset fixes elsewhere do not resolve this adapter path.

### 6. Python, statistical methods, and forecasts

The current runner is already iterative and inspectable. The main improvement is
method assurance, not a broader list of Python packages.

**Successful execution is a weak completion condition.** `finish_analysis`
requires a successful execution, but does not establish that the method and final
outputs answer the assigned question. Forecast evaluation is optional in the
tool contract. A forecast can therefore be marked complete without the descriptor
that triggers the strong score and chronology checks. This is a contract gap;
the review did not observe a live model taking that path.

Require saved predictions and an explicit evaluation descriptor for a completed
forecast. If defensible evaluation is unavailable, state the limitation and use a
partial outcome. Extend similar evidence requirements to other methods only as
their workflows are delivered. A general algorithm registry is unnecessary.

The current forecast checks recompute scores and measured interval coverage.
They do not prove that preprocessing, feature selection, fitting, or interval
construction avoided future information. Inspect the actual calculation and use
appropriate time or group splits. Scikit-learn's
[pipeline guidance](https://scikit-learn.org/stable/modules/compose.html)
shows how to keep learned preprocessing within the correct training split.

After these basics are verified, add forecasts from several chronological
starting points and errors by horizon. This gives a better test of the actual
planning task. The
[rolling forecast evaluation pattern](https://otexts.com/fpp3/tscv.html)
is well established. Grouped forecasts and fiscal calendars can follow a clear
business need. Keep nominal coverage separate from observed coverage and its
sample size.

### 7. New analytical capabilities

Generic Python can attempt many of these tasks now. The gap is a tested workflow
with clear inputs, correct saved outputs, and useful interpretation.

| Workflow | Practical value | Main requirement |
|---|---|---|
| Explain a change | Identify which segments contributed to a rise or fall | Reconcile contributions to the total; distinguish arithmetic contributions from causes |
| Reconcile measures | Compare sales, returns, targets, or two reports | Align grain, units, definitions, dates, and unmatched populations |
| Cohorts and retention | Track groups from a common starting event | Declare eligibility, cohort date, activity definition, denominator, and observation window |
| Funnels | Find where an event journey loses users | Declare event order, time limits, repeat-event rules, and eligible entities |
| Anomalies and structural changes | Identify unusual changes with business context | Use suitable baselines; handle missing periods and false alarms |
| Experiments and prediction | Estimate effects or assess useful predictions | Check assignment or split design, uncertainty, leakage, baselines, and important subgroups |
| Scenarios and sensitivity | Compare plans under stated assumptions | Save assumptions; distinguish scenario ranges from probability intervals |

Start with change explanation and reconciliation. They fit the existing saved
data path and have clear numerical checks. Add cohorts or funnels next according
to demand. Prediction, experiment, and causal workflows need stronger method
review; a regression coefficient alone is not a causal effect.

Power BI's
[explain-change interaction](https://learn.microsoft.com/en-us/power-bi/explore-reports/end-user-analyze-visuals)
is a useful product pattern: select a change, examine segment contributions, and
add useful findings to the report. The proposed workflow should preserve its
actual scope and limitations.

### 8. Graphing, reporting, and user workflow

Shared charts, direct edits, forecast bands, saved reports, and portable downloads
already cover much of the presentation need. Add chart types with a business
workflow: waterfall for reconciled change contributions, funnel for ordered
journeys, and existing heatmaps for retention. Plotly already supports
[waterfall](https://plotly.com/python/waterfall-charts/) and
[funnel](https://plotly.com/python/funnel-charts/) charts.

**Final analysis outputs need explicit selection.** Reports currently collect
diagnostics from every successful Python step. Earlier estimates can appear beside
revised estimates. They are labeled as diagnostics, but there is no explicit
final-output or superseded-output contract. Keep exploration in provenance and
portable replay. Select the final evidence for the report and later analysis.

Give users a compact statement of population, measure, date role, units, and
known completeness. Link each material conclusion to the saved result or
calculation that supports it. Numeric report cards already bind to stored values;
broader narrative consistency needs its own checks. This improves clarity without
removing the required agent-composed HTML.

Extend the existing saved-input and scope controls with useful analytical actions,
such as compare periods, explain a change, or inspect a segment. A chart click
must select from complete evidence; a display sample must not become the analysis
population.

Bounded inspection of registered diagnostic images could help the analyst check
residual or distribution plots. Add it when visual tasks justify it and the model
supports images. Numerical checks remain primary.

Observe business users identifying scope, handling empty refresh results, and
choosing a follow-up. Observe analysts tracing and replaying a download. Scripted
browser success does not establish that users can complete these tasks.

### 9. Architecture, efficiency, and simplification

Keep FastAPI, Streamlit, the two specialists, typed artifacts, and fresh Python
processes. The current separation is modular and fits the product. The Deep Agents
[architecture](https://docs.langchain.com/oss/python/deepagents/overview)
supports this use of delegation and context management.

**Make limit recovery consistent.** Wall-clock exhaustion has a partial-report
path. Hard model and tool call limits raise errors and reach the general failure
path. Committed evidence can remain without a partial answer and report. Use one
bounded completion path for these limit cases. Retain strict computation limits.

**Reduce repeated work.** Keep detailed source grounding with SQL. Reuse exact
definitions already resolved in an assignment. Reduce repeated instructions only
after testing the changed behavior. The earlier prompt reduction removed a unique
terminal instruction and failed in all three candidate repetitions. It does not
justify broad prompt removal.

**Control resource use before raising limits.** Each Python step loads all inputs
into pandas; saved SQL also loads complete Arrow tables. File size limits do not
bound working memory, and parallel analysis can multiply memory use. Shape narrow,
complete inputs with existing SQL, DuckDB, and Arrow facilities. Preserve the
requested population. Measure large-data loading and use a combined resource
budget where needed.

Separate cohesive parts of large API and state modules as new work touches them.
Measure long-history startup and persistence costs before changing storage.
Avoid a broad rewrite, a new event framework, duplicate renderers, and speculative
configuration. Remove obsolete paths after a replacement passes its checks.

The current Python process is not a filesystem or network sandbox. This is an
explicit local-product constraint in the handoff, and dedicated isolation is
deferred. Keep that decision visible. Shared or hosted use would require execution
isolation and user-scoped access before release.

### 10. Evaluation and the existing handoff

The handoff correctly describes the recent capabilities and their limits. It
distinguishes local verification from model accuracy and human usability. Its
pending semantic studies remain useful. Keep the authorization to verify locally;
this review made no provider or warehouse calls.

The next plan should give more weight to answer correctness, the Snowflake adapter,
final evidence selection, and common business tasks. The current handoff is mainly
organized around recent releases and semantic experiments. It does not yet give a
full plan for cross-schema discovery and analysis.

Use the existing runner and grader. Add known numerical outcomes and difficult
cases for counts, rates, date roles, duplicate keys, lost groups, multi-fact
alignment, missing periods, leakage, and misleading conclusions. Some current live
analytical smoke checks look for method words and successful execution. Those
checks cannot establish statistical correctness.

Measure first correct results, repairs, useful clarification, scope errors,
method errors, report agreement, user task success, latency, and cost where known.
Do not count unavailable telemetry as zero. Keep held-out questions separate from
reviewed examples. The
[Spider 2.0 research](https://spider2-sql.github.io/)
also supports testing large schemas, multiple dialects, and multi-step enterprise
questions. Its benchmark scores do not establish this agent's accuracy.

## A stronger next version

Build an analyst that can complete three clear jobs:

1. **Find and define.** Search approved business domains and schemas. Explain the
   selected measure, date, population, and valid relationship route. Ask only for
   material missing meaning.
2. **Calculate and investigate.** Retrieve complete data, check key risks, reconcile
   results, and use a tested analytical method. Continue from final saved evidence.
3. **Explain and continue.** Present supported findings, uncertainty, and a compact
   report. Let the user compare, refine, inspect, or refresh the same analytical
   scope as a new revision.

This version would use the current coordinator, SQL, and Python roles. Its new
capability would come from better metadata, evidence requirements, reviewed
relationships, and verified business workflows.

## Prioritized improvement plan

Deliver each increment as a working product. Preserve the existing boundaries
and recovery behavior. The completion checks below are proposed gates, not claims
that these improvements have already been implemented or measured.

| Order | Improvement | Why it comes here | Completion check |
|---|---|---|---|
| 1 | Close the count-grain gap and preserve Snowflake result types | These can directly change answers or break valid refreshes | Checked counts across one-to-many joins; correct decimal/date types for empty and all-null results |
| 2 | Strengthen analytical completion, final output selection, and partial reporting | Results must support the claim of completion | Required forecast evidence; revised outputs are clearly final; every supported limit case preserves partial findings and their report |
| 3 | Improve semantic and saved-data meaning | Later analysis depends on the right measure, date, units, and population | Held-out competing meanings resolve correctly or prompt useful clarification; derived datasets show declared grain and unknowns |
| 4 | Add approved cross-schema discovery and analytics within one warehouse | This adds substantial coverage without changing source ownership | Duplicate names remain distinct; approved cross-schema queries reconcile; unsupported relationships remain explicit |
| 5 | Deliver change explanation and reconciliation, then cohorts or funnels | These are common business jobs with clear evidence checks | Final saved outputs independently recompute; denominators, exclusions, and scope are visible |
| 6 | Extend forecast and statistical evaluation | Deeper methods need stronger outcome and leakage checks | Rolling evaluations at useful horizons; checked splits and preparation; baseline and subgroup results are inspectable |
| 7 | Simplify and improve speed as measured | Reduce cost and maintenance while preserving correct behavior | Fewer redundant calls and lower time or memory; no new scope, method, recovery, or report failures |

Independent numerical checks and outcome evaluation run through every increment.
Prepare and run deterministic checks locally. Provider studies remain planned work
until the user authorizes their provider and fixture contents. Do not treat the
existing local timing or passing tests as the result of those studies.

Later product choices include multiple files or sheets, warehouse/file enrichment,
scheduling, shared workspaces, and hosted use. Prioritize them only when a concrete
workflow needs them. They require explicit scope and lifecycle decisions. A vector
service, persistent kernel, universal critic, new specialist, or general workflow
engine is not required by the current evidence.

## Review evidence and limits

**Checks performed for this review:** 108 focused tests passed in 17.02 seconds,
with three existing framework/client warnings. The suites cover semantic priority,
saved scope, forecast evaluation, and priority workflow. Tracing was disabled.
No live provider evaluation was enabled. The full suite was not rerun here.

Two local synthetic probes confirmed the count-grain and Snowflake type issues
described above. Neither used a warehouse or model. Findings about optional
forecast evidence, report output selection, schema readiness, resource loading,
and hard-limit recovery come from code inspection. Their effect on live users was
not measured.

The retained 2 October record reports 490 full-suite passes and six skipped
provider tests. Those are historical results, not a new full-suite result from
this review. No broad model accuracy, performance improvement, or user-success
rate is claimed.

| Finding | Main code location |
|---|---|
| Count-grain and optional metric checks | `data_analytics_agent/semantic_sql.py:312`, `:408`; `agents/text_to_sql/tools.py:97` |
| Snowflake empty/all-null result types | `data_analytics_agent/backends/snowflake.py:122` |
| Current-schema metadata boundary | `data_analytics_agent/backends/snowflake.py:161`; `semantic.py:487` |
| Role discovery and exact definitions | `data_analytics_agent/semantic_context.py:164`, `:183`, `:275` |
| Business metadata for saved data | `data_analytics_agent/analytical_scope.py:67`; `agents/data_analysis/runner.py:299` |
| Optional forecast completion evidence | `data_analytics_agent/agents/data_analysis/tools.py:130`, `:161` |
| Report includes each successful step's diagnostics | `data_analytics_agent/reporting/tools.py:107` |
| Hard-limit failure and partial recovery paths | `data_analytics_agent/execution_budget.py:22`; `run_manager.py:436` |
| Eager loading of saved inputs | `data_analytics_agent/agents/data_analysis/worker.py:215`; `agents/text_to_sql/tools.py:220` |
| Live statistical smoke checks | `tests/test_live_evaluations.py:164` |

## Documentation cleanup

Removed ten obsolete files, totaling 1,223,200 bytes:

- The 14 September generated review HTML.
- The 29 September capability review and its superseded check record.
- The 30 September ablation readiness review, superseded by actual outcomes and
  the execution guide.
- Four redundant browser screenshots: Excel, export, stale scope, and failed
  refresh.
- Two `.DS_Store` files.

Retained current guides, the handoff, capability inventory, active study protocols,
the rejected prompt candidate needed by tests, compact failure and verification
receipts, the useful empty-scope screenshot, onboarding diagrams and their editable
sources, and the portable example. Updated indexes and removed links to deleted
files. Historical counts and failed outcomes were not rewritten as current passes.

The initial review pass wrote only documentation cleanup and this review. It
preserved existing application changes, tests, configuration, and `HANDOFF.md`.
The subsequent handoff update and consolidation are recorded in
[the review index](README.md#historical-assessments); no application implementation
was changed.
