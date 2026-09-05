# Data Analytics Agent

A source-aware, approval-configurable conversational analytics POC built with Deep
Agents, FastAPI, and Streamlit.

The Data Analytics Agent delegates database questions to an isolated
text-to-SQL specialist. Each source's OSI model is parsed once into an immutable
semantic catalog. The specialist searches that catalog, fetches only the
relevant datasets, fields, metrics, and declared relationships, prepares one
read-only query, validates it, and either executes immediately or pauses for
approve/edit/reject according to `REQUIRE_SQL_APPROVAL`.

The coordinator uses the same catalog's business-facing projection for
metadata-only research. It can explain available data, propose supported
analyses and hypotheses, identify limitations, and produce executable analysis
briefs without running SQL or creating empty charts and reports.

For broader questions, the coordinator plans a sequential investigation and
combines several source/thread-scoped SQL results. Every ordinary data-bearing
answer then attempts one useful chart over the most explanatory final result.
The optional visualization specialist receives an immutable full-result profile
plus at most 10 rows,
validates one constrained Plotly `ChartSpec`, and returns an explicit terminal
outcome to the coordinator.

When uncertainty or modeling materially improves the answer, an optional
statistical-analysis specialist handles experiments, regression, trend
inference, seasonality, forecasting, and related analysis over one
source/thread-scoped saved result by ID. It writes general Python, then either
pauses for approve/edit/reject or executes immediately according to
`REQUIRE_PYTHON_APPROVAL`; the exact submitted or edited code runs with the
saved data preloaded as pandas `df`. Compact tables, text, and bounded
matplotlib/seaborn figures return to the coordinator; the complete DataFrame
never enters an agent message.

Every successful evidence-backed analysis also produces a compact HTML report.
After final evidence, optional statistics, and the ordinary automatic chart are
complete, the coordinator loads its report-design skill and produces a strict
`ReportSpec` over those same artifacts. Trusted code renders one self-contained
file for isolated Streamlit preview and immediate download. Explicit report,
infographic, briefing, and data-story requests can still control audience,
structure, and visual direction; revisions remain conversational and do not
require an approve/finalize ceremony.

Included local sources:

- **Chinook music store** — catalog, customers, invoices, and playlists
- **Financial services** — accounts, clients, transactions, cards, orders, and
  loans

Every selectable source requires a valid Apache Ossie/OSI `0.1.1` semantic
model.

![Data Analytics Agent architecture](doc/diagrams/system-architecture.svg)

[Interactive architecture diagram](doc/diagrams/system-architecture.html) ·
[Developer documentation](doc/README.md) ·
[Executable tutorial](agent_internals_tutorial.ipynb)

## What it demonstrates

- Trusted registry for multiple semantic data sources
- Conversation-per-source isolation and URL rehydration
- Source-specific agent graph, OSI model, dialect, limits, and backend
- Cached immutable OSI catalog with bounded overview and deterministic lexical
  discovery
- Role-specific semantic tools for entity details and declared join paths
- Metadata-only research that transitions into the existing analysis workflow
- Generic `SQLBackend` protocol with a hardened SQLite adapter
- Dialect-aware structural validation with SQLGlot
- Independently configurable SQL and statistical-Python approval
- Repeated rejection, revision, and reapproval cycles
- Exact edited-SQL execution and result provenance
- Optional, feature-flagged statistical-analysis specialist
- Exact autonomous or human-edited SQL/Python execution provenance
- General pandas/NumPy/SciPy/statsmodels/scikit-learn analysis with bounded
  matplotlib/seaborn figures
- Truncated-result refusal, one SQL-reshape recovery, and one targeted Python
  repair after the initial execution at most
- Optional, feature-flagged visualization specialist using the existing model
- One automatically selected, constrained chart per ordinary data answer
- Bar, line, area, scatter, pie/donut, histogram, box, heatmap, and map charts
- Deterministic Plotly rendering with saved-result reconstruction
- Full capped results and eager column profiles stored outside model context
- Multi-result final evidence with trusted primary-first scoped references
- At most `head(10)` rows visible to the coordinator and specialists
- No generated SQL limit unless the user explicitly requests one
- Streamlit result tables, CSV downloads, warnings, and source diagnostics
- Structured live activity showing named context, skills, agents, tools, and
  collapsed bounded tool inputs and outputs
- In-memory run and conversation diagnostics for provider-reported tokens,
  elapsed/active/review time, per-agent aggregates, and tool durations
- Rotating bounded API logs with redacted tool results in every mode
- Optional trusted-local debug views for bounded per-agent state snapshots
- Optional Snowflake adapter over an injected `snowlib` client
- Automatic feature-flagged coordinator reporting with open-ended explicit
  design direction
- Accessible self-contained HTML reports with reproducible SQL, scoped
  provenance, versioning,
  isolated preview, and byte-identical download

## Quick start

Prerequisites:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- `curl`
- OpenAI API key or AWS credentials with Bedrock model access
- local database files expected by [`data_sources.yaml`](data_sources.yaml)

```bash
cp .env.example .env
# Choose MODEL_PROVIDER/MODEL_ID and configure its credentials in .env or
# through the standard AWS credential chain.
./scripts/start.sh
```

Open:

