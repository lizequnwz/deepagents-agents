# Testing the application

Use deterministic regression tests for code behavior, browser checks for user
interactions, and independently graded live model runs for analytical outcomes.
Keep verification local unless the user authorizes the provider and fixture data.

## Local regression suite

```sh
uv run pytest
uv run ruff check data_analytics_agent streamlit_app.py tests scripts --select F
```

Normal pytest runs isolate storage before importing `api.app`. Six provider tests
are opt-in; a skipped test is not a pass. `RUN_LIVE_SMOKE=1` only builds a configured
graph—it does not ask a model a question. `RUN_LIVE_EVALUATIONS=1` invokes the model
on generated fixtures in `tests/test_live_evaluations.py`.

## Browser interaction suite

Build the production React client, then run the local browser journeys:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
node tests/ui/run.mjs
node tests/ui/deployment.mjs
node tests/ui/genbi-interactions.mjs
node tests/ui/editorial.mjs
```

The runner starts the real FastAPI application and native Streamlit interface on
isolated ports with temporary application storage. A scripted agent uses the
normal run manager and saved evidence without provider requests. The checks cover
file/table review, conversation, code review, dashboard actions, failure recovery,
downloads, narrow layouts and persistence. See [runner instructions](../../tests/ui/README.md)
for exact coverage and output options.

The receipt records each scenario and browser errors. Screenshots support visual
review. These checks establish browser behavior over deterministic evidence; they
do not establish model accuracy, live warehouse behavior or human usability.
The GenBI interaction runner adds exact multi-value drafts, full saved-domain
search, real chart-mark and keyboard selections, completed chart/report edits,
evidence inspection, narrow layouts and interrupted-stream recovery. It uses the
same isolated services and never sends provider requests.
The editorial runner adds title/chart placement, compact metrics, exact-value
keyboard access, matching metric/report format revisions, saved width edits,
review visibility, desktop/dark/phone captures and overflow checks.
The deployment runner rebuilds an isolated frontend copy. An already-open tab must
render its first chart after the previous hashed entry is removed, without another
script request. Do not rebuild the user's running assets to exercise this check.

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

Keep raw runs, Parquet, and HTML in the isolated receipt or workspace directory.
Record the model, source hashes, prompt IDs, run IDs, settings, elapsed time,
grading method, and limitations. Never commit credentials.

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

Use the [paired evaluation guide](ablation-evaluation.md) to freeze inputs,
grade paired runs independently, and compare a single change against the baseline.
It also documents the semantic study protocols and retained prompt-study evidence.

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
