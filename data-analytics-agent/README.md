# Persistent Data Analytics Agent

A local, single-user analyst built with Streamlit, FastAPI and Deep Agents, with
an optional React workspace. One coordinator and its SQL/Python specialists serve
both interfaces. Conversations, evidence, Python executions, charts, dashboards
and HTML reports survive restarts. Follow-up questions can reuse saved snapshots
and derived datasets.

## Run

```bash
cp .env.example .env
# Set your key, model and SQL/Python approval preferences in .env, then start:
./scripts/start.sh
```

Open the Streamlit workbench at `http://127.0.0.1:8501`. The API runs at
`http://127.0.0.1:8000` and exposes its contract at `/docs`. Install `uv` and
`curl` before starting. The launcher installs locked Python dependencies and
checks model configuration before starting both services.

React is off by default (`ENABLE_REACT_UI=false`), so the launcher skips npm and
FastAPI leaves `/workspace/` disabled. To enable React, install Node.js with npm, set
`ENABLE_REACT_UI=true` in `.env` and restart the launcher. It builds React and adds
the workspace at `http://127.0.0.1:8000/workspace/` alongside Streamlit. Streamlit's
**Open full workspace** links appear when React is enabled.

Ask a question to let the analyst choose a configured source, or choose one
yourself. You can also upload a CSV, Parquet or Excel file and review its schema.
The included SQLite sources use `data_sources.yaml`. See
[adding sources](doc/development/adding-data-sources.md) to connect your own data.

The current API contract is **25**. Restart both services together after upgrading.
The change from contract 24 keeps the same saved history format. For older
incompatible history, use a fresh `ANALYTICS_STORAGE_DIR` and preserve needed
artifacts separately.

Provider alternatives, execution limits, review settings, tracing, and development
reload are documented in [configuration](doc/development/configuration.md).
Try the [deep-dive test questions](doc/user/deep-dive-examples.md) for investigations,
saved-data follow-ups, a sample upload, and run-control checks.

## Workflow

- With **Automatic**, the first question selects the source for the conversation.
  If the choice is unclear, pick a source or edit the question. Follow-ups stay
  on the selected source. Use **Attach file** in React or the chat **+** button
  in Streamlit to add tables to a file conversation or PDF/text/Markdown context
  to either source type.
  Extracted document tables require review before calculation. Reopen from history.
- **Understanding → Retrieving data → Analyzing → Findings ready → Preparing
  report** describes the current work. Descriptive questions may skip Python.
- Findings appear before report rendering. Every data-backed answer finishes
  with a downloadable HTML report. Metadata-only discussion needs no report.
- Click the microphone beside the question box, allow microphone access, speak,
  and stop recording. The transcription fills the box for review/editing; press
  Send when ready. Voice uses `OPENAI_API_KEY` and `TRANSCRIPTION_MODEL`
  (default `whisper-1`), including when the analytics model uses Bedrock.
- Ask follow-ups to refine charts or extend an investigation. Saved results are
  snapshots; ask for fresh/current data to execute source SQL again.
- In Streamlit, use **Saved dashboards** to save a completed report or reopen a
  dashboard. In React, choose **Send** for an answer or **Create dashboard** for
  an interactive view. React puts the report, data and conversation in one
  workspace, with separate Findings and Conversation panes on phones.
- In React, add filters with explicit panel/column bindings. **Apply filters** can use a
  validated SQL definition over complete saved data. **Refresh data** and
  **Investigate** retain the analytical specialists. All use the existing run and review controls. The prior
  dashboard remains visible until its replacement evidence and HTML report succeed.
  Empty selections reset a filter; empty populations display a no-data state.
- In React, **Save view** changes title, panel order/width and draft selections without a
  model or source query. Applied filters remain distinct from draft selections.
  Stale requests are rejected and repeated action requests resolve to their run.
- To use updated file data, attach and review the new version; earlier snapshots
  remain available. Warehouse refresh runs through the SQL specialist.
- Forecast evaluations save predictions, baseline/candidate MAE and RMSE,
  training/holdout windows and measured interval coverage separately from
  nominal coverage. Their tables and calculations are included in downloads.
- Use **Edit chart** on completed findings to change a title, axis label, colors, or compatible chart
  type directly. React and Streamlit save matching chart/report versions using saved data.
- Stop preserves committed artifacts. Resume continues interrupted work; after
  restart, unfinished work waits for an explicit Resume. A report failure can
  be retried without rerunning data retrieval or analysis.