- App: `http://127.0.0.1:8501`
- API health: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`

The launcher runs `uv sync --locked`, validates the registry and source
readiness, starts FastAPI and Streamlit, and supervises both processes. Press
Ctrl+C to stop them.

Development auto-reload is enabled by default. FastAPI watches only Python
source inside `data_analytics_agent/`, using Uvicorn's default `*.py` filter;
the project `.venv` is outside the watched tree. Streamlit reruns independently
when its watched source changes. Restart FastAPI manually after changing
`.env`, Markdown policies/skills, source YAML, or semantic models. Because all
POC stores are process-local, a FastAPI reload clears conversations, saved SQL
results, in-flight reviews, statistical analyses, and report versions. Disable
reload when retaining a manual test session matters:

```bash
API_AUTO_RELOAD=false ./scripts/start.sh
```

## Use the agent

1. Select a ready source in the sidebar.
2. Choose a source example to prefill the chat box for editing, or write your
   own business question, then send it.
3. When SQL approval is enabled, inspect joins, filters, measures, dates,
   ordering, and row limits, then approve, edit, or reject with feedback.
4. For statistical inference, review the complete proposed Python when Python
   approval is enabled.
5. Let the coordinator choose one useful chart automatically, or name an exact
   chart type to make it authoritative.
6. Open the automatically generated report in a full-page reading view or
   download its identical HTML, and optionally request a different audience,
   structure, or visual treatment.
7. Expand progress steps to inspect each tool's bounded, recognized-secret-key-
   redacted input and output.
8. Inspect every supporting table/CSV, exact SQL, statistical outputs, rendered
   Plotly chart, and exact executed Python.
9. Expand run diagnostics, or the sidebar conversation diagnostics, to inspect
   operational usage and timing.

Changing source starts a new conversation. **New conversation** retains the
selected source. Previous conversations remain available through their URLs
until FastAPI restarts.

See [Using the agent](doc/using-the-agent.md) for the full workflow and common
failures.

## Data sources

[`data_sources.yaml`](data_sources.yaml) is the trusted catalog:

```yaml
version: 1
default_source: chinook

backends:
  local_sqlite:
    type: sqlite

sources:
  chinook:
    name: Chinook music store
    backend: local_sqlite
    semantic_model: semantic/chinook.osi.yaml
    dialect: sqlite
    target:
      path: db/chinook/chinook.db
```

A source is unavailable when its target, OSI structure, physical tables, or
simple field expressions fail readiness validation. One broken source does not
disable healthy sources.

To add another SQLite source, create a curated OSI file under `semantic/`, add
the source to the registry, restart FastAPI, and verify readiness. See
[Adding data sources](doc/adding-data-sources.md) and
[Semantic-model best practices](doc/semantic-model-best-practices.md).

## Backend extension

[`SQLBackend`](data_analytics_agent/backends/base.py) defines:

- `execute`
- `get_table_schema`

Provider-specific connections, metadata, timeouts, row caps, and native safety
controls stay behind this contract. SQLite is built in. Snowflake is available
through an optional thin adapter over the separately provided `snowlib` client;
SQLite-only installations do not import or initialize `snowlib`.

See [Backend development](doc/backend-development.md) and the
[Snowflake backend guide](doc/snowflake-blueprint.md).

## Safety

- Registry targets and semantic files are trusted server configuration.
- SQLGlot permits one `SELECT`/CTE/set-operation query.
- Validation does not submit a preflight query.
- SQL and Python interrupts are controlled independently by deployment settings;
  autonomous mode preserves every validation and execution limit.
- `create_chart` executes automatically only after strict schema and
  result-scoped validation.
- Submitted or human-edited SQL is validated once by the backend immediately
  before execution.
- The backend executes the exact submitted or human-edited SQL.
- A bounded subprocess executes the exact submitted or human-edited Python with service secrets
  removed from its environment. It is not a production sandbox.
- SQLite uses read-only mode, an authorizer, deadline, and capped fetch.
- Per-agent model and tool-call budgets stop runaway loops and continue across
  SQL review resumptions.
- Results carry both source and conversation provenance.
- Only the full-result profile and at most the first 10 rows enter model
  context.
- Statistical execution refuses saved results marked `truncated`.
- Saved result IDs are opaque evidence handles, never database table names.
- Expected SQL validation and provider query errors return to the specialist
  for bounded repair instead of failing the whole run immediately.

Read [SQL safety and human review](doc/safety-and-hitl.md) before changing
validation, approval, execution, or result access.

## Tests

```bash
uv run pytest
```

The normal suite uses deterministic fakes for agent/cloud boundaries. The live
OpenAI smoke test is opt-in:

```bash
RUN_LIVE_SMOKE=1 uv run pytest -m live
```

See [Operations and testing](doc/operations-and-testing.md) for readiness,
notebook, documentation, and diagram checks.

## Documentation

Start at [`doc/README.md`](doc/README.md). It provides learning paths for:

- operating the app;
- adding sources and OSI models;
- implementing database backends;
- changing safety/HITL;
- understanding the text-to-SQL, visualization, and statistical specialists;
- using or extending the coordinator reporting skill and self-contained HTML
  renderer.

## Current limitations

This remains a local, single-user POC:

- conversations, runs, checkpoints, and results are process-local;
- the result HTTP endpoint is not a production authorization boundary;
- there is no authentication or durable persistence;
- Snowflake requires the external `snowlib` package, its environment/config,
  and a least-privilege default role/database/schema context;
- visualization is intentionally limited to one validated top-level chart over
  one final evidence result, without arbitrary Python or custom Plotly layout;
- statistical Python is trusted-local code with filesystem, process,
  and network capabilities; production sandboxing is out of scope;
- completed statistical outputs and report versions are process-local reusable
  artifacts and disappear on API reload;
- self-contained report maps are not yet supported because offline geographic
  topology is not embedded;
- semantic models are curated manually;
- production deployment, audit, retention, and tenant isolation are out of
  scope.

The current-state implementation briefing and prioritized next work are in the
repository-level [`HANDOFF.md`](../HANDOFF.md).
