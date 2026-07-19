# Project handoff: Data Analytics Agent

Last updated: 2026-07-18

## Executive summary

The active deliverable is [`data-analyst-agent/`](data-analyst-agent/), a local
source-aware conversational analytics POC.

It now supports multiple trusted data sources rather than being a
Chinook-specific agent:

- Chinook music store
- Financial services

Each conversation is permanently bound to one registered source. The source
selects a required OSI `0.1.1` semantic model, SQL dialect, backend target,
execution limits, description, and starter questions.

A Deep Agent coordinator delegates database questions to an isolated
text-to-SQL specialist. Every SQL execution pauses for approve/edit/reject
review. The generic `SQLBackend` contract isolates database-specific
validation, execution, metadata, deadlines, caps, and native safety controls.
SQLite is implemented; Snowflake is the prioritized future adapter.

This is intentionally a local, single-user, process-memory POC. It is not
production-ready.

## Documentation

Start with:

- [Project README](data-analyst-agent/README.md)
- [Developer documentation index](data-analyst-agent/doc/README.md)
- [Architecture](data-analyst-agent/doc/architecture.md)
- [Using the agent](data-analyst-agent/doc/using-the-agent.md)
- [Adding data sources](data-analyst-agent/doc/adding-data-sources.md)
- [Backend development](data-analyst-agent/doc/backend-development.md)
- [Safety and HITL](data-analyst-agent/doc/safety-and-hitl.md)
- [Operations and testing](data-analyst-agent/doc/operations-and-testing.md)
- [Conceptual Snowflake blueprint](data-analyst-agent/doc/snowflake-blueprint.md)
- [Executable tutorial](data-analyst-agent/agent_internals_tutorial.ipynb)

Canonical Archify diagrams live under
[`data-analyst-agent/doc/diagrams/`](data-analyst-agent/doc/diagrams/), with
editable JSON, interactive HTML, and dual-theme SVG assets.

## Confirmed design decisions

- Product name: **Data Analytics Agent**.
- Audience: Python and agent developers.
- Source registry: trusted repository YAML; no arbitrary user uploads.
- Semantic model: required per source; invalid/missing OSI blocks that source.
- Conversation: one immutable source; switching source creates a new thread.
- New conversation: keeps the selected source.
- URL: stores `thread_id` for refresh/bookmark/history rehydration.
- Source selector: disabled while a run or SQL review is active.
- Agent topology: coordinator plus explicit text-to-SQL specialist; no default
  general-purpose subagent.
- SQL review: every execution uses built-in HITL approve/edit/reject.
- Rejection: revision loop, not terminal completion.
- SQL execution: exactly the reviewed text; no invisible limit rewrite.
- SQL validation: one read-only SELECT/CTE/set-operation in source dialect.
- Results: capped application artifacts; bounded sample enters model context.
- Persistence: process-local is acceptable for the POC.
- SQLite: local-file proof-of-concept backend.
- Snowflake: next backend priority; blueprint remains conceptual until a client
  is chosen.
- PostgreSQL: not in current scope.
- Future specialists: leave coordinator extension seams for capabilities such
  as visualization without coupling them to database clients.

## Current architecture

![Data Analytics Agent architecture](data-analyst-agent/doc/diagrams/system-architecture.svg)

The primary runtime path is:

```text
Streamlit
  -> FastAPI source-bound conversation/run
  -> Data Analytics Agent coordinator
  -> text-to-SQL specialist
  -> selected OSI model
  -> structural SQL validation
  -> human review interrupt
  -> source-bound SQLBackend
  -> normalized result artifact
  -> provenance-checked final answer
```

### Source binding

Source isolation is enforced by:

- conversation and run stores;
- source-specific backend/agent resolution;
- runtime `AgentContext`;
- `execute_sql` source check;
- source/thread-scoped model result access;
- final-answer provenance validation;
- Streamlit conversation switching.

Do not reduce source binding to a UI-only control.

### Service construction

