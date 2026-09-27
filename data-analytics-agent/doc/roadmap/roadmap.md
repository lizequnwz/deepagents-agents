# Improvement priorities

Updated 27 September 2026. Sections 1–3 now have working implementations and
dated verification; remaining limits are stated below. The [implementation log](implementation-progress.md) records delivered
capabilities; the [live-test issue register](../reviews/documentation-live-tests-2026-09-26.md)
provides concrete evidence and separates confirmed problems from risks.

## Immediate correctness fixes from the live trial

- **Saved analysis agreement (02, 07):** derive residual counts/flags from final
  saved computations; propagate units/completeness and reconcile contradictory
  attached narratives before publication. Check downloads and report attachments.
- **Exact title edits (10):** copy the stored report specification, change only
  title and revision identity, and preserve findings/charts/analyses without calls.
- **Reliable artifact handoff (09):** stop repeated UUID transcription mistakes
  with exact reference selection and useful tool feedback.
- **Repair reduction (01, 08, 09):** target observed query-shape, output-budget and
  generated-code failures, then rerun the original questions with identical checks.

These fixes were implemented and retested in the [roadmap delivery review](../reviews/roadmap-implementation-2026-09-27.md). Exact title editing is deterministic. Analysis consistency and artifact-reference repairs improved in the observed trials, but generated prose and arbitrary source-query correctness still require review.

## 1. Make correct outcomes reproducible — delivered

Keep exact documented prompts, independent expected values, source fingerprints,
and per-run receipts. Grade scope, joins, aggregation, units, assumptions,
methodology, and report/evidence agreement. Record first-attempt failures and
self-repairs, not just eventual completion. Add held-out paraphrases and ambiguous
requests before claiming a general SQL accuracy gain.

Acceptance: every released example has a dated outcome; arithmetic recomputes from
complete saved evidence; incorrect or incomplete answers fail even when a report
exists. Live trials complement deterministic tests and do not replace them.

## 2. Reduce repairs that obscure analytical work — delivered, continue measuring

Use the issue register to prioritize observed retrieval, tool-input, execution,
and presentation failures. Improve model-visible tool descriptions or feedback
at the responsible boundary. Avoid global prompt additions for one local defect.
Keep SQL, analysis, and report composition responsibilities distinct.

Acceptance: reproduce the original failing question, add a targeted regression,
and compare the same question after the fix. Preserve first-attempt receipts.

## 3. Bind comparisons to stored evidence — delivered for shared snapshots

Add an explicit KPI comparison contract using metric references, population,
period, grain, units, and current/baseline result bindings. Derive absolute and
percentage changes deterministically and attach reconciliation checks. Expose
**How calculated?** without a model call.

Implemented checks reject period/denominator mismatches, duplicate aggregate keys,
incompatible dimensions/units, incomplete snapshots, and false completeness labels.
Displayed deltas are derived from saved values. These checks cannot detect a source
join that already inflated an otherwise unique aggregate; independent source-grain
reconciliation remains required. Cross-snapshot comparisons and an explicit source
cutoff contract remain future work.

## 4. Make forecast evaluation inspectable

Persist training/holdout boundaries, method and baseline scores, predictions,
observations, and interval assumptions. Existing interval labels are delivered;
a dedicated forecast-evaluation workspace and shared multi-series/start-marker
contract remain open.

Acceptance: recomputable holdout errors, no temporal leakage, explicit baseline
comparison, actuals visible beside forecasts, and nominal coverage distinguished
from measured coverage. Include short/noisy/structural-break fixtures.

## 5. Measure large-catalog discovery before adding infrastructure

Evaluate the current lexical index using expected semantic roles, relationships,
and reviewed results over real-sized catalogs. Include table-name ambiguity,
abstract date intents, rare concepts, overloaded terminology, and many-hop joins.
Compare hybrid embeddings only under equal context/call budgets.

Acceptance: necessary-entity recall and downstream correctness improve without
unacceptable latency, context growth, or operational complexity. A controlled
synthetic retrieval benchmark alone does not meet this gate.

## 6. Extend the result workspace incrementally

After direct title/style editing, add explicit selected-scope follow-ups, then a
shared filter over complete saved evidence, then manual report refresh. Preserve
immutable revisions and the last successful view on failure. Do not infer scope
from visual row positions or label a new query timestamp as fresh source data.

Acceptance: metric/chart/table/export agree on scope; reopen restores the view;
unsupported rescoping of aggregates explains its limitation; presentation-only
edits make no provider or warehouse calls.

## Deferred expansion

Multiple-file joins, warehouse enrichment, document research, new exports,
scheduling, hosted collaboration, and persistent Python kernels remain separate
initiatives. They should not precede measured reliability of the current local
single-source workflow. See the [ablation plan](simplification-and-ablation.md)
for evidence gates on further simplification.
