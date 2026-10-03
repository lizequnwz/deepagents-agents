# Priority analytics releases: local verification

Subsequent testing and contract-19 repairs are recorded in
[extended local verification](priority-followup-tests-2026-10-02.md). This initial
record retains its original contract and test counts.

Date: 1 October 2026 (America/New_York). Changes are in the local working tree;
no commit or deployment was made. API/storage contract 18; new portable bundles
use format 2. Restart both services together and choose fresh incompatible storage,
preserving needed artifacts separately. No migrations or compatibility readers.

## Authorization and evidence level

The user instructed: **Keep verification local for now.** No new live provider
study was run. All new checks use generated synthetic data, scripted model responses
or direct local calculations. Provider tests remain opt-in and skipped. Browser
checks use the actual Streamlit interface and FastAPI with a scripted agent; they
verify product interactions, not model accuracy, speed or business-user success.

The five batches were built in order over the existing product. Existing lexical
ranking/cache/synonyms, small inline catalogs, exact definitions, specialists,
Python runner, multi-series charts, presentation edits and mandatory HTML remain
in place. No embedding/vector system, query repository, algorithm registry,
scheduling or execution isolation was added.

## Batch 1: semantic discovery and reliable SQL

The existing corpus has **40 cases**, including **20 timed semantic cases**,
a semantic clarification and file/statistical/lifecycle controls. The builder
provides a two-dataset inline catalog and a 102-dataset competing catalog over
frozen synthetic source data. Expectations name measures, dimensions, filters,
time roles, routes, output grain and clarification outcomes. No new business
catalog synonyms or meanings were invented without an evidenced reviewed miss.

The runner preserves every returned complete SQL snapshot, including attempts
not selected in the final report. Independent snapshot reviews determine the first
correct result; missing reviews cannot produce first-correct timing. The grader
independently checks declared scalar values against full typed Parquet bindings.
Definition recall and query grounding recall are separate. Metrics retain errors,
repairs, cumulative input context, discovery time, model time and source time
(including category lookup); active time excludes approval waits.
Small-catalog definitions actually supplied in the specialist's system prompt
count as available without requiring redundant discovery. Only matching trusted
system context creates this receipt; user content cannot forge it. Availability
still does not certify that the generated query grounds every required entity.

Role batching uses the existing discovery tool and lexical index. Exact SQL
relationship payloads include all physical key pairs, including composites.
Structured SQL feedback adds relevant details and repair guidance while retaining
canonical metric, route, key and fan-out enforcement. Specialist coverage remains
an assessment; candidates and resolved selections never certify question coverage.
Coordinator routing already gives the specialist detailed discovery ownership.

Separate protocols cover [routing](../roadmap/semantic-routing-study.json),
[role batching](../roadmap/semantic-role-batching-study.json) and
[join feedback](../roadmap/semantic-join-feedback-study.json). The comparator
requires complete paired outcomes and controls. Targeted quality scenarios need
reviewed paired baseline-fail/candidate-pass evidence in every repetition. Speed
gates need at least 15% median improvement in active time to the first independently
correct SQL snapshot. Fabricated reducer tests exercise these mechanical gates;
they are explicitly not model-quality receipts.

**Remaining gate:** three fresh independently graded baseline/candidate repetitions
per isolated change, with no new failures or boundary violations. No new live
accuracy, retrieval improvement or speed claim is established. The retained prior
trial identified join errors/redundant calls and did not establish lexical misses.

## Batch 2: explicit saved inputs

The native Analyze selector accepts complete source snapshots, reviewed uploads
and Python-derived datasets. Labels, population, completeness, saved question,
grain and applied filters appear beside the composer. Chart presentation data and
incomplete extracts are excluded. The dedicated analytical request carries an
optional exact selected reference; corrections and clarifications remain separate.

Application-owned specialist briefs carry the exact input ID. Execution and
publication enforce it, including edited bindings. Every contributing lineage
path must reach an allowed input: a reused dataset that mixes the selected
snapshot with broader saved data is rejected. Independent derivations from the
same input and combinations of several fresh inputs remain valid. References
persist in run/checkpoint context, history, answers, reports and exports.

The real harness exercised clarification, Stop, service restart, Resume and a
clarification reply with the same selected ID. Stale clarification IDs are rejected.
Text alone does not authorize source expansion; an explicit decision on the current
scope question does. Structural missing detail and unsuitable supported aggregate
periods produce feedback. General business grain still requires specialist judgment.

## Batch 3: forecast evaluation

