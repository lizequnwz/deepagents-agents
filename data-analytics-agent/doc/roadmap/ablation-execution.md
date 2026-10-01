# Ablation execution

Updated 1 October 2026. Continue the interrupted working tree rather than resetting to
HEAD: Excel, export and cleanup work in that tree is part of the baseline.
The [ablation plan](simplification-and-ablation.md) still governs adoption.

## Current step

The existing runner/grader now retain failed and partial outcomes, account for
unreviewed cases, bind reviews to exact receipts, and support explicit CSV/Excel
upload fixtures. `/api/evaluation-context` fingerprints the **serving** application's
code, instructions, installed versions, execution settings and requested local
source snapshots. Checks before and after a batch detect changes. No credentials
or environment files are returned. Remote warehouse contents remain unfrozen.

[25 frozen synthetic cases](../../tests/fixtures/ablation_cases.json) cover totals,
rankings, monthly series, declared relationships, date roles, held-out paraphrases,
metadata-only questions, unanswered clarification, multiple inputs, nullable
screening decisions, prediction, forecasts, reviewed Excel, unknown completeness,
partial findings over capped retrieval and evidence reuse. Preparation creates a
deterministic 120-month SQLite source and a separate capped source over the same
synthetic data. No user warehouse is needed.

[Prompt ownership candidate](prompt-ownership.patch) attempted to remove coordinator
policy repetition and move analytical guidance into the analysis skill. It also
removed a unique terminal-response instruction and is **rejected, not adopted**:
metadata-only answers failed in all three candidate repetitions while all baseline
repetitions passed. The patch is retained for reproduction. Its
[predeclared study](prompt-ownership-study.json) targets model input tokens, with
20 or more cases, at least three independent repetitions, a 15% median paired
improvement, positive lower confidence bound and no correctness/boundary regression.
The authorized live batch recorded 138 of 150 slots and ended early after that
regression and a shared multi-action approval failure. Full receipts are preserved;
most cases remain unreviewed. The approval failure is repaired under API contract
17 and verified by deterministic checks and a complete reviewed live smoke.
See [outcomes, evidence and limitations](../reviews/ablation-outcomes-2026-10-01.md).
No performance improvement or whole-corpus accuracy is claimed.

## Reproduce a comparison

Use two isolated copies of the validated working tree, including its uncommitted
files. Keep the same lock file, provider/model, evaluation scripts and execution
settings. For the rejected study, use the preserved original snapshots; the
current application also includes the batch-review repair. Apply a predeclared
candidate patch only in its isolated copy, never to production. Prepare a
**fresh synthetic project and receipt directory for every variant/repetition**.
Preparing does not call a provider:

```sh
uv run python scripts/prepare_ablation_fixtures.py --output /tmp/ablation-baseline-r1
```

The candidate copy runs the same command with a different output directory. Its
prepared project receives the candidate's instructions. Start each project with
the existing FastAPI application, on separate local ports if interleaving trials:

```sh
uv run python scripts/prepare_ablation_fixtures.py \
  --output /tmp/ablation-baseline-r1 --serve --port 8018
```

Serving itself makes no model calls. **Submitting the corpus invokes the configured
provider and sends generated observations, prompts and repository instructions.**
Obtain authorization for that provider and fixture content first. The runner never
approves SQL/Python. Use the same review settings in both variants and exercise
manual approvals/edits through the existing UI/API when required.

```sh
uv run python scripts/evaluate_documented_examples.py \
  --base-url http://127.0.0.1:8018 \
  --corpus tests/fixtures/ablation_cases.json \
  --study doc/roadmap/prompt-ownership-study.json \
  --variant baseline --repetition 1 --keep-going \
  --output /tmp/ablation-receipts-baseline-r1
```

Repeat for the candidate and repetitions 2 and 3, interleaving paired cases/variants
where practical. `--case` supports interleaving while preserving prior conversation
receipts; the manifest always includes the entire frozen corpus. Cases not yet run
remain unreviewed, and invoking the full corpus completes the collection. Follow-ups
need their successful predecessors. Stop/Resume and report retry must actually be
exercised; a prompt mentioning them is not evidence.
A blocked follow-up is retained as missing evidence instead of creating a new
conversation. Stop at unexpected review/clarification when working interactively;
`--keep-going` retains such outcomes and continues independent cases, exiting nonzero.

Completed collections are preserved on rerun. Interrupted downloads can be
completed over the same terminal run. Review/clarification/paused runs can be
reattached after manual action without resubmitting the question; their original
interruption receipt is retained. Failed trials stay failed; an independent repeat
uses a new directory and conversation. Timeout Stop remains cooperative.

