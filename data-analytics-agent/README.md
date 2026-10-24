# Persistent Data Analytics Agent

A local, single-user analyst built with React, Streamlit, FastAPI and Deep Agents.
One coordinator and its SQL/Python specialists serve both interfaces. Conversations,
evidence, Python executions, charts, dashboards and HTML reports survive restarts.
Follow-up questions can reuse saved snapshots and derived datasets.

## Run

```bash
cp .env.example .env
# Set your key, model and SQL/Python approval preferences in .env, then start:
./scripts/start.sh
```

Open the React workspace at `http://127.0.0.1:8000/workspace/`. The native Streamlit
workbench remains available at `http://127.0.0.1:8501`. The API runs at
`http://127.0.0.1:8000`; `/docs` exposes its contract. Install Node.js/npm and `uv`
before starting. The launcher installs locked dependencies, builds React and checks
model configuration before starting the services. Restart both processes after
Python changes; rebuild React after client changes. Upload a CSV, Parquet or Excel file and
review its schema, or select a configured warehouse. The included SQLite sources
use `data_sources.yaml`; see [adding sources](doc/development/adding-data-sources.md)
to connect your own data.

The current API contract is **23**. Restart both services together and
choose fresh `ANALYTICS_STORAGE_DIR` storage for older incompatible history;
preserve needed artifacts separately. No migrations are provided.

For an existing checkout with older storage, start both services against a new
directory: `ANALYTICS_STORAGE_DIR=.analytics-v23 ./scripts/start.sh`.

Provider alternatives, execution limits, review settings, tracing, and development
reload are documented in [configuration](doc/development/configuration.md).
Try the [deep-dive test questions](doc/user/deep-dive-examples.md) for investigations,
saved-data follow-ups, a sample upload, and run-control checks.

## Workflow

- Select a configured source, or upload CSV, Parquet or a selected Excel table and
  confirm its column types. Use the chat **+** button for every attachment: more
  tables in a file conversation, or PDF/text/Markdown context in either source type.
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
- Type your question and choose **Send** for an answer or **Create dashboard**
  for an interactive view. You can also save a completed report as a dashboard.
  Reopen saved dashboards from the same workspace and inspect the report, data
  and conversation together. On phones, switch between Findings and Conversation.
- Add filters with explicit panel/column bindings. **Apply filters**, **Refresh
  data** and **Investigate** create normal reviewed analytical runs. The prior
  dashboard remains visible until its replacement evidence and HTML report succeed.
  Empty selections reset a filter; empty populations display a no-data state.
- **Save view** changes title, panel order/width and draft selections without a
  model or source query. Applied filters remain distinct from draft selections.
  Stale requests are rejected and repeated action requests resolve to their run.
- To use updated file data, attach and review the new version; earlier snapshots
  remain available. Warehouse refresh runs through the SQL specialist.
- Forecast evaluations save predictions, baseline/candidate MAE and RMSE,
  training/holdout windows and measured interval coverage separately from
  nominal coverage. Their tables and calculations are included in downloads.
- In the Streamlit workbench, use **Edit chart** to change a title, axis label, colors, or compatible chart
  type directly. Saving creates matching chart/report versions using saved data.
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
[user workflow](doc/user/using-the-agent.md), and [next implementation handoff](HANDOFF.md). The
[capability status](doc/roadmap/implementation-progress.md) records delivered behavior.
The [tutorial](agent_internals_tutorial.ipynb)
walks through the artifact workflow without a model call.

## Verify

```bash
uv run pytest
uv run ruff check data_analytics_agent streamlit_app.py tests --select F
node tests/ui/run.mjs
```

The deterministic suite tests typed extraction, 100,000-row continuity, iterative
Python with repair, saved-data SQL, report consistency and retry, lifecycle,
provider configuration and UI components. Opt-in model evaluations are separate;
they send the supplied fixture context to the configured provider and must be
explicitly enabled. They assess correctness and methodology rather than exact SQL.
The [React design verification](doc/reviews/react-ui-redesign-2026-10-22.md)
records the latest interface changes and browser checks. The
[dashboard verification](doc/reviews/genbi-workspace-2026-10-22.md) retains the
backend regression results, chart-loading repair and shared-theme checks.
The [18 October checkup](doc/reviews/checkup-2026-10-18.md) retains earlier analytical/replay checks. The three paired
semantic studies remain pending; verification stays local under the user's current
instruction.

The browser runner uses the production React build and the real local API with
isolated saved evidence. It also opens Streamlit. Its scripted agent exercises
the normal run manager without provider calls. See [browser verification](tests/ui/README.md)
for setup, covered journeys, screenshots and receipts.
