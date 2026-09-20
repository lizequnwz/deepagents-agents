# Persistent Data Analytics Agent

A local, single-user analyst built with Streamlit, FastAPI and Deep Agents.
Conversations, evidence, Python executions, charts and HTML reports survive
restarts. Follow-up questions can reuse saved snapshots and derived datasets.

## Run

```bash
cp .env.example .env
# Set your key, model and SQL/Python approval preferences in .env, then start:
./scripts/start.sh
```

Open Streamlit at `http://127.0.0.1:8501`. The API runs at
`http://127.0.0.1:8000`; `/docs` exposes its contract. Restart both processes after
code changes. The launcher installs the locked dependencies and checks model
configuration before starting either service. Upload a CSV/Parquet file and
review its schema, or select a configured warehouse. The included SQLite sources
use `data_sources.yaml`; see [adding sources](doc/development/adding-data-sources.md)
to connect your own data.

Provider alternatives, execution limits, review settings, tracing, and development
reload are documented in [configuration](doc/development/configuration.md).
Try the [deep-dive test questions](doc/user/deep-dive-examples.md) for investigations,
saved-data follow-ups, a sample upload, and run-control checks.

## Workflow

- Select a configured source, or upload one CSV/Parquet file and confirm its
  column types. Each file has its own conversation. Reopen either from history.
- **Understanding → Retrieving data → Analyzing → Findings ready → Preparing
  report** describes the current work. Descriptive questions may skip Python.
- Findings appear before report rendering. Every data-backed answer finishes
  with a downloadable HTML report. Metadata-only discussion needs no report.
- Ask follow-ups to refine charts or extend an investigation. Saved results are
  snapshots; ask for fresh/current data to execute source SQL again.
- Use **Edit chart** to change a title, axis label, colors, or compatible chart
  type directly. Saving creates matching chart/report versions using saved data.
- Stop preserves committed artifacts. Resume continues interrupted work; after
  restart, unfinished work waits for an explicit Resume. A report failure can
  be retried without rerunning data retrieval or analysis.
- Evidence panels contain bounded previews, exact SQL/Python and full CSV and
  Parquet download links. Diagnostic images and HTML remain local artifacts.

## Responsibilities

| Component | Owns |
|---|---|
| Coordinator | Routing, investigation plan, evidence selection, shared charts, findings and HTML report |
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
The active analysis budget is 15 minutes, individual Python execution 120
seconds, and presentation has a separate two-minute budget. Framework call
limits remain emergency stops. Partial work is identified as partial.

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
[user workflow](doc/user/using-the-agent.md), and [deferred work](HANDOFF.md). The
[implementation log](doc/roadmap/implementation-progress.md) tracks roadmap delivery.
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
