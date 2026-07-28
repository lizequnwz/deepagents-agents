# Project handoff: Data Analytics Agent

Last updated: 2026-07-27

## Executive summary

The active deliverable is [`data-analytics-agent/`](data-analytics-agent/), a local,
source-aware conversational analytics POC built with Deep Agents, FastAPI, and
Streamlit.

Each conversation is bound to one registered source and its required OSI
`0.1.1` semantic model, dialect, backend target, and limits. A coordinator
routes database work to an isolated text-to-SQL specialist. Every SQL execution
requires approve/edit/reject review.

The coordinator also has an optional visualization specialist. It is used only
when the user explicitly requests a chart, consumes one chart-ready saved
result through a full-result profile plus `head(10)`, validates exactly one
strict `ChartSpec`, and terminates explicitly before trusted application code
renders Plotly.

An optional statistical-analysis specialist now handles tests, experiments,
correlations, distributions, significance, regression, uncertainty, and
similar analysis. It consumes one source/thread-scoped saved SQL result by
result ID, writes general Python over a runtime-provided pandas `df`, and pauses
for approve/edit/reject review before every execution. The exact reviewed code
executes with bounded time/output capture; compact tables, text, scalars, and
figures are attached to the final result without copying the full dataset into
agent messages.

This remains a local, single-user, process-memory POC. It is not production
ready.

Flexible reporting is now implemented as a feature-flagged coordinator skill,
not a fourth specialist. The coordinator can reuse multiple same-thread,
same-source SQL/chart/statistical artifacts or invoke missing reviewed analysis,
then submit a strict `ReportSpec` to trusted code. The renderer produces
canonical self-contained HTML with scoped provenance, version lineage, CSP,
isolated Streamlit preview, and immediate byte-identical download.

The canonical Archify diagrams show the coordinator, three analytical
specialists, provider-neutral `SQLBackend`, reviewed execution boundaries,
artifact stores, coordinator-owned reporting, and Streamlit outputs.

## Start here

- [Project README](data-analytics-agent/README.md)
- [Developer documentation](data-analytics-agent/doc/README.md)
- [Architecture](data-analytics-agent/doc/architecture.md)
- [Using the agent](data-analytics-agent/doc/using-the-agent.md)
- [Safety and HITL](data-analytics-agent/doc/safety-and-hitl.md)
- [Operations and testing](data-analytics-agent/doc/operations-and-testing.md)
- [Reporting capability](data-analytics-agent/doc/reporting-capability.md)
- [Executable tutorial](data-analytics-agent/agent_internals_tutorial.ipynb)

Canonical Archify sources, interactive HTML, and dual-theme SVGs live in
[`data-analytics-agent/doc/diagrams/`](data-analytics-agent/doc/diagrams/).

## Confirmed design decisions

- Product/package: **Data Analytics Agent** / `data_analytics_agent`.
- Topology: coordinator in `coordinator.py`; specialists under `agents/`.
- Root `agent.py`: thin compatibility import only.
- Default general-purpose subagent: disabled.
- Model: existing configured model reused by all specialists.
- Source isolation: immutable per conversation and enforced below the UI.
- Execution budgets: strict per-run model and tool-call limits on the
  coordinator and each specialist; SQL/Python review resumptions retain their
  counters. Budget failure returns safe typed diagnostics naming the agent,
  budget, attempted count, and limit, with bounded secret-redacted tool
  payloads available only in opt-in debug mode.
- SQL: one reviewed read-only query; exact edited SQL executes.
- SQL limits: generated SQL has no default `LIMIT`; a limit appears only when
  the user explicitly requests a row count. The backend retrieval cap remains
  independent and configurable.
- Visualization activation: explicit chart/plot/graph/visualize/map request
  only.
- Visualization removal: global `ENABLE_DATA_VISUALIZATION` flag, default
  `true`; disabling it removes the subagent without changing SQL behavior.
- Statistical activation: tests, experiments, correlations, distributions,
  significance, regression, uncertainty, and similar inference route to
  `statistical-analysis` when enabled.
