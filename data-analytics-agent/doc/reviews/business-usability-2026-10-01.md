# Business usability changes

1 October 2026. Implemented in the local working tree after the
[ablation and batch-review repair](ablation-outcomes-2026-10-01.md).

## Delivered behavior

- Excel setup uses worksheet choice, header/last-data row controls and optional
  first/last column letters. The preview carries Excel coordinates. Selected
  row/column counts and the exact range update before import; invalid ranges
  disable continuation. The original question waits for data confirmation.
- File review shows columns with notes first, with suggested types for every
  remaining column in a separate expandable editor. Row meaning/identifiers and
  original type details are available without filling the main review screen.
  Confirmation submits all column types and validates the entire population.
  Errors retain the selections so the user can correct and submit again.
- Confirmed file details show filename, population, worksheet/range, row meaning,
  identifiers and confirmed types. Unknown source freshness stays explicit.
  Original provenance and metadata remain available under technical details.
- The analysis ZIP is a native deferred download inside **Download data and
  calculations**. It prepares on click, using the displayed report revision;
  merely viewing an answer does not build a bundle. Streamlit provides loading
  and failure feedback. Unfinished answers disable this download. Plain-language
  guidance distinguishes browser-readable reports from local Python replay.
- Optional execution review shows purpose and bounded Python inputs first,
  with exact code behind expandable editors. No decision is preselected.
  Feedback appears only for requested changes; errors appear beside the affected
  proposal. A progress indicator and disabled primary button prevent incomplete
  batches. Per-proposal reset preserves other edits; applying submits the exact
  ordered batch.

SQL and Python review remain **off** in defaults, `.env.example` and the current
`.env`. Ordinary analysis still runs automatically. Mandatory upload confirmation,
one source/file per conversation, complete-population checks, original-scope
evidence and exact code execution remain in place. API/storage contract stays
**17**; this usability pass adds no new storage requirement or dependency.

## Verification

- Full suite: **378 passed, six skipped**, ten dependency warnings, in 160.64
  seconds. Command: `.venv/bin/python -m pytest -o addopts='' -q`.
  The six skipped tests are opt-in provider checks; they are not counted as passes.
  Notebook replay ran with the local loopback access its kernel needs.
- Static checks: `.venv/bin/ruff check data_analytics_agent streamlit_app.py tests
  scripts --select F` and `git diff --check` passed. Updated local documentation
  links resolve.
- Runtime: Python **3.13.13**, Streamlit **1.59.2**, API contract **17**.
  Raw local test output is in
  `.analytics/evaluations/business-usability-2026-10-01/test-results.txt`.

Focused automated interactions cover:

- Excel worksheet changes, row/column selection, invalid-range blocking, exact
  submitted range and retention of the original question.
- Real API file confirmation with both column groups edited, a duplicate-key
  error, preserved choices, successful correction, date/identifier fidelity and
  retention of all rows. Streamlit AppTest does not serialize data editors;
  the test explicitly sends their native widget state on each form submission.
- Exact ordered SQL edit/rejection, deliberate decisions, inline feedback
  validation, readiness gating and independent code resets.
- Native deferred-download registration and execution through the real API:
  no eager export, exact ZIP/report agreement, stale-report rejection, current
  revision on retry and disabled downloads for unfinished answers.
- Existing scripted real-agent flows with approval disabled, file isolation,
  chart/report completion, Stop/Resume, history reopening and portable replay.

These are deterministic implementation checks, using synthetic data. They do
not establish a measured improvement in task success or live-model accuracy.
No new provider evaluation or business-user study was run. No existing local
preview service was running; this revision's new browser loading animation,
visual layout and responsive behavior were not separately exercised. The dated
September browser screenshots describe the earlier UI.
