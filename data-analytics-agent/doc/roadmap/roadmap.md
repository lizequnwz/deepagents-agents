# Next capability increments

Updated 1 October 2026. Excel intake, portable script/data bundles and notebook
export/replay are [delivered](implementation-progress.md). This roadmap describes
remaining work. The [handoff](../../HANDOFF.md) sets product constraints and the
[ablation plan](simplification-and-ablation.md) covers optional simplifications.
Dedicated execution isolation remains deferred; reuse the local runner.

## 1. Establish outcome and usability evidence

Extend the existing evaluation corpus and independent grader rather than build a
benchmark service. Include workbook range/formula interpretation, multi-input
analysis, reconciliation, cohorts/funnels, missingness, forecast feasibility,
temporal leakage, baseline comparison and report/evidence agreement. Hold out
paraphrases and ambiguous requests. Recompute arithmetic and statistical outcomes
from complete saved evidence; a completed report is not a grade.

Observe business users uploading/reviewing a workbook, identifying its population,
asking a follow-up and finding limitations. Observe analysts tracing and replaying
the exported calculation. Measure task success, time, errors and repairs. Use the
largest observed friction to choose the next usability change; foreground risky
schema columns without removing explicit confirmation.

**Completion gate:** exact prompts/configuration/fingerprints, independent expected
values or method checks, retained failures and a dated outcome for every evaluated
case. Distinguish deterministic/scripted, live-provider and browser evidence. Model
quality claims require live outcomes, not more implementation-only tests.

**Existing boundaries:** `scripts/evaluate_documented_examples.py`,
`scripts/grade_documented_examples.py`, `tests/fixtures/`, and upload review UI.

The [ablation execution workflow](ablation-execution.md) now supplies 25 synthetic
cases, complete receipts and paired gates. The first prompt candidate was rejected
after repeated metadata regressions; the shared batch-review failure was repaired
and verified through a live reviewed run. See the
[dated result](../reviews/ablation-outcomes-2026-10-01.md). The mixed study ended
early and does not complete live grading or observed usability evidence.

## 2. Deliver an explicit saved-dataset follow-up

Let a user select a named saved dataset and ask a narrower analytical question.
Carry that explicit reference and scope into the existing conversation workflow.
Reuse complete saved evidence where it answers the question. Coarse aggregates
cannot support finer populations; require suitable retrieval rather than infer
missing detail. Keep chart display samples separate from analytical inputs.

**Completion gate:** the chosen dataset/population is visible; SQL/Python receive
the intended IDs; incompatible grain and incomplete evidence produce useful
feedback; report and download agree on scope; reopening preserves the conversation.
Source access still follows the configured warehouse/file boundary.

**Existing boundaries:** result inspection UI, run request/context, scoped evidence
resolver and saved-dataset tools. Start with explicit selection; linked chart
interaction is a later increment.

## 3. Make forecast evaluation inspectable

Display saved training/holdout boundaries, observed/predicted values, requested
horizon, baseline/candidate errors, forecast start and interval method. Persist
evaluation tables plus a small descriptor; extend existing chart/report contracts
only for the required actual/forecast series and start marker. Interval labeling
already exists. Do not introduce an algorithm registry or new forecasting agent.

**Completion gate:** scores recompute from saved actuals/predictions; no temporal
leakage; a baseline is visible; short/noisy/structural-break fixtures are covered;
nominal interval coverage is distinguished from measured holdout coverage and its
limited sample. Chat, HTML, notebook and saved tables describe the same scope/method.

**Existing boundaries:** data-analysis outputs, shared chart schemas and renderer,
report blocks and export evidence. This can proceed independently of scope controls.

## 4. Add shared scope, then manual refresh

After explicit follow-ups work, introduce one filter state over a complete suitable
saved dataset. Bind cards/charts/tables/downloads to it. Keep unsupported filtering
of aggregates explicit. Then add manual warehouse refresh as a new analysis and
immutable report revision, preserving the last successful view on failure.

**Completion gate:** all surfaces and exports agree on scope, reopening restores
the view, stale edits are rejected, presentation changes make no model/source
calls, and refresh records actual source cutoff/completeness separately from query
time. File refresh remains a new upload/conversation under the current policy.

**Existing boundaries:** presentation revisions, evidence resolution, run lifecycle
and export preparation. Do not add scheduling before refresh is validated.

## Later, driven by evidence

Improve cross-snapshot comparison proof and deliberately reviewed metric meaning;
existing same-snapshot checks do not establish source join correctness or freshness.
Support focused business workflows with skills/examples and graded outcomes before
adding method-specific agents. Add bounded registered-image inspection only when
visual reasoning is needed. Measure lexical retrieval misses before testing hybrid
retrieval at equal context budgets and grading downstream results.

Additional delimited/flat JSON formats, Excel result export, other workbook formats
and analyst code editing need observed demand. Reuse the existing ingestion/export
paths. Multi-file/sheet joins, warehouse enrichment, document research, scheduling,
hosting and live kernels require separate product decisions. None is a prerequisite
for these increments. Remove obsolete paths when replacements are adopted.