- Statistical removal: global `ENABLE_STATISTICAL_ANALYSIS` flag, default
  `true`; disabling it removes the subagent without weakening SQL or
  visualization behavior.
- Statistical input: exactly one source/thread-scoped saved SQL result by
  result ID. The specialist sees provenance, a full-result profile, and at
  most `head(10)`; reviewed Python receives the complete saved result as pandas
  `df` inside the execution process.
- Python review: every `execute_statistical_python` call pauses for
  approve/edit/reject. Exact edits are authoritative; rejection feedback
  returns to the specialist for revision. At most three actual executions are
  allowed, excluding review rejections.
- Python execution: trusted-local subprocess with a configurable timeout,
  bounded stdout/stderr, compact output limits, and no production sandbox or
  network-isolation claim.
- Statistical completeness: truncated results cannot produce
  `analysis_completed`; the specialist must request SQL reshaping, request
  clarification, or explain why analysis cannot proceed.
- Statistical outcomes: `analysis_completed`, `needs_sql_reshape`,
  `needs_clarification`, or `cannot_analyze`; the coordinator permits one
  reviewed SQL-reshape recovery cycle.
- Statistical result ownership: the specialist returns concise narrative;
  `RunManager` attaches the exact reviewed Python and authoritative captured
  outputs from `RunStore` after coordinator parsing. Streamlit renders those
  artifacts directly from `FinalAnswer.statistical_analysis`.
- Chart tool: one generic `create_chart` with a constrained declarative spec,
  never arbitrary generated Python or custom Plotly code.
- Chart execution: automatic after strict schema and result-scoped validation;
  there is no chart approval interrupt.
- Chart outcomes: `chart_created`, `needs_sql_reshape`, or `cannot_create`.
  The coordinator permits at most one reviewed SQL-reshape recovery cycle.
- Agent skills: `skills/text-to-sql/` contains the combined `query-writing`
  workflow; `skills/data-visualization/` contains `chart-design`; and
  `skills/statistics/statistical-analysis/` contains robust statistical-design
  and graphics guidance. Each specialist loads only its own namespace. System
  prompts retain only runtime goals, hard boundaries, tool stages, and terminal
  contracts.
- Reporting topology: a lazy-loaded coordinator skill, not a fourth subagent.
  The coordinator retains conversation context, may invoke existing specialists
  for missing evidence, and produces a structured `ReportSpec` for trusted
  rendering. Graduate reporting into a specialist only if measured context
  pressure, independent lifecycle needs, or specialist tooling justify the
  additional handoff.
- Report output: canonical self-contained HTML, combining multiple
  same-thread/same-source artifacts with provenance. A trusted deterministic
  renderer owns markup assembly and any audited JavaScript; the model cannot
  inject arbitrary scripts. Every safe Streamlit preview is downloadable and
  conversationally revisable without mandatory approval or finalization.
- Report design: style remains open-ended. Infographic, statistical
  report, executive briefing, exploratory report, comparison, and appendix are
  examples rather than an allowlist. UI/UX Pro Max guidance supplies
  accessibility, responsive layout, typography, chart, motion, and design-token
  quality checks.
- Chart progress: exposes chart type and a bounded subset of mappings while
  omitting the result ID and full tool payload.
- Output: one chart per request.
- Chart-ready contract: grouping, business transforms, and formulas belong in
  reviewed SQL. Presentation sorting, category limiting, horizontal bars,
  histogram bins, and box quartiles are allowed in the chart layer.
- Supported types: bar, line, area, scatter, pie/donut, histogram, box,
  heatmap, and map.
- Maps: coordinates, US ZIP/city-state centroid markers, US state
  choropleths, and ISO-country choropleths. ZIP polygons are out of scope.
- Results: capped process-local application artifacts. `ResultStore` retains
  every stored row and an eager immutable full-result profile; the coordinator
  and specialists receive at most `head(10)` plus that profile.
- Result discovery: `list_conversation_results` returns provenance and profile
  metadata without rows; `inspect_conversation_result` returns the same
  metadata plus `head(10)`. Agents cannot paginate through additional rows.
- UI retrieval: Streamlit automatically fetches every API page up to the
  retrieval cap and uses all stored rows for the table, CSV, and deterministic
  renderer. Capped results are labeled as truncated.
