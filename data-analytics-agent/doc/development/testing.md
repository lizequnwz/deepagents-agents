# Testing the application

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
rather than inventing business answers or approving code. Recorded cases are
skipped on a subsequent invocation. A saved request without final receipts is
reattached by run ID; the question is not submitted again. Missing prerequisites
and recorded runs requiring attention stop the runner. Polling elapsed time on a
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
See the [26 September test record](../reviews/documentation-live-tests-2026-09-26.md).

## Reproducible grading and held-out cases

The runner stores a manifest containing the exact corpus and hashes of source DBs,
semantic catalogs, uploads, application code and instructions. Reusing a receipt
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
semantic-accuracy judge. [Dated evidence](../reviews/roadmap-evidence/README.md)
includes failing as well as passing trials and reproducible numeric checkers.
