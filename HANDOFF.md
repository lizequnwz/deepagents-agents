# Project handoff: Data Analytics Agent

Last updated: 2026-07-19

## Executive summary

The active deliverable is [`data-analytics-agent/`](data-analytics-agent/), a local,
source-aware conversational analytics POC built with Deep Agents, FastAPI, and
Streamlit.

Each conversation is bound to one registered source and its required OSI
`0.1.1` semantic model, dialect, backend target, and limits. A coordinator
routes database work to an isolated text-to-SQL specialist. Every SQL execution
requires approve/edit/reject review.

The coordinator now also has an optional visualization specialist. It is used
only when the user explicitly requests a chart, consumes one chart-ready saved
result, validates exactly one strict `ChartSpec`, and generates it automatically
before trusted application code renders Plotly.

This remains a local, single-user, process-memory POC. It is not production
ready.

## Start here

- [Project README](data-analytics-agent/README.md)
- [Developer documentation](data-analytics-agent/doc/README.md)
- [Architecture](data-analytics-agent/doc/architecture.md)
- [Using the agent](data-analytics-agent/doc/using-the-agent.md)
- [Safety and HITL](data-analytics-agent/doc/safety-and-hitl.md)
- [Operations and testing](data-analytics-agent/doc/operations-and-testing.md)
- [Executable tutorial](data-analytics-agent/agent_internals_tutorial.ipynb)

Canonical Archify sources, interactive HTML, and dual-theme SVGs live in
[`data-analytics-agent/doc/diagrams/`](data-analytics-agent/doc/diagrams/).

## Confirmed design decisions

- Product/package: **Data Analytics Agent** / `data_analytics_agent`.
- Topology: coordinator in `coordinator.py`; specialists under `agents/`.
- Root `agent.py`: thin compatibility import only.
- Default general-purpose subagent: disabled.
- Model: existing configured model reused by both specialists.
- Source isolation: immutable per conversation and enforced below the UI.
- SQL: one reviewed read-only query; exact edited SQL executes.
- Visualization activation: explicit chart/plot/graph/visualize/map request
  only.
- Visualization removal: global `ENABLE_DATA_VISUALIZATION` flag, default
  `true`; disabling it removes the subagent without changing SQL behavior.
- Chart tool: one generic `create_chart` with a constrained declarative spec,
  never arbitrary generated Python or custom Plotly code.
- Chart execution: automatic after strict schema and result-scoped validation;
  there is no chart approval interrupt.
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
- Results: capped application artifacts; only a bounded sample enters model
  context.
- Chart persistence: generated `ChartSpec` and canonical success message are
  stored in the completed turn; Plotly is reconstructed from its saved result,
  with no separate chart store.
- Backend: SQLite is implemented behind `SQLBackend`; Snowflake remains the
  next backend candidate.

## Current architecture

```text
Streamlit
  -> FastAPI source-bound conversation/run
  -> data-analytics coordinator
     -> text-to-SQL specialist
        -> OSI + SQL validation
        -> execute_sql HITL
        -> source-bound SQLBackend
        -> scoped SavedResult
     -> visualization specialist (explicit request + feature enabled)
        -> inspect scoped SavedResult
        -> validate strict ChartSpec
        -> automatic create_chart
        -> success result returned to coordinator
  -> provenance-checked FinalAnswer
  -> deterministic Plotly + underlying table/CSV
```

The feature folders are:

- [`agents/text_to_sql/`](data-analytics-agent/data_analytics_agent/agents/text_to_sql/)
- [`agents/visualization/`](data-analytics-agent/data_analytics_agent/agents/visualization/)

The visualization folder owns:

- strict schemas and chart-type rules;
- saved-result-scoped inspect/validate/create tools;
- presentation-only row shaping and readability limits;
- deterministic Plotly rendering;
- lazy `pgeocode` US ZIP/city-state centroid resolution.

## Safety and provenance

Do not weaken these invariants:

1. One conversation has one immutable `source_id`.
2. Every SQL execution pauses before the database is touched.
3. Every chart is explicitly requested and validated before rendering.
4. Edited SQL is validated again.
5. A chart remains tied to its source/thread-scoped `result_id`.
6. Specialist result access requires current source and thread.
7. Final SQL is replaced with the exact SQL saved with the result.
8. Final charts are validated against that same saved result.
9. LangGraph checkpoints are isolated per run; conversation history, including
   chart success results, is explicitly reconstructed for the next turn.
10. Full result rows remain outside model messages except for a configured
   sample.

The chart renderer is trusted deterministic code. The model supplies only a
constrained, validated specification—not executable Python. Incompatible chart
points are not coerced from strings: line/area preserve null gaps; other chart
types exclude invalid points with visible warnings and fail when none remain.

Readability limits are enforced: pie/donut 12 slices, bar/box 30 categories,
heatmap 500 cells, and other charts use the existing 500-row result cap. There
is no silent truncation.

## Running locally

From `data-analytics-agent/`:

```bash
cp .env.example .env
# Set OPENAI_API_KEY.
./scripts/start.sh
```

Endpoints:

- Streamlit: `http://127.0.0.1:8501`
- FastAPI health: `http://127.0.0.1:8000/health`
- FastAPI docs: `http://127.0.0.1:8000/docs`

`pgeocode` caches its generic US postal dataset on first map use.
`PGEOCODE_DATA_DIR` can override the cache location.

## Verification status

Last verified on 2026-07-19:

```text
72 passed, 1 skipped
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

## Prioritized next work

### 1. Live visualization flow

Use a real model to exercise:

1. a non-chart question (visualization must not route);
2. an explicit chart request with chart-ready SQL;
3. automatic chart generation with visible type/mapping progress;
4. a chart request requiring a second reviewed SQL result;
5. rehydration of a generated chart and its success message;
6. a partially resolved ZIP/city-state map.

### 2. Snowflake adapter

Use the [conceptual blueprint](data-analytics-agent/doc/snowflake-blueprint.md).
Keep credentials outside registry/OSI, inject connection ownership, bind
database/schema/role per source, use a read-only role and provider-native
timeout/cancellation, and preserve unchanged agent/API/UI contracts.

### 3. Production hardening

- authentication and source/result authorization;
- durable stores and LangGraph checkpoints;
- managed secrets and connection lifecycle;
- approval/audit records for exact SQL and chart specs;
- redacted observability;
- cancellation, retries, rate limits, and concurrency policy;
- retention, deletion, backup, tenant isolation, and least privilege.

## Known limitations

- API restart clears conversations, runs, checkpoints, and results.
- The local result HTTP endpoint is not a production authorization boundary.
- Registry/readiness changes require restart.
- No Snowflake adapter exists.
- Chart generation is deliberately one-chart, declarative, and non-extensible
  at runtime.
- ZIP/city maps depend on generic centroid lookup, not boundary geometry.
- OSI generation remains manual.