Named predictions and recomputed scores carry training/holdout windows, forecast
origin/start, frequency, horizon, candidate/baseline method, interval meaning and
sample size. MAE and RMSE recompute through trusted SQL; portable replay independently
recomputes them with NumPy. Measured holdout coverage remains distinct from nominal
coverage. Short holdouts disclose unstable estimates. Missing/duplicate periods,
nonfinite predictions, inverted bounds, future actuals, text values and overlapping
windows are rejected with repairable feedback.

Tests include short/noisy series and structural breaks. The portable example fits
its evaluation candidate on earlier training data and scores later untouched
observations, then refits for future forecasts. Boundary checks and inspectable code
support leakage review; they do not prove arbitrary Python preparation/fitting code
is leakage-free. Chronological metadata must not be sold as that proof.

Existing multi-series line charts now attach the band to interval_series and mark
forecast_start. Chat, HTML, notebook and downloadable tables carry the same
descriptor and scores. HTML retains evaluation evidence even when optional execution
diagnostics are hidden. A bundle moved to another directory passed script replay
and fresh-kernel notebook execution with score/coverage recomputation.

## Batch 4: shared saved-data scope

Categories and inclusive typed date ranges materialize a complete saved input;
a new analytical turn uses the existing business question and accepted corrections.
Metrics, chart data, tables, narrative, HTML, manifest and package README agree.
Empty populations retain their schema. Supported SQL month/quarter/year aggregates
reject split-period boundaries. Arbitrary aggregate suitability still needs analysis.

Native-widget/API checks exercise category selection, scope application, stale
requests and reopened history. The browser selected a three-row snapshot, filtered
Name=Alpha to two rows, and showed matching answer, chart and HTML. A second view
reopened the saved scope; its open form was rejected after the first view created
a newer report revision. Previous successful findings stay available during work.

## Batch 5: manual warehouse refresh

A new source-backed run preserves the current question/corrections and links its
report revision to the old one. Selected base data must be regenerated from fresh
SQL and rebound before its stored scope is applied; old-only or mixed-old inputs
cannot satisfy the fresh-run boundary. Field/type equivalence is checked, while
business-grain equivalence remains an analytical responsibility.

A local SQLite source was changed from three saved artist rows to four current
rows. Fresh SQL returned four rows; reapplying Alpha scope produced three current
rows, a new report revision and a new input ID. The old two-row filtered input and
three-row base remained unchanged. A failed refresh retained the last report,
verified through API, native widgets and browser. File refresh was rejected with
useful new-upload/conversation feedback. Query/snapshot times remain distinct from
explicit source cutoff or completeness declarations.

## Verification commands and results

The final deterministic suite passed **423 tests**, with **six provider tests
skipped**, in 122.17 seconds. Final lineage review added two population-boundary
regressions; the focused scope/workflow/parallel suite passed **24 tests**.
Inline-definition measurement added two further regressions; the focused
semantic/workflow/comparator suite passed **80 tests** before the final full run.

Commands: `.venv/bin/python -m pytest -o addopts='' -q` and
`.venv/bin/ruff check data_analytics_agent streamlit_app.py scripts tests --select F`.
Ruff and `git diff --check` pass. Existing framework/HTTP-client/DuckDB deprecation
warnings do not establish failed tests. Notebook kernels needed permission to bind
local loopback ports; no provider calls were enabled.

Browser receipts: [compact local record](priority-browser-evidence-2026-10-01.json).
Initial preview semantic-path/stub-resume setup failures are retained in that record;
the fixture was corrected before the positive selection/scope flow. These fixture
failures are not a model-quality grade. Temporary services use separate storage and
local synthetic rows, leaving existing analytical storage and source data untouched.
Both temporary services and their verification tabs were closed after the checks.
No normal app services were running at handoff; start both together with a fresh
contract-18 storage directory as described in the README.

Redundant scope and refresh screenshots were removed during the 3 October
documentation cleanup. The compact browser record retains the observations.

## Remaining validation and product boundaries

- Live paired accuracy/speed studies require new provider/fixture authorization.
- Business-user scope recognition and analyst replay observations remain pending.
- Arbitrary grain, source join correctness and Python leakage require independent
  assessment beyond structural checks and score recomputation.
- Source completeness remains unknown unless explicitly declared; observed final
  transaction dates and query times do not establish a cutoff.
- One source/file per conversation, explicit upload review, SQL-only warehouse
  access, declared units, immutable evidence and required HTML remain enforced.
- Hybrid/verified-query retrieval, scheduling and execution isolation stay deferred.