[`Services`](data-analyst-agent/text2sql_agent/api.py) owns:

- settings and registry catalog;
- source summaries/readiness;
- backend cache per source;
- agent graph cache per source;
- process-local stores;
- shared `RunManager`.

Registry/readiness caches require an API restart after configuration, OSI, or
target changes.

## Implemented source system

[`data_sources.yaml`](data-analyst-agent/data_sources.yaml) defines:

- backend profiles;
- default source;
- source name and description;
- backend reference and trusted target;
- semantic model;
- dialect;
- starter questions;
- optional limit overrides.

[`data_sources.py`](data-analyst-agent/text2sql_agent/data_sources.py) uses
strict Pydantic models, forbids unknown keys, resolves OSI paths under
`semantic/`, and merges validated limits.

[`semantic.py`](data-analyst-agent/text2sql_agent/semantic.py) checks:

- OSI file, version, and structure;
- datasets, fields, primary keys, and relationships;
- selected dialect or `ANSI_SQL` expressions;
- live table existence;
- simple physical column existence;
- metrics warning.

One unavailable source does not disable healthy sources. Streamlit lists ready
sources and separately displays diagnostics for unavailable ones.

## Implemented semantic models

### Chinook

[`chinook.osi.yaml`](data-analyst-agent/semantic/chinook.osi.yaml) covers all 11
physical tables, relationships, physical fields, business descriptions, and
canonical revenue/count metrics.

### Financial

[`financial.osi.yaml`](data-analyst-agent/semantic/financial.osi.yaml) covers:

- account;
- card;
- client;
- disposition;
- district;
- loan;
- standing order;
- transaction.

It includes relationships, status/direction/date context, and canonical count,
volume, cash-flow, and loan metrics. It deliberately does not invent an
undocumented currency.

## Implemented backend boundary

[`SQLBackend`](data-analyst-agent/text2sql_agent/backends/base.py) requires:

- `readiness_errors`;
- `validate_sql`;
- `execute`;
- `list_tables`;
- `get_table_schema`.

Execution normalizes to columns, row dictionaries, truncation, and elapsed
time. Common decimal/date/time/bytes values are converted to stable
JSON-compatible values.

[`SQLiteBackend`](data-analyst-agent/text2sql_agent/backends/sqlite.py) owns:

- read-only URI connection;
- SQLite mutation/administrative authorizer;
- monotonic progress deadline;
- capped fetch;
- SQLite catalog and PRAGMA introspection;
- connection cleanup.

The LangChain SQL toolkit, `langchain-community`, and SQLAlchemy are no longer
dependencies.

## Agent and HITL behavior

[`agent.py`](data-analyst-agent/text2sql_agent/agent.py) builds one source-bound
coordinator graph with:

- source-specific coordinator and specialist prompts;
- explicit OSI virtual path and dialect;
- explicit query-writing/schema-exploration skills;
- filesystem deny-by-default permissions;
- structured specialist and coordinator outputs;
- source-specific in-memory checkpointer.

[`run_manager.py`](data-analyst-agent/text2sql_agent/run_manager.py) implements:

- `queued`, `running`, `approval_required`, `completed`, and `failed`;
- sanitized non-token-streaming activity;
- approval extraction;
- approve/edit/reject resume translation;
- edited-SQL validation;
- repeated rejection/reapproval cycles;
- final result/SQL provenance checks;
- conversation completion/failure ownership.

[`sql_tools.py`](data-analyst-agent/text2sql_agent/sql_tools.py):

- exposes generic list/schema/validate/execute tools;
- checks runtime source on execution;
- passes source limits to the backend;
- stores complete capped results;
- returns only the configured sample to the model;
- restricts model result paging to current source/thread.

## Streamlit behavior

[`streamlit_app.py`](data-analyst-agent/streamlit_app.py) and
[`ui/components.py`](data-analyst-agent/text2sql_agent/ui/components.py)
provide:

