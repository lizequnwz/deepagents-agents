# Ablation outcomes and batch-review repair

1 October 2026. The authorized synthetic OpenAI study used `gpt-6-luna`,
the interrupted working tree as its baseline, frozen SQLite/file fixtures,
SQL/Python review enabled, and three fresh repetitions per variant. Production
instructions retain the baseline. The prompt-ownership candidate is rejected.

## Prompt study

The predeclared 25-case, two-variant study had 150 run slots. It recorded 138 runs:
27 completed, nine failed, 80 paused and 22 awaiting clarification. Twelve follow-ups
were not attempted because their prerequisite conversations had not completed.
Expected clarification is distinct from an unexpected incomplete answer.

The metadata-only case completed and independently passed in all three baseline
repetitions. All three candidate repetitions failed with **Agent finished without
a structured response**. The patch removed a unique instruction to return
`CoordinatorResponse` along with repeated policy. This regression is sufficient
to reject the patch; it does not establish which other removed passages are safe.

The study ended early after the replicated regression. Pending runs were stopped,
original failures and review decisions were retained, and existing artifacts were
downloaded without resubmitting questions. The mixed corpus is **not fully graded**.
There is no latency, token or cost improvement claim. The comparator now suppresses
aggregate performance estimates when outcome pairs are incomplete, unreviewed or
failing; stopped-run counters describe only work already performed.

Compact evidence: [run counts, IDs and errors](ablation-live-evidence-2026-10-01.json),
[failed-tool categories](ablation-tool-failures-2026-10-01.json), and
[session record](ablation-live-session.json). Full frozen copies, manifests,
operator decisions, grades, downloads and the comparison are retained locally in
`.analytics/evaluations/prompt-ownership-2026-09-30/`, which is ignored by Git.
No provider credentials or environment files were copied into evidence.

## Shared product failure and repair

The multiple-input case exposed a baseline bug in both variants, in all three
repetitions. A native middleware interrupt held two SQL proposals, but the
application exposed and resumed only one. Resumption failed with **Number of human
decisions (1) does not match number of hanging tool calls (2)**.

The application now follows the library's
[ordered decision-per-action contract](https://docs.langchain.com/oss/python/langchain/human-in-the-loop):

- A review contains its interrupt ID and every proposed action, in order.
- Each proposal retains its permitted decisions, exact code and input bindings.
  Python review includes every named input and its complete-population metadata.
- One common review form submits all decisions. A user can edit one proposal,
  approve another or request revision of selected proposals. Reset affects only
  its own editor and does not submit the batch.
- The API rejects missing decisions and decisions for a superseded interrupt.
  A correction rejects every proposal in the current batch with the correction.
- Independent worker interrupts stay separate; checkpoint recovery preserves
  their reviews. Unused stored review-type state and duplicate review forms were
  removed. No compatibility layer was added.

API contract is **17**. Both services must use this version; old incompatible
records require fresh storage. Preserve needed old artifacts separately.

## Verification

A new live synthetic run completed using the repaired contract:
`7ed3869b-0c08-4df8-9f76-d906dc82564e`. Its first review contained both SQL queries.
One was approved, the other received an exact secondary-order edit. Both executed
once and saved disjoint, untruncated 60-month populations. Stop/Resume at Python
review preserved the proposals and dataset bindings.

Python then used both named inputs, saved a 120-row combined dataset and a two-row
summary, and completed a second reviewed comparison step. The operator corrected
a column-name collision with `Series.skew`; NumPy was already preloaded, so an
additional import in that edit was redundant. This is a successful reviewed
workflow, **not first-attempt model accuracy**.

Independent calculations over the complete Parquet downloads confirmed means
159 and 279, medians 160 and 280, identical sample standard deviations of about
35.6592, and a 120-unit shift. The stored summary, report table and analysis agreed.
The chart and HTML were created, and the ZIP retained exact reviewed code and both
input populations. No tool failures occurred in this run. See the
[check record](approval-batch-evidence-2026-10-01.json). Raw artifacts are retained
in `.analytics/evaluations/approval-batch-2026-10-01/`.

The client comparator changed during smoke collection, so the runner correctly
refused to reuse its original evaluation manifest. Final artifacts were downloaded
from the same completed run, and the serving application's before/after fingerprint
was independently checked as identical. The refusal and manual collection record
are preserved. This smoke is not part of the paired prompt comparison.

Deterministic verification covers native two-action interruption, exact editing,
selective rejection without duplicate execution, missing/stale decisions, durable
review recovery, all-input scope checks, and Streamlit form reset/submission. The
full suite passed: **376 passed, six skipped** (the opt-in provider tests), with
10 existing library warnings. Focused ablation gates passed 20 checks; unused-name
lint and whitespace checks passed. The later nonempty-decision-policy guard is
included in the full suite. Temporary provider servers were stopped after
collection. No commit or deployment was made.

## Remaining candidates

| Candidate | Decision from current evidence |
|---|---|
| Prompt ownership | Reject this patch; retain the baseline. A narrower revision needs a fresh predeclared study and must preserve unique terminal/output instructions. |
| Redundant metadata lookup | Coordinator discovery before prediction delegation was observed in all three baseline repetitions. That is a target for a narrower routing study; an accuracy-preserving reduction was not measured. Metadata-only requests still need coordinator discovery, and SQL grounding remains required. |
| Serial versus bounded parallel analysis | Not resolved by this study. Freeze a worker-count-only comparison on independent analytical questions; exercise separate approvals and Stop/Resume. The repaired batch is the new common baseline. |
| Feature-disable switches | Both are documented supported settings, and chart-disable wiring has a regression. Local enablement does not establish that external disable usage is absent. Retain them pending deployment evidence. |
| File-only specialist handoff | No analytical assignment completed before the study was stopped, so material handoff cost was not established. Keep SQL/Python separation and SQL-only warehouse ownership. |
| Presentation instructions/arguments | No chart/report argument failures appeared in the partial study; SQL grounding and approval failures dominated. This does not prove presentation is failure-free, and does not justify narrowing its contract. |
| Hybrid retrieval | No lexical miss was established. Execution rejections over relationship keys are not evidence of retrieval misses. Keep the lexical path. |

The later behavioral experiments remain open. The early-terminated study does not
justify removing specialists, planning/recovery, parallelism or HTML reporting.
