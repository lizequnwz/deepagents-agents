# Paired evaluations

Compare one declared change against a fixed baseline. The [synthetic corpus](../../tests/fixtures/ablation_cases.json)
includes semantic grounding, descriptive and analytical questions, reviewed uploads,
clarification, incomplete data, and evidence reuse. The fixture builder creates
local SQLite sources, including a source with an extraction cap.

Keep verification local unless the user authorizes the configured provider and
fixture contents. Preparing the fixtures and starting the server make no model
calls. Submitting the corpus sends prompts, semantic context, instructions, and
retrieved fixture observations to the provider.

## Prepare and collect runs

Declare the candidate, changed files or settings, target metric, scenarios, and
adoption gates before collecting runs. Use isolated copies of the current working
tree for the baseline and candidate. Keep the lock file, fixtures, evaluation
scripts, provider/model, and shared execution settings identical. Apply candidate
changes only in the isolated copy.

Create a fresh fixture project and receipt directory for each variant and
repetition. From the baseline copy, prepare the project, then serve it:

```sh
uv run python scripts/prepare_ablation_fixtures.py --output /tmp/ablation-baseline-r1
uv run python scripts/prepare_ablation_fixtures.py \
  --output /tmp/ablation-baseline-r1 --serve --port 8018
```

After authorization, collect the run from another terminal. The example uses
the routing protocol. Use a protocol that matches the isolated change.

```sh
uv run python scripts/evaluate_documented_examples.py \
  --base-url http://127.0.0.1:8018 \
  --corpus tests/fixtures/ablation_cases.json \
  --study tests/fixtures/ablation/semantic-routing-study.json \
  --variant baseline --repetition 1 --keep-going \
  --output /tmp/ablation-receipts-baseline-r1
```

Repeat for each declared baseline and candidate repetition. Interleave pairs
where practical. `--case` runs individual cases while retaining the full
manifest. Follow-ups require their prior conversation receipts. The runner
retains failed and partial outcomes and does not approve code. Exercise reviews,
Stop/Resume, and report retry through the app when the protocol requires them.

Before/after fingerprints check the serving code, instructions, dependencies,
execution settings, and requested local snapshots. Remote warehouse contents
are outside the fingerprint. A changed fingerprint requires a new collection.

## Grade and compare

Check every case independently against the frozen source or typed downloads.
Use the [testing guide](testing.md#reproducible-grading-and-held-out-cases) for
the base review schema. Paired reviews declare `evidence_level` (`live_provider`
or `scripted`) and add the following fields to each case alongside its exact
`run_id` and criteria:

```json
{
  "hard_boundaries": {"status": "pass", "evidence": "Source, review, completeness, units, and reporting receipts"},
  "first_attempt": {"status": "pass", "evidence": "Initial outcome and any errors"},
  "repair_count": 0,
  "scenario_checks": {
    "stop_resume": {"status": "pass", "evidence": "Observed interruption, resumption, and final evidence"}
  }
}
```

Record `fail` for failed checks. Leave unassessed checks unreviewed and absent
repair counts unknown. Each required scenario needs evidenced coverage in each
trial. Scripted checks establish mechanics. Live outcomes require their own
independent grades.

```sh
uv run python scripts/grade_documented_examples.py \
  /tmp/ablation-receipts-baseline-r1 \
  --review /tmp/baseline-r1-review.json \
  --output /tmp/ablation-receipts-baseline-r1/grades.json

uv run python scripts/compare_ablation.py \
  --study tests/fixtures/ablation/semantic-routing-study.json \
  --trial /tmp/ablation-receipts-baseline-r1 \
  --trial /tmp/ablation-receipts-candidate-r1 \
  --trial /tmp/ablation-receipts-baseline-r2 \
  --trial /tmp/ablation-receipts-candidate-r2 \
  --trial /tmp/ablation-receipts-baseline-r3 \
  --trial /tmp/ablation-receipts-candidate-r3 \
  --output /tmp/semantic-routing-comparison.json
```

The comparator checks declared inputs and changes, receipt and grade bindings,
unique runs, and trial coverage. It computes paired changes per case and
bootstraps conversations to keep follow-ups and repetitions together. Missing
telemetry remains unknown. Aggregate performance estimates require complete,
passing, independently reviewed pairs. `eligible_for_adoption` reports whether
the declared gates passed. Applying the candidate remains a separate decision.

## Semantic study protocols

The optional [routing](../../tests/fixtures/ablation/semantic-routing-study.json),
[role-batching](../../tests/fixtures/ablation/semantic-role-batching-study.json),
and [join-feedback](../../tests/fixtures/ablation/semantic-join-feedback-study.json)
protocols each require three fresh repetitions per variant. Check the expected
measures, dimensions, filters, dates, joins, grain, and clarification outcome.
Supply `semantic_roles` with a status and evidence, `snapshot_reviews` for
every complete SQL snapshot, and `value_bindings` for declared scalar expectations.
Key snapshot reviews by result ID and record a `pass` or `fail` status and evidence.
Key value bindings by expected metric and supply the saved `result_id`, `column`,
and optional `row_index`.

Quality changes must resolve their paired target failures without new outcome,
first-attempt, or boundary regressions. Speed changes also require at least 15%
lower median paired active time to the first correct SQL snapshot, excluding
approval waits. The studies remain incomplete.

## Historical prompt study

The rejected prompt-ownership candidate removed a unique terminal-response
instruction. All three candidate metadata runs failed while all three baseline
runs passed. The study stopped after recording 138 of 150 planned runs and
before full grading, leaving whole-corpus accuracy and performance unmeasured.
A shared multi-action approval failure was reproduced in both variants and
verified separately after repair.

- [Run counts and errors](evaluation-evidence/ablation-live-evidence-2026-10-01.json)
- [Failed tool calls](evaluation-evidence/ablation-tool-failures-2026-10-01.json)
- [Approval repair check](evaluation-evidence/approval-batch-evidence-2026-10-01.json)
- [Protocol](../../tests/fixtures/ablation/prompt-ownership-study.json) and [candidate patch](../../tests/fixtures/ablation/prompt-ownership.patch)
