# Data Analytics Agent

A source-aware, human-reviewed conversational analytics POC built with Deep
Agents, FastAPI, and Streamlit.

The Data Analytics Agent delegates database questions to an isolated
text-to-SQL specialist. The specialist reads the selected OSI semantic model,
prepares one read-only query, and pauses for approve/edit/reject review before a
source-bound backend executes the exact reviewed SQL.

When—and only when—the user explicitly requests a chart, the coordinator can
delegate one saved, chart-ready result to an optional visualization specialist.
That specialist receives an immutable full-result profile plus at most 10 rows,
validates one constrained Plotly `ChartSpec`, and returns an explicit terminal
outcome to the coordinator.

For statistical tests, experiments, correlations, distributions, regression,
and related inference, an optional statistical-analysis specialist consumes one
source/thread-scoped saved result by ID. It writes general Python, pauses for
approve/edit/reject review, then executes the exact reviewed code with the
saved data preloaded as pandas `df`. Compact tables, text, and bounded
matplotlib/seaborn figures return to the coordinator; the complete DataFrame
never enters an agent message.

For an explicit report, infographic, briefing, or data-story request, the
coordinator loads its report-design skill, reuses compatible artifacts or runs
missing analysis through the existing review flows, and produces a strict
`ReportSpec`. Trusted code renders one self-contained HTML file for isolated
Streamlit preview and immediate download; revisions remain conversational and
do not require an approve/finalize ceremony.

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
- Generic `SQLBackend` protocol with a hardened SQLite adapter
- Dialect-aware structural validation with SQLGlot
- Mandatory human review of every SQL execution
- Repeated rejection, revision, and reapproval cycles
- Exact edited-SQL execution and result provenance
- Optional, feature-flagged statistical-analysis specialist
- Mandatory review of every statistical Python execution and exact edited-code
  execution
- General pandas/NumPy/SciPy/statsmodels/scikit-learn analysis with bounded
  matplotlib/seaborn figures
- Truncated-result refusal, one SQL-reshape recovery, and three actual Python
  execution attempts at most
- Optional, feature-flagged visualization specialist using the existing model
- One automatically executed, constrained chart tool
- Bar, line, area, scatter, pie/donut, histogram, box, heatmap, and map charts
- Deterministic Plotly rendering with saved-result reconstruction
- Full capped results and eager column profiles stored outside model context
- At most `head(10)` rows visible to the coordinator and specialists
- No generated SQL limit unless the user explicitly requests one
- Streamlit result tables, CSV downloads, warnings, and source diagnostics
- Structured live activity showing named context, skills, agents, tools, and
  curated tool arguments
- Optional trusted-local debug views for redacted tool inputs and bounded
  per-agent state snapshots
- Optional Snowflake adapter over an injected `snowlib` client
- Feature-flagged coordinator reporting skill with open-ended design direction
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
2. Ask a business question.
3. Inspect joins, filters, measures, dates, ordering, and row limit in the SQL
   review.
4. Approve, edit, or reject with feedback.
5. For statistical inference, review the complete proposed Python and immutable
   input-result provenance before execution.
6. To visualize a regular saved result, explicitly ask for one chart.
7. Expand progress steps to inspect loaded skills, context files, tools, and
   curated arguments such as chart mappings.
8. Inspect statistical outputs or the rendered Plotly chart, parent table/CSV,
   exact Python, and executed SQL.

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

- `readiness_errors`
- `validate_sql`
- `execute`
- `list_tables`
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
- Every `execute_sql` action pauses for human review.
- Every `execute_statistical_python` action pauses for human review.
- `create_chart` executes automatically only after strict schema and
  result-scoped validation.
- Edited SQL is validated again.
- The backend executes the exact reviewed SQL.
- A bounded subprocess executes the exact reviewed Python with service secrets
  removed from its environment. It is not a production sandbox.
- SQLite uses read-only mode, an authorizer, deadline, and capped fetch.
- Per-agent model and tool-call budgets stop runaway loops and continue across
  SQL review resumptions.
- Results carry both source and conversation provenance.
- Only the full-result profile and at most the first 10 rows enter model
  context.
- Statistical execution refuses saved results marked `truncated`.

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
- visualization is intentionally limited to one validated chart over one saved
  result, without arbitrary Python or custom Plotly layout code;
- reviewed statistical Python is trusted-local code with filesystem, process,
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