- ready-source selector;
- source descriptions, backend/dialect badges, warnings, and errors;
- automatic new conversation on source switch;
- selector lock during active run/review;
- new conversation with current source;
- URL rehydration;
- source-specific starter questions and chat placeholder;
- sanitized progress;
- exact editable SQL review;
- approve/edit/reject and repeated revision UI;
- result table, CSV, assumptions, interpretation, SQL, and activity.

## Running locally

From `data-analyst-agent/`:

```bash
cp .env.example .env
# Set OPENAI_API_KEY.
./scripts/start.sh
```

Endpoints:

- Streamlit: `http://127.0.0.1:8501`
- FastAPI health: `http://127.0.0.1:8000/health`
- FastAPI docs: `http://127.0.0.1:8000/docs`

The launcher uses `uv sync --locked`, validates settings and source readiness,
checks ports, starts both services, waits for health, and supervises shutdown.

## Verification status

Last verified on 2026-07-18:

```text
47 passed, 1 skipped
```

The skip is the opt-in live OpenAI smoke test.

Also verified:

- Python compilation;
- both sources ready with zero errors/warnings;
- tutorial notebook executes end to end with live calls disabled;
- Archify JSON and generated HTML validation;
- dual-theme SVG rendering;
- Streamlit source switching;
- old URL source restoration;
- new conversation retaining Financial;
- no Streamlit runtime error during that flow;
- `git diff --check`.

Re-run all verification before relying on this count:

```bash
cd data-analyst-agent
uv run pytest
```

## Prioritized next work

### 1. Snowflake adapter

This is the primary feature milestone.

Use the [conceptual blueprint](data-analyst-agent/doc/snowflake-blueprint.md).
The intended work is:

1. choose/inject the Snowflake client or connection provider;
2. implement `SQLBackend` responsibilities;
3. evolve construction into an injected backend-provider registry;
4. keep credentials outside registry/OSI;
5. bind target database/schema context per source;
6. use a read-only Snowflake role and provider-native timeout/cancellation;
7. add fake adapter contract tests;
8. add opt-in live smoke coverage;
9. prove two Snowflake semantic sources can reuse one profile safely;
10. preserve unchanged agent/API/UI contracts.

Do not implement against one globally mutable connection that changes
database/schema/role across concurrent sources.

### 2. Additional specialist agents

The coordinator may later route to specialists such as visualization.

Before implementing one:

- define a narrow task description;
- define strict input/output or artifact contracts;
- scope saved-result access by thread/source;
- keep credentials and cursors out of specialist context;
- assign skills and filesystem permissions explicitly;
- place HITL at real side effects;
- keep coordinator ownership of the final answer;
- test routing, repeated use, failure, and provenance.

A visualization specialist should consume a saved result ID and create a chart
specification/artifact rather than execute SQL directly.

### 3. Concise production hardening

Before production:

- authentication and source/result authorization;
- durable stores and LangGraph checkpoints;
- managed secrets and connection lifecycle;
- audit trail for review decisions and executed SQL;
- redacted logging/metrics/tracing;
- cancellation, retries, rate limits, and concurrency policy;
- tenant isolation and least-privilege database/network access;
- retention, deletion, backup, and recovery.

## Known limitations and cautions

- State disappears on API restart.
- Result HTTP access is unscoped for the local single-user POC.
- Registry and readiness changes require restart.
- No Snowflake dependency or adapter exists.
- No visualization specialist exists.
- OSI generation is manual.
- Readiness verifies simple identifiers, not arbitrary expression semantics.
- SQL parser/HITL do not replace database permissions.
- Live model behavior is nondeterministic; deterministic tests use fakes.
- Local `.env` and database data must never be copied into docs or logs.

## Maintenance rule

When a stable contract changes, update in the same change:

1. implementation and focused tests;
2. root project README if user-facing;
3. relevant `doc/` guide;
4. affected Archify diagram JSON, HTML, and SVG;
5. this handoff when current state or prioritized work changes.