- Chart persistence: generated `ChartSpec` and canonical success message are
  stored in the completed turn; Plotly is reconstructed from its saved result,
  with no separate chart store.
- Statistical persistence: the successful `PythonExecutionResult` is retained
  in process-local `RunStore`, merged into the completed `FinalAnswer`, and
  saved under a reusable source/thread-scoped analysis ID. Binary figures are
  omitted from later model history but remain available to trusted report and
  Streamlit rendering until the API reloads.
- Report persistence: `ReportStore` retains exact self-contained HTML, validated
  specification, renderer version, input references, previous-version lineage,
  and SHA-256 content hash. FastAPI and Streamlit serve the stored bytes rather
  than reconstructing model-authored markup.
- Development reload: `./scripts/start.sh` enables Uvicorn reload and
  Streamlit run-on-save by default. API reload clears all process-local stores;
  use `API_AUTO_RELOAD=false ./scripts/start.sh` for a stable manual session.
- Runtime compatibility: Streamlit checks `api_contract_version` and blocks
  requests to a stale FastAPI process instead of silently running old code.
- Backend: all database execution is exposed through the provider-neutral
  `SQLBackend`; provider-specific behavior remains behind adapters.

## Current architecture

```text
Streamlit
  -> FastAPI source-bound conversation/run
  -> data-analytics coordinator
     -> per-run model/tool/task budgets
     -> text-to-SQL specialist
        -> per-run model/tool/execute_sql budgets
        -> OSI + SQL validation
        -> execute_sql HITL
        -> source-bound SQLBackend
        -> scoped SavedResult rows + immutable profile
     -> visualization specialist (explicit request + feature enabled)
        -> per-run model/tool budgets
        -> inspect profile + head(10)
        -> validate strict ChartSpec
        -> automatic create_chart or explicit failure outcome
        -> terminal result returned to coordinator
     -> statistical-analysis specialist (statistical request + feature enabled)
        -> per-run model/tool budgets + three actual executions maximum
        -> inspect scoped result provenance/profile + head(10) by result ID
        -> write general Python over runtime-provided pandas df
        -> execute_statistical_python HITL (approve/edit/reject)
        -> bounded exact-code execution + compact tables/text/scalars/figures
        -> terminal statistical outcome returned to coordinator
     -> report-design skill (explicit document request + feature enabled)
        -> discover same-thread/same-source results and analyses
        -> invoke missing SQL, visualization, or statistical work as needed
        -> validate strict declarative ReportSpec with no executable markup
        -> trusted renderer embeds required data/assets into standalone HTML
  -> provenance-checked FinalAnswer
  -> RunManager attaches authoritative statistical and report artifacts
  -> deterministic Plotly/statistical outputs + table/CSV + report iframe
  -> exact report HTML download from versioned process-local ReportStore
```

The feature folders are:

- [`agents/text_to_sql/`](data-analytics-agent/data_analytics_agent/agents/text_to_sql/)
- [`agents/visualization/`](data-analytics-agent/data_analytics_agent/agents/visualization/)
- [`agents/statistical_analysis/`](data-analytics-agent/data_analytics_agent/agents/statistical_analysis/)
- [`reporting/`](data-analytics-agent/data_analytics_agent/reporting/)
- [`skills/reporting/report-design/`](data-analytics-agent/skills/reporting/report-design/)

The visualization folder owns:

- strict schemas and chart-type rules;
- saved-result-scoped inspect/validate/create tools;
- presentation-only row shaping and readability limits;
- deterministic Plotly rendering;
- lazy `pgeocode` US ZIP/city-state centroid resolution.

The statistical-analysis folder owns:

- terminal outcome, execution-result, and compact output schemas;
- result-scoped inspection and reviewed-Python tools;
- exact-code child-process execution, timeout/failure handling, and bounded
  stdout/table/text/figure capture;
- source/thread/result provenance enforcement and execution-attempt accounting.

The reporting folder and coordinator skill own:

