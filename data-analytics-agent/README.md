# Persistent Data Analytics Agent

A local, single-user analyst built with Streamlit, FastAPI and Deep Agents.
Conversations, evidence, Python executions, charts and HTML reports survive
restarts. Follow-up questions can reuse saved snapshots and derived datasets.

## Run

```bash
uv sync
cp .env.example .env
# Configure your model credentials and sources in .env / data_sources.yaml.
./scripts/start.sh
```

Open Streamlit at `http://127.0.0.1:8501`. The API runs at
`http://127.0.0.1:8000`; `/docs` exposes its contract. Restart both processes after
code changes. Existing obsolete in-memory state is not migrated.

## Workflow

- Select a configured source and ask a question, or reopen a saved conversation.
- **Understanding → Retrieving data → Analyzing → Findings ready → Preparing
  report** describes the current work. Descriptive questions may skip Python.
- Findings appear before report rendering. Every data-backed answer finishes
  with a downloadable HTML report. Metadata-only discussion needs no report.
- Ask follow-ups to refine charts or extend an investigation. Saved results are
  snapshots; ask for fresh/current data to execute source SQL again.
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

See [architecture](doc/architecture.md), [operations and tests](doc/operations-and-testing.md),
[reporting](doc/reporting-capability.md), [user workflow](doc/using-the-agent.md),
and [deferred work](HANDOFF.md). The [tutorial](agent_internals_tutorial.ipynb)
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
