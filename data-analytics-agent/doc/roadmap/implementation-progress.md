# Current capability status

Updated 18 October 2026. This is the current delivery inventory. Seven analytical
families, multiple reviewed tables in one file workspace, and cited document
context are now implemented. The [handoff](../../HANDOFF.md) owns priorities and
acceptance gates; its earlier broader workspace direction is only partly delivered.
General warehouse discovery, repository code authoring and a broader platform are
not implemented. Dated reviews describe earlier versions.

## Delivered

| Capability | Current behavior and boundary |
|---|---|
| Local onboarding | One locked install/start path; upload entry does not require a warehouse; advanced settings documented separately |
| Source grounding | One configured SQLite/Snowflake source or isolated file workspace per conversation; curated warehouse semantics; shared cached lexical discovery/browsing; no warehouse/upload enrichment |
| Semantic reliability | Batched unresolved role candidates; SQL-only exact physical relationship key pairs; structured actionable join/metric/fan-out validation feedback; specialist-owned coverage |
| File intake | The chat **+** button accepts CSV, Parquet, explicitly selected `.xlsx` worksheet tables and reference documents; additional file tables receive separate schema confirmation, grain and keys; original hashes, immutable typed snapshots and warnings |
| Document context | Readable PDF, UTF-8 text and Markdown with retained originals/hashes, bounded extraction and cited document/page/line search/read tools; candidate PDF/Markdown tables enter separate schema review before calculation; published context is retained in reports/exports; warehouse documents remain context only |
| SQL and Python | SQL-only warehouse execution; saved-data SQL reshaping; iterative Python with named inputs, fresh processes, saved derived datasets and diagnostic PNGs |
| Exploration and preparation | Full-population profiles, distributions, missingness, correlations with sample counts, category remainders and declared-date coverage; explicit conversions, derived columns, fill/drop/deduplication with operation audits |
| Comparisons and diagnostics | Descriptive group comparison, keyed reconciliation and additive change contributions; unmatched groups, missing values and reconciliation status remain visible; no causal attribution claim |
| Customer journeys | Declared-population cohort retention, ordered fixed-entry-window funnels with censored entities retained, and deterministic RFM scores/segment profiles; observation cutoffs and activity/event definitions are explicit |
| Statistical comparison | Numeric Welch mean-difference intervals/tests and Hedges' g, or binary Newcombe risk-difference intervals with Fisher tests; saved sample/exclusion accounting and undefined cases; independent observations required |
| Prediction | Fixed Ridge regression and binary logistic pipelines; training-only preprocessing; declared random, time or group holdout, simple baseline, held-out metrics and saved scored rows; feature availability remains an explicit analytical assumption |
| Time-series methods | Declared regular-calendar trend/STL diagnostics and residual anomaly screening; additive ETS with chronological holdout, last-value baseline, final refit, saved predictions/scores and declared conditional model-based prediction intervals |
| Scenarios | Explicit assumption grids and caller-supplied formulas with saved input combinations, computed outputs and undefined arithmetic; scenario ranges have no assigned probability coverage |
| Evidence and reports | Application-owned receipts, explicit final output/dataset selections, scoped findings, shared versioned charts, required agent-composed HTML, numerical bindings and report retry; superseded attempts remain provenance |
| Comparisons | Same-snapshot current/baseline bindings, deterministic deltas and calculation disclosure; checks for grain, dimensions, periods, units and completeness |
| Presentation | Direct chart styling and exact report-title revisions over saved evidence; immutable revisions, stale-write protection and failure recovery |
| Analytical visibility | Visible plans, compact investigation records, bounded independent Python assignments, ordered batch review, exact all-input review and code inspection |
| Run recovery | Durable conversations/checkpoints, approvals/corrections, Stop/Resume and history deletion; native budget exhaustion blocks analysis and reserves bounded partial-report presentation; blocking source cancellation remains cooperative |
| Saved evidence | Conversational follow-ups reuse suitable named saved datasets; source/thread isolation, complete-population checks, input lineage, inspection and downloads remain |
| Forecast evaluation | Declared forecast completion requires evaluation or a partial outcome; named predictions and independently recomputed finite scores; training/holdout/origin/horizon/frequency/baseline/sample size; measured versus nominal coverage; anchored weekly calendar and distinct interval bindings; forecast-specific band/start marker and portable replay |
| Voice | Record → transcribe → edit composer draft; no automatic question submission |
| Portable work | Selected report/data/code ZIP prepared on click, exact SQL files, provenance, versions/hashes, material documents and exact per-execution analytical-helper source snapshots; editable notebook and script replay over saved snapshots |
| Evaluation tooling | 40-case synthetic corpus with 20 timed semantic cases over small/large catalogs; role/grain/clarification expectations; all complete SQL snapshots retained; independent scalar checks and first-correct timing; separate routing/batching/join protocols and strict paired gates; opt-in provider tests |

The latest cleanup removed the unused debug-details setting and inactive validation
branch. Enforced data/output limits remain. Python review shows every named input.
Native multi-action review now preserves every proposal, exact per-action decisions
and checkpoint recovery; stale submissions are rejected. Duplicate review forms
and unused review-type state are removed. The Analyze selector, its population
filters, explicit source-expansion state and warehouse-refresh route are removed.
All attachments use the native composer. API contract is **22**, with no migrations
or compatibility readers. Older
incompatible storage requires a fresh directory; restart both services together.