- **Download data and calculations** offers an analysis ZIP, prepared on click,
  containing SQL query files, a portable Python script, notebook, typed data and saved report. Python
  steps replay locally with their exact workflow helper sources; SQL remains snapshot provenance.
- Evidence panels contain bounded previews, exact SQL/Python and full CSV and
  Parquet download links. Diagnostic images and HTML remain local artifacts.

## Analytical capabilities

Ask “Explore this dataset and investigate its strongest patterns,” “Explain this
change by segment,” “Compare cohort retention and funnel drop-off,” or “Compare
groups with uncertainty.” Prediction requests compare held-out models with a
baseline; forecasts save predictions, errors and intervals. Scenario questions
use declared assumptions. Multiple reviewed tables support preparation and keyed
joins. Documents provide cited context and reviewable extracted tables.

The analyst shows a plan for broad work and proceeds within approved scope. It
asks when business meaning or source expansion changes the answer. Statistical
associations do not establish causes; scenario outputs do not claim probabilities.

## Responsibilities

| Component | Owns |
|---|---|
| Coordinator | Routing, investigation plan, evidence selection, shared charts, findings and HTML report |
| Dashboard feature | Scoped saved views, explicit filter bindings, validated actions and immutable dashboard/report revisions |
| `text-to-sql` | Semantic grounding, source retrieval, descriptive analysis, value discovery and saved-data SQL |
| `data-analysis` | Iterative exploration, statistical analysis, predictive models, trends, seasonality, forecasting and evaluation |

Only SQL has a warehouse tool. Python receives named saved datasets and can
create reusable derived datasets. Each execution starts a fresh process:
`datasets` holds named pandas inputs, `analysis_outputs` holds compact outputs,
and `output_datasets` holds DataFrames to persist. There is no live notebook
kernel. Successful executions can be followed by more analysis; repairable
errors preserve earlier steps.

## Defaults

Both SQL and Python review are independently configurable and off by default.
Enabled review executes exact edited code with its original dataset bindings.
Each review shows every proposal in the interrupt and submits their decisions
together. Choose a decision for each proposal; none is preselected. Decisions
for an older review are rejected.
The active analysis budget is 15 minutes, individual Python execution 120
seconds, and presentation has a separate two-minute budget. Hard call limits stop further analysis and reserve bounded presentation calls.
Supported unfinished work is published as partial.

Uploads default to 32 MiB per file and 200 scalar columns. Files that exceed
row/decoded-size limits are rejected in full. CSV identifiers stay text until
explicit review; ambiguous slash dates require an explicit format or remain text.

A dataset permits up to one million rows and 256 MiB of uncompressed batches;
model previews contain at most ten rows. Incomplete extraction is explicit and
cannot be used as a complete population for Python. Decimal and temporal values
remain typed in Parquet. Numeric conversion for models/charts is explicit.
Chart presentation is separately bounded to 5,000 rows; downsampling is labeled
and retains lineage to the complete downloadable artifact.

## Storage and architecture

`ANALYTICS_STORAGE_DIR` defaults to `.analytics/`: SQLite metadata, a separate
SQLite graph checkpoint database, and an `artifacts/` directory containing
Parquet, HTML and diagnostic figures. FastAPI owns the AsyncSqliteSaver lifecycle.
Run IDs identify checkpoints; conversation IDs scope artifacts. Tool-call commits
reuse saved output during resumption. An execution interrupted before output
commit may execute again. Use a single API process for this local deployment.

See the [documentation index](doc/README.md), [architecture](doc/development/architecture.md),
[user workflow](doc/user/using-the-agent.md), and [implementation handoff](HANDOFF.md).
The [tutorial](agent_internals_tutorial.ipynb)
walks through the artifact workflow without a model call.

## Verify

```bash
uv run pytest
uv run ruff check data_analytics_agent streamlit_app.py tests --select F
```

The deterministic suite tests typed extraction, 100,000-row continuity, iterative
Python with repair, saved-data SQL, report consistency and retry, lifecycle,
provider configuration and UI components. Opt-in model evaluations are separate;
they send the supplied fixture context to the configured provider and must be
explicitly enabled. They assess correctness and methodology rather than exact SQL.
See the [testing guide](doc/development/testing.md) for test setup and evidence
requirements. Keep verification local unless a provider run is authorized.

The browser runner (`node tests/ui/run.mjs`) uses the production React build and
the real local API with isolated saved evidence. It also opens Streamlit. Its
scripted agent exercises the normal run manager without provider calls. See
[browser verification](tests/ui/README.md) for setup, covered journeys, screenshots
and receipts.
