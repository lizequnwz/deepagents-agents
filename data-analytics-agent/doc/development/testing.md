# Testing the application

Historical live-test claims whose receipts are unavailable in this checkout are
unverified. Current review/comparator checks and the early-terminated synthetic
study are recorded in the [1 October outcome](../reviews/ablation-outcomes-2026-10-01.md).
The [historical implementation checks](../reviews/README.md#earlier-implementation-checks)
retain the earlier Excel/export and native-widget/API checks and their limits.
The [extended priority verification](../reviews/priority-followup-tests-2026-10-02.md)
records 490 passing local tests, six skipped provider tests, retained defect/repair
receipts, population and forecast boundaries, browser checks and portable replay.
The user's current instruction is to keep verification local; no new provider
trials are authorized.

Use three distinct evidence levels: deterministic regression tests, live model
runs through the API, and browser interaction checks. None substitutes for the
others. A successful HTTP response or completed report is not a correctness grade.

## Local regression suite

```sh
uv run pytest
uv run ruff check data_analytics_agent streamlit_app.py tests scripts --select F
```

Normal pytest runs isolate storage before importing `api.app`. Six provider tests
are opt-in; a skipped test is not a pass. `RUN_LIVE_SMOKE=1` only builds a configured
graph—it does not ask a model a question. `RUN_LIVE_EVALUATIONS=1` invokes the model
on generated fixtures in `tests/test_live_evaluations.py`.

`scripts/probe_discovery_local.py` prepares frozen synthetic small/large catalogs
and compares four separate role lookups with one batch, using three fresh catalog
instances and warmed samples. It records role candidates, bounded broad/narrow
date browsing and an independently recomputed manual SQL reference. Redirect its
JSON output to an observation file. It never invokes a provider; its timings
cannot establish the end-to-end SQL performance gate.

## Documented examples against a live application

The [example corpus](../../tests/fixtures/documented_examples.json) contains exact
prompts, source IDs, conversation groups, and the explicit answer for the
clarification scenario. The [user guide](../user/deep-dive-examples.md) contains
these same prompts and human review criteria. Keep both synchronized.

These tests send prompts, semantic context, and retrieved observations to the
configured provider. Use sources you have authorized for that purpose. They incur
model usage. Do not run them against a user's active workspace or change its
review preferences.

Start a separate API and UI, keeping the configured model and source registry:

```sh
ANALYTICS_STORAGE_DIR=/tmp/analytics-example-workspace LANGSMITH_TRACING=false \
  uv run uvicorn data_analytics_agent.api:app --host 127.0.0.1 --port 8018
```

In another terminal:

```sh
API_BASE_URL=http://127.0.0.1:8018 \
  uv run streamlit run streamlit_app.py --server.port 8518
```

Run the exact questions through the same API used by Streamlit:

```sh
uv run python scripts/evaluate_documented_examples.py \
  --base-url http://127.0.0.1:8018 \
  --output /tmp/analytics-example-receipts
```

The runner preserves conversation dependencies, confirms the synthetic upload's
schema, answers only the specified clarification, and saves requests, run events,
CSV results, and report HTML. It stops at unexpected clarification/review states
rather than inventing business answers or approving code. Completed receipt collections are
preserved on a subsequent invocation. Interrupted artifact downloads can be retried
over the same terminal run. Review/paused runs can be reattached after manual action;
failed trials remain failed and independent repetitions need fresh directories. A saved request without final receipts is
reattached by run ID; the question is not submitted again. Missing prerequisites
and runs requiring attention stop the runner by default. `--keep-going` records
failures and missing dependent cases, continues independent cases and exits nonzero. Polling elapsed time on a
reattached run measures that invocation; use run diagnostics for execution timing. To repeat a full independent trial, use a new
receipt directory and a new API storage directory. `--case ID` selects a case;
follow-ups require their prior conversation receipts.

Inspect every outcome. Compare downloaded complete results with independent
read-only source queries. Recompute derived statistics, shares, reconciliations,
and forecast errors; inspect generated Python for leakage and interval meaning.
Record first-attempt errors even when the agent repairs them. Separate missing
findings from missing reports and partial answers from complete ones.

Open the matching conversation in Streamlit to check user-visible completion,
report preview, evidence disclosure, and controls. API-driven upload confirmation
does not establish that the browser's attach-and-confirm interaction works.
Stop/Resume, approvals, correction timing, microphone recording, and report retry
need their own exercised paths; do not claim them from a normal successful run.

## Evidence records

Store compact, dated outcomes and issues under `doc/reviews/`. Keep bulky raw runs,
Parquet, and HTML in the isolated receipt/workspace directories unless a particular
artifact is needed to explain a finding. Record model, source hashes, prompt IDs,
run IDs, settings, elapsed time, grading method, and limitations. Never commit keys.
See the [latest local verification](../reviews/priority-followup-tests-2026-10-02.md)
for available local checks and their limitations.

## Reproducible grading and held-out cases

The runner stores the entire frozen corpus, upload hashes and an execution
fingerprint from the serving API. It includes source DB/catalog hashes, code and
instructions, locked/installed dependencies, provider/model and execution settings.
The before/after fingerprints must agree. `--case` limits this invocation; every
corpus case remains in grading, with missing cases unreviewed. For an intentionally
smaller study, provide a smaller corpus before the first run. Reusing a receipt
directory with changed inputs fails; use a new directory for each revision. Each
completed case includes its saved report specification. Run the alternate corpus:

```sh
uv run python scripts/evaluate_documented_examples.py \
  --base-url http://127.0.0.1:8018 \
  --corpus tests/fixtures/held_out_examples.json \
  --output /tmp/analytics-heldout-receipts
```

Review each case against scope, joins/grain, arithmetic, units, assumptions,
methodology, and report agreement. Record `run_id` and `criteria` in a review JSON;
each criterion needs `status` (`pass`, `fail`, `not_applicable`) and `evidence`.
Then grade it without model calls:

```sh
uv run python scripts/grade_documented_examples.py /tmp/analytics-example-receipts \
  --review review.json --output grades.json
```

Failed, partial, missing-evidence, and unreviewed outcomes exit nonzero. Human
review and independent recomputation remain necessary; this is not an automatic
semantic-accuracy judge. Keep failing and passing receipts with their independent
numeric checks. Historical live-trial claims without receipts are unverified;
current deterministic checks do not replace provider evaluation.

## Paired ablations

Use the [paired evaluation guide](ablation-evaluation.md) for the
predeclared prompt study, frozen synthetic sources, explicit workbook/schema
fixtures and paired reducer. `scripts/compare_ablation.py` requires independent
per-case grading bound to exact manifests/receipts, fresh repetitions and
evidenced boundary checks. It rejects changed inputs/settings and stale or reused
receipts. Unknown usage/cost and absent reviews cannot satisfy adoption gates.
Incomplete, failing or unreviewed outcome pairs suppress aggregate performance
estimates. The first patch was rejected after three live metadata regressions;
the mixed study ended early. See the
[1 October outcome and batch-review checks](../reviews/ablation-outcomes-2026-10-01.md).
Deterministic/scripted checks and operator-reviewed smoke runs are not
first-attempt live-model quality evidence.

## Semantic priority studies

The [handoff](../../HANDOFF.md#verification-and-acceptance-gates) links separate routing, role-batching
and join-feedback protocols. Prepare the existing synthetic project locally with
`scripts/prepare_ablation_fixtures.py --output /tmp/a-fresh-project`; preparation
does not invoke a provider. Starting the local server also makes no model call.
Submitting analytical questions uses the configured model and requires separate
provider/fixture authorization.

The corpus now contains 40 cases, including 20 timed semantic cases and an
unanswered semantic clarification. Review expected measures, dimensions, filters,
date roles, relationship routes, grain and clarification outcome. Each complete
semantic case needs independently evidenced role checks, `snapshot_reviews` for
every complete SQL snapshot, and `value_bindings` for declared scalar expectations.
A snapshot review has `status` (pass/fail) and evidence; value bindings name an
exact result_id, column and optional row_index. Scores cannot come from report
completion or model narrative alone.

Three fresh repetitions per baseline/candidate must use identical frozen fixtures,
corpus, provider/settings and dependencies. Keep all shared product changes in both
variants; review that each semantic variant changes one declared component. The
comparator grades untimed controls, requires paired baseline-fail/candidate-pass
evidence for targeted quality scenarios, and rejects new first-attempt or boundary
regressions. Speed adoption additionally requires at least 15% median improvement
in independently graded active time to the first correct SQL snapshot. An incomplete
or unreviewed study stays inconclusive. The comparator never changes production code.

## Portable replay

Export checks move the extracted bundle before replaying its script and notebook.
Each execution starts a fresh process; notebook checks use fresh kernels. Keep
typed inputs, exact reviewed code, necessary producers, hashes, dependency versions,
and the selected report consistent. SQL remains snapshot provenance, not a source
refresh during replay. Failed attempts and unrelated evidence are excluded from
runnable replay, while required derivation steps remain inspectable.

Dataset and scalar/table numerical checks use `rtol=1e-7` and `atol=1e-10`.
Figure pixel equality is not asserted. External paths/services, dynamic imports,
or missing original random seeds can require extra setup; successful replay does
not establish analytical correctness. Notebook kernels need local loopback access.

## Controlled improvements

Remove provably unused paths and duplicate documentation directly. Changes to
instructions, routing, delegation or recovery need independently checked outcomes.
Use the existing runner and isolated variants; do not introduce production
experiment switches, compatibility readers or duplicate execution/evidence layers.

Declare the changed component, target metric and acceptance gate before collecting
results. Preserve source ownership, upload review, population, units, exact approved
edits, immutable evidence and reporting throughout a comparison. Include ambiguous
questions, partial data, interruption/restart, report retry and failed outcomes.
Repeat inconclusive studies rather than infer equivalent behavior. A small study
does not establish broad non-inferiority for removing a major component.

Measure first correct results, repairs, latency, memory and cost where known.
Observe users finding scope and completing the task; visual preference or scripted
browser success is insufficient. Fewer lines can improve maintenance without
establishing a runtime speed gain. The handoff owns current product priorities.