- open-ended requirement interpretation and UI/UX quality guidance;
- `ReportBrief`, strict typed `ReportSpec`, theme, artifact, and reference
  contracts;
- same-thread/same-source artifact resolution and report revision lineage;
- escaped semantic HTML, embedded charts/figures/data, restrictive CSP, print
  styling, renderer-owned theme interaction, and exact content hashing.

## Safety and provenance

Do not weaken these invariants:

1. One conversation has one immutable `source_id`.
2. Every SQL execution pauses before the database is touched.
3. Every statistical Python execution pauses before code runs; exact user edits
   are authoritative and rejection feedback returns for revision.
4. Statistical Python loads only the assigned source/thread-scoped result as
   `df`; the full dataset is never copied into agent messages.
5. Truncated data cannot produce a completed statistical inference.
6. Every chart is explicitly requested and validated before rendering.
7. Edited SQL is validated again.
8. Charts and statistical analyses remain tied to their scoped `result_id`.
9. Specialist result access requires current source and thread.
10. Final SQL is replaced with the exact SQL saved with the result.
11. Final charts are validated against that same saved result.
12. Final statistical artifacts use the exact reviewed Python and bounded
    outputs recorded by the application, not a coordinator reconstruction.
13. LangGraph checkpoints are isolated per run; conversation history, including
   chart success results, is explicitly reconstructed for the next turn.
14. Full result rows remain outside model messages except for at most the first
    10; deterministic tools may validate/render against all stored rows.
15. Agent execution budgets reset for a new run and persist across every
    approve/edit/reject resume of that run.
16. Reports combine only same-thread/same-source artifacts; model-authored
    values remain declarative data and never become executable HTML or scripts.
17. Every report reference is replaced with the exact stored ID, version,
    timestamp, and content hash; Streamlit verifies that hash before preview.

The chart renderer is trusted deterministic code. The model supplies only a
constrained, validated specification—not executable Python. Incompatible chart
points are not coerced from strings: line/area preserve null gaps; other chart
types exclude invalid points with visible warnings and fail when none remain.

Readability limits are enforced: pie/donut 12 slices, bar/box 30 categories,
heatmap 500 cells, and other charts use the configured result cap. A display
category limit requires explicit meaningful sorting and emits “Displaying X of
N.” Retrieval-cap truncation is also disclosed.

## Running locally

From `data-analytics-agent/`:

```bash
cp .env.example .env
# Set OPENAI_API_KEY.
./scripts/start.sh
```

The launcher watches Python, Markdown skills/policies, YAML configuration and
semantic models, and `.env`; FastAPI reloads and Streamlit reruns on changes.
Because API reload discards process-local state, disable it for a stable manual
test session:

```bash
API_AUTO_RELOAD=false ./scripts/start.sh
```

Endpoints:

- Streamlit: `http://127.0.0.1:8501`
- FastAPI health: `http://127.0.0.1:8000/health`
- FastAPI docs: `http://127.0.0.1:8000/docs`

`pgeocode` caches its generic US postal dataset on first map use.
`PGEOCODE_DATA_DIR` can override the cache location.

## Verification status

Last verified on 2026-07-27:

```text
146 passed, 1 skipped
```

The skip is the opt-in live OpenAI smoke test. Python compilation also passes.
Before relying on this handoff, rerun:

```bash
cd data-analytics-agent
uv run pytest
uv run python -m compileall -q \
  data_analytics_agent streamlit_app.py agent.py tests
```

Also execute the tutorial with live calls disabled, validate/render/check the
affected Archify diagram, validate both configured sources, and run
`git diff --check`.

The reporting implementation is covered by focused contract, scope, renderer,
versioning, API byte-identity, and Streamlit tests. The report-design skill
passes skill validation; full Python compilation and `git diff --check` pass.
The statistical-analysis implementation and follow-up debugging were also
checked through focused schema/HITL/runner/UI tests, a live current-code request
through SQL and Python review, API contract inspection, and Bash syntax
validation.

The refreshed system-architecture and SQL/Python-review diagrams both pass all
nine Archify showcase checks. Their exported dual-theme SVGs pass XML
validation and were visually reviewed in light and dark themes after one label-
fit correction round.