## Independent grading and adoption

Review every frozen corpus case against the existing seven criteria. Check arithmetic
against the frozen source or complete typed downloads; inspect methods, training
boundaries, executed approval edits, units and report agreement independently.
`run.json`, complete CSV/Parquet, report/specification and `analysis.zip` are saved
before grading. A download failure cannot erase the model's outcome.

Each review JSON has `evidence_level` (`live_provider` or `scripted`) and `cases`.
Each case has its exact `run_id`, the seven `criteria` entries, plus these fields
for a paired study:

```json
{
  "hard_boundaries": {"status": "pass", "evidence": "Exact receipts proving source ownership, review, completeness, units and reporting"},
  "first_attempt": {"status": "pass", "evidence": "Initial outcome and preserved errors, before repairs"},
  "repair_count": 0,
  "scenario_checks": {
    "stop_resume": {"status": "pass", "evidence": "Observed interruption/resume receipts and final evidence"}
  }
}
```

Use `fail` when a check fails; retain missing/unassessed evidence. Record only
scenarios actually exercised. Every required scenario in the protocol needs an
evidenced passing check in each variant/repetition. Scripted mechanical tests do
not satisfy live outcome grading. An absent repair count remains unknown.

```sh
uv run python scripts/grade_documented_examples.py \
  /tmp/ablation-receipts-baseline-r1 \
  --review /tmp/baseline-r1-review.json \
  --output /tmp/ablation-receipts-baseline-r1/grades.json

uv run python scripts/compare_ablation.py \
  --study doc/roadmap/prompt-ownership-study.json \
  --trial /tmp/ablation-receipts-baseline-r1 \
  --trial /tmp/ablation-receipts-candidate-r1 \
  --trial /tmp/ablation-receipts-baseline-r2 \
  --trial /tmp/ablation-receipts-candidate-r2 \
  --trial /tmp/ablation-receipts-baseline-r3 \
  --trial /tmp/ablation-receipts-candidate-r3 \
  --output /tmp/prompt-ownership-comparison.json
```

The comparator rejects mismatched inputs/providers/settings, stale grades,
duplicated runs/conversations, undeclared changes and incomplete trial coverage.
It keeps per-case outcomes, first-attempt regressions, diagnostics, failed-tool
categories and reviewed repair counts. It computes paired relative changes within
each case, then bootstraps **conversations** using SciPy, keeping related follow-up
cases and repetitions together. Missing usage, paid cost and warehouse query-count
telemetry are unknown, never zero. Interrupted executions have no comparable
performance metric. An aggregate improvement and interval require passing,
independently reviewed pairs for the entire frozen corpus; an early-terminated
study cannot report a favorable estimate over its surviving cases.

`eligible_for_adoption` means the declared diagnostic gates pass; it does not apply
a patch or establish general non-inferiority. Review boundary coverage before
adopting. Failed/regressed studies retain the baseline; unknown or insufficient
evidence is inconclusive. A major specialist/recovery removal needs stronger
repeated evidence. The evaluation follows established
[dataset/repetition comparisons](https://docs.langchain.com/langsmith/evaluation-types)
and [SciPy bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
patterns without adding an evaluation service.

## Subsequent steps

| Candidate | Current decision / next evidence |
|---|---|
| Prompt ownership | Reject this candidate after three paired metadata regressions. Preserve unique output/terminal instructions in any narrower study. |
| Redundant metadata lookup | Prediction traces show coordinator discovery before delegation despite the SQL ownership policy. Isolate this routing behavior in a fresh study; metadata-only research and SQL grounding must remain available. |
| Serial versus bounded analysis | Existing `ANALYSIS_PARALLEL_WORKERS=1/2` supports this comparison. Freeze another protocol allowing only `analysis_parallel_workers`, targeting elapsed time; preserve explicitly requested parallel work and exercise separate approvals/Stop/Resume. |
| Feature-disable variants | The two settings are documented and chart-disable wiring has a regression. The local deployment enables both, but external usage/need is unknown. Removal is not established as unused. |
| File-only specialist | Deferred until traces establish material handoff cost; source ownership and all saved-data/review boundaries remain required. |
| Presentation guidance/arguments | The partial study showed SQL/approval failures and no chart/report argument failures. No schema narrowing is justified by this evidence. |
| Hybrid retrieval | Conditional on observed lexical misses; no vector service or new retrieval path added. |

Planning persistence, the two specialists and mandatory agent-composed HTML remain.
No behavioral component is declared unnecessary by deterministic checks alone.
