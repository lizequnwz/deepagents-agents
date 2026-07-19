# Data Analytics Agent

A source-aware, human-reviewed conversational analytics POC built with Deep
Agents, FastAPI, and Streamlit.

The Data Analytics Agent delegates database questions to an isolated
text-to-SQL specialist. The specialist reads the selected OSI semantic model,
prepares one read-only query, and pauses for approve/edit/reject review before a
source-bound backend executes the exact reviewed SQL.

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
- Full capped results stored outside model context
- Streamlit result tables, CSV downloads, warnings, and source diagnostics
- Clear extension seams for Snowflake and future specialist agents

## Quick start

Prerequisites:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- `curl`
- OpenAI API key
- local database files expected by [`data_sources.yaml`](data_sources.yaml)

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env.
./scripts/start.sh
```

Open:

- App: `http://127.0.0.1:8501`
- API health: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`

The launcher runs `uv sync --locked`, validates the registry and source
readiness, starts FastAPI and Streamlit, and supervises both processes. Press
Ctrl+C to stop them.

## Use the agent

1. Select a ready source in the sidebar.
2. Ask a business question.
3. Inspect joins, filters, measures, dates, ordering, and row limit in the SQL
   review.
4. Approve, edit, or reject with feedback.
5. Inspect the answer, assumptions, interpretation, result table, executed SQL,
   and CSV.

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

[`SQLBackend`](text2sql_agent/backends/base.py) defines:

- `readiness_errors`
- `validate_sql`
- `execute`
- `list_tables`
- `get_table_schema`

Provider-specific connections, metadata, timeouts, row caps, and native safety
controls stay behind this contract. The current adapter is SQLite; Snowflake is
a conceptual future adapter, not an installed dependency.

See [Backend development](doc/backend-development.md) and the
[conceptual Snowflake blueprint](doc/snowflake-blueprint.md).

## Safety

- Registry targets and semantic files are trusted server configuration.
- SQLGlot permits one `SELECT`/CTE/set-operation query.
- Validation does not submit a preflight query.
- Every `execute_sql` action pauses for human review.
- Edited SQL is validated again.
- The backend executes the exact reviewed SQL.
- SQLite uses read-only mode, an authorizer, deadline, and capped fetch.
- Results carry both source and conversation provenance.
- Only a configured row sample enters model context.

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
- adding future specialist agents.

## Current limitations

This remains a local, single-user POC:

- conversations, runs, checkpoints, and results are process-local;
- the result HTTP endpoint is not a production authorization boundary;
- there is no authentication or durable persistence;
- Snowflake and visualization agents are not implemented;
- semantic models are curated manually;
- production deployment, audit, retention, and tenant isolation are out of
  scope.

The current-state implementation briefing and prioritized next work are in the
repository-level [`HANDOFF.md`](../HANDOFF.md).