SQL/Python execution remains automatic by default. Optional review requires
explicit decisions, validates feedback beside each proposal and preserves
independent edits. Earlier usability and export checks are retained in the
[historical record](../reviews/README.md#earlier-implementation-checks).

## Evidence and limits

The [19 October composer simplification](../reviews/composer-simplification-2026-10-19.md)
records removal of the Analyze feature and its backend contracts, native attachment
routing and preserved review/question flow. Its 634 local cases include two notebook
retries with loopback access; 31 focused checks cover the final composer revision.

The [18 October checkup](../reviews/checkup-2026-10-18.md) repairs exact arithmetic,
warehouse metadata/identity, direct entity-count fan-out, final analytical selection,
declared forecast completion, native call-budget recovery and file lifecycle cases.
Final checkup validation: **667 full-suite passes and six opt-in provider skips**;
code/instruction hashes stayed unchanged during the run. See the dated checkup for
commands, intermediate findings, native harness/replay checks and limitations.

The [17 October implementation outcome](../reviews/capability-expansion-2026-10-17.md)
records **617 full-suite passes and six opt-in provider skips**, plus focused
checks, replay, native UI verification and retained limitations.

The 17 October feature expansion includes local deterministic tests for analytical
arithmetic, sample/population accounting, censoring, undefined cases, chronological
forecast evaluation, training-only prediction preprocessing, document/table review,
same-workspace boundaries and portable helper-source replay. These checks exercise
implemented paths; no provider study, warehouse study or business-user study was
performed for this expansion. Generic Python can attempt additional methods, but
that does not make every statistical or business task a validated capability.
New bundles use format **4**; the format-2/3 statements in dated verification records
describe those historical runs.

[Extended priority verification](../reviews/priority-followup-tests-2026-10-02.md)
records **490 passed, six skipped** and **108 focused passes**, with retained
before/after failures. It covers calendar/type/empty-population/forecast/error
boundaries, source configuration recovery, native scope submission guards and
portable replay. The local discovery probe finds expected roles with dataset
hints, reduces batch response size about 52%, and exposes broad date browsing's
need for narrowing in the competing catalog. Its warmed timings do not establish
live SQL performance. A 25-node shared-lineage check fell from 12,286 lookups to 25.

[Priority verification](../reviews/priority-releases-2026-10-01.md) records
**423 passed, six skipped**, native-widget/API/browser population checks,
clarification/Stop/Resume/restart binding checks, successful and failed local
source refresh, and moved forecast bundle/fresh-kernel notebook replay. Those bundles
used format 2. The current instruction is to keep verification local: no new live
provider accuracy or speed claim is made.

[Historical implementation checks](../reviews/README.md#earlier-implementation-checks)
retain the completed Excel, usability and SQL-export outcomes and their limits. The
[example bundle](../examples/README.md) is synthetic and usable outside the app.

These checks verify implementation behavior; they do not establish broad live-model
analytical accuracy or comparative superiority. Historical live results whose
receipts are absent are unverified. The superseded 29 September review was removed
during the 3 October documentation cleanup. The
[3 October capability review](../reviews/agent-review-2026-10-03.md) assesses the
pre-expansion implementation and proposes improvements; it does not change delivery
status or satisfy pending accuracy gates.

[Ablation outcomes](../reviews/ablation-outcomes-2026-10-01.md) record the rejected
prompt candidate, the early-terminated 138-run study and the batch-review repair.
The 1 October operator-reviewed live workflow completed and its downloads independently
recomputed; it is not first-attempt model accuracy or a completed mixed-corpus
ablation. Later behavioral studies remain open. See the
[evaluation guide](../development/ablation-evaluation.md).
The final suite for the review/comparator repair passed **376 tests**, with six
opt-in provider tests skipped.

## Open

- Broader independently graded statistical/business outcomes and usability studies.
- Three separately isolated, complete live semantic paired studies and independently
  reviewed targeted failures; speed adoption still needs at least 15% improvement.
- Live specialist suitability/leakage assessment and business-user scope recognition;
  arbitrary saved grain and Python fitting code cannot be certified by structural checks.
- Cross-snapshot comparison scope proof, explicit source cutoffs and general derived
  metric semantics. Current checks cannot certify arbitrary source joins.
- Held-out competing date/metric meanings without dataset hints, and user recognition
  of changed or empty scopes; add explicit calendar/grain preparation as workflows
  require it.
- A narrower prompt study and paired routing, parallelism and file-only specialist ablations.
- OCR, additional document/output formats, external web research and bounded visual
  diagnostic inspection.
- Broader statistical inference, validated causal designs, richer prediction/model
  selection and rolling-origin/grouped forecasting beyond the delivered procedures.

Dedicated execution isolation is deferred by the user; local processes are retained.
No Bash tool, app notebook editor/persistent kernel, workbook recalculation or
mixed warehouse/file-source analysis is included. Multiple file tables can be
combined only after explicit intake and separate review in the same file workspace.
General warehouse discovery and repository code authoring remain unimplemented. See the
[handoff](../../HANDOFF.md) and [evaluation guide](../development/ablation-evaluation.md)
before changing behavioral components. Conversation-wide source binding remains
enforced: one warehouse or one reviewed file workspace, with attached documents
treated as context rather than additional implicit analytical sources.