## Prioritized next work

### 1. Exercise and harden reporting with real conversations

Use a real model to exercise an infographic, a statistical report, and a
user-directed visual style through the complete UI. Cover reuse of prior
artifacts, missing-analysis routing through SQL/Python review, conversational
revision with `previous_report_id`, full-row table inclusion when explicitly
needed, and offline opening of the downloaded HTML.

Add browser-based accessibility and visual-regression checks at phone, tablet,
desktop, print, light, dark, reduced-motion, and keyboard-focused states. Add
offline geographic topology embedding before permitting map chart blocks in
reports. Keep reporting in the coordinator unless measured context pressure,
independent lifecycle needs, or specialist tooling establishes a concrete
reason for a fourth subagent.

### 2. Live statistical and visualization flows

Exercise the statistical path with a real model through SQL review, Python
review, successful execution, compact tables, and a diagnostic figure. Include
rejection/revision, edited Python, execution repair, truncation refusal, and one
SQL-reshape recovery. Confirm the coordinator owns final wording while the UI
renders the exact application-attached artifacts.

Use a real model to exercise:

1. a non-chart question (visualization must not route);
2. an explicit chart request with chart-ready SQL;
3. automatic chart generation with visible type/mapping progress;
4. a chart request requiring a second reviewed SQL result;
5. rehydration of a generated chart and its success message;
6. a partially resolved ZIP/city-state map.

### 3. Production hardening

- authentication and source/result authorization;
- durable stores and LangGraph checkpoints;
- managed secrets and connection lifecycle;
- approval/audit records for exact SQL, reviewed Python, and chart specs;
- redacted observability;
- cancellation, retries, rate limits, and concurrency policy;
- retention, deletion, backup, tenant isolation, and least privilege.

### 4. Deferred visualization and orchestration hardening

Keep the current POC tolerant and simple until real usage justifies these:

- add a small prompt-evaluation suite for routing, skill loading, human-edited
  scope, terminal chart behavior, and one-cycle SQL reshaping before tightening
  prompts further;
- add strict full-column validation/coercion policies with configurable
  thresholds for mixed values, invalid dates, nulls, infinities, and
  nonnegative measures;
- add explicit data-cleaning policies instead of only excluding incompatible
  points with visible warnings;
- replace generic DeepAgents `task` assignments with typed SQL, visualization,
  and statistical dispatch inputs after the orchestration contract stabilizes;
- enforce the one-reshape limit in deterministic graph state rather than
  coordinator instructions;
- add a separate `density_heatmap` type for automatic two-dimensional numeric
  binning/counting; keep standard heatmap binning and aggregation in SQL;
- persist chart-validation diagnostics as structured error codes for richer UI
  guidance and telemetry;
- move `ResultStore` and checkpoints to durable, shared storage with retention,
  expiry, authorization, and multi-worker consistency;
- persist derived statistical outputs under a scoped result/artifact ID so they
  can be reused and visualized without rerunning the analysis;
- add deterministic summary tools for follow-ups that need facts beyond
  `head(10)` without exposing model-side row pagination;
- profile source-native types where adapters can supply them, while retaining
  deterministic value-based fallback and confidence reporting.

## Known limitations

- API restart clears conversations, runs, checkpoints, and results.
- Development auto-reload therefore clears conversations, SQL results,
  approvals, and statistical outputs whenever a watched API file changes.
- The local result HTTP endpoint is not a production authorization boundary.
- Registry/readiness changes require reload or restart when auto-reload is
  disabled.
- Reports and reusable statistical analyses are process-local and are not an
  authenticated production authorization boundary; API reload removes them.
- Self-contained report maps are rejected until geographic topology can be
  embedded without a network dependency.
- Chart generation is deliberately one-chart, declarative, and non-extensible
  at runtime.
- Statistical Python is trusted-local reviewed code, not a production sandbox;
  its bounded reusable output artifacts remain process-local.
- Mixed-value chart validation is intentionally tolerant for the POC; invalid
  points can be excluded with visible warnings.
- ZIP/city maps depend on generic centroid lookup, not boundary geometry.
- OSI generation remains manual.
