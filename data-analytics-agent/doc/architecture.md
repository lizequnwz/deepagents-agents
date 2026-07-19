# Architecture

## Purpose and mental model

The system separates semantic meaning, agent behavior, application lifecycle,
and database execution. The most important boundary is `SQLBackend`: the agent
and UI work with one stable contract while provider-specific execution remains
inside an adapter.

![Data Analytics Agent architecture](diagrams/system-architecture.svg)

[Open the interactive diagram](diagrams/system-architecture.html) ·
[Edit the Archify source](diagrams/system-architecture.architecture.json)

## Component ownership

| Component | Owns | Does not own |
| --- | --- | --- |
| Streamlit | Source selection, conversation URL, polling, SQL review, progress, result and Plotly presentation | Agent graph, credentials, SQL execution |
| FastAPI | Source catalog, conversations, runs, SQL decisions, result endpoint, service construction | Open-ended business interpretation |
| Coordinator | Conversational context, delegation, model-generated structured answers | Direct SQL execution |
| Text-to-SQL specialist | OSI reading, query design, structural validation, execution request, interpretation | Source switching |
| Visualization specialist | One constrained chart spec over one scoped saved result | SQL, arbitrary Python, source switching |
| HITL middleware | Pause and approve/edit/reject resume shape for SQL | Database authorization |
| `SQLBackend` | Provider dialect, validation, execution, metadata, native safety controls | Business semantics |
| OSI model | Curated entities, physical expressions, relationships, metrics, AI context | Credentials or connection lifecycle |
| Process-local stores | Conversation, run, event, and result artifacts | Durable or multi-user persistence |

## Source resolution

[`data_sources.yaml`](../data_sources.yaml) is the trusted catalog. It separates:

- backend profile (`backends`);
- user-facing semantic source (`sources`);
- source-specific execution target;
- semantic model path;
- dialect, examples, and limits.

[`data_sources.py`](../data_analytics_agent/data_sources.py) strictly validates the
registry with Pydantic, resolves semantic paths under `semantic/`, merges global
and source-specific limits, and produces immutable runtime `DataSource`
objects.

[`api.py`](../data_analytics_agent/api.py) builds and caches one backend and agent
graph per source. A future backend-provider layer may share connection
configuration or pools, but a source-specific execution context must remain
explicit.

## Source binding is defense in depth

Source selection is not merely a Streamlit convention.

| Layer | Enforcement |
| --- | --- |
| Conversation store | Persists immutable `source_id` with the thread |
| Run store | Copies `source_id` into every run |
| Agent resolver | Chooses a graph built for that source |
| Runtime context | Carries thread, run, and source IDs into tools |
| `execute_sql` | Rejects a runtime source that does not match its bound source |
| Result store | Saves thread ID and source ID with each artifact |
| Saved-result tool | Requires current thread and source |
| Run manager | Rejects final answers with unknown or out-of-conversation results |
| Streamlit | Starts a new conversation when source changes |

Any future specialist that consumes data artifacts must preserve the same
thread/source provenance.

## Agent topology

[`coordinator.py`](../data_analytics_agent/coordinator.py) builds:

- `data-analytics-agent` coordinator;
- one custom `text-to-sql` specialist;
- an optional `data-visualization` specialist when
  `ENABLE_DATA_VISUALIZATION=true`;
- no default general-purpose subagent;
- source-specific prompts and tools;
- explicit query-writing and schema-exploration skills;
- filesystem read access only to `AGENTS.md`, `semantic/**`, and `skills/**`;
- provider/tool structured-output contracts;
- a source-specific in-memory LangGraph checkpointer.

The coordinator delegates through the built-in `task` tool. It can read saved
results but cannot execute SQL. `agents/text_to_sql/` owns database analysis;
`agents/visualization/` owns the chart schema, result-scoped tools, validation,
geocoding, and deterministic renderer. The root `agent.py` remains a thin
compatibility import for Deep Agents tooling.

## Request and result flow

1. Streamlit creates or rehydrates a source-bound conversation.
2. FastAPI creates a run and rejects concurrent runs for the same thread.
3. `RunManager` invokes the source-specific coordinator with typed run-scope
   state containing the conversation, run, and source IDs.
4. The coordinator delegates database work.
5. The specialist reads OSI context, validates SQL, and calls `execute_sql`.
6. HITL pauses before the tool runs.
7. Approve/edit resumes execution; reject returns feedback to the specialist.
8. The backend fetches `cap + 1`, returns at most the configured cap, and uses
   the extra row only to detect truncation.
9. `ResultStore` saves the rows and an eager immutable full-artifact profile
   with thread/source provenance.
10. The SQL specialist and coordinator see the profile plus at most the first
    10 rows and the result ID.
11. `RunManager` verifies final-answer provenance and records the turn.
12. Streamlit retrieves and displays the full capped artifact.
13. On an explicit chart request, the visualization specialist inspects the
    same profile plus at most 10 rows and proposes one `ChartSpec`.
14. `create_chart` validates the constrained spec and completes the
    visualization subagent directly, without a second model packaging step.
15. Progress shows the chart type and a bounded subset of safe mappings.
16. A terminal `chart_created`, `needs_sql_reshape`, or `cannot_create` result
    returns to the coordinator. A reshape outcome permits one reviewed SQL
    recovery cycle.
17. `RunManager` preserves the exact generated spec and canonical success
    message with result provenance.
18. Streamlit reconstructs Plotly and exposes the underlying table/CSV.

LangGraph checkpoints are isolated by `run_id`. Typed graph state retains the
conversation `thread_id`, `run_id`, `source_id`, and current question for
artifact scoping and is inherited by inline subagents. `RunManager.start`
reconstructs completed
human/assistant turns for each new run, including the chart success message and
exact spec.

See [Safety and HITL](safety-and-hitl.md) for the detailed sequence.

## Backend boundary

[`backends/base.py`](../data_analytics_agent/backends/base.py) defines five required
operations:

- readiness diagnostics;
- read-only SQL validation;
- capped execution;
- table listing;
- normalized table-schema inspection.

The current [`SQLiteBackend`](../data_analytics_agent/backends/sqlite.py) owns
SQLite-specific read-only URI handling, authorizer rules, timeout progress
handler, cursors, and PRAGMA metadata. Those details do not leak into the
agent, API schemas, or Streamlit.

## Visualization capability

The implemented visualization specialist is deliberately declarative. Its
single generic `create_chart` tool accepts a strict `ChartSpec`, not Python or a
tool per chart type. That gives useful breadth while keeping validation,
provenance, and removal simple.

The feature is globally plug-and-play through
`ENABLE_DATA_VISUALIZATION` (default `true`). Disabling it removes the
subagent from graph construction and makes the coordinator report that charts
are unavailable. Existing SQL behavior and backend contracts are unchanged.

Supported chart types are bar, line, area, scatter, pie/donut, histogram, box,
heatmap, and map. Renderer-owned palettes/layout prevent arbitrary Plotly
configuration. Maps support coordinates, US ZIP/city-state centroid markers,
US state choropleths, and ISO-country choropleths.

## Adding specialist capabilities

Additional specialists should follow the same explicit coordinator capability
pattern rather than expanding the text-to-SQL prompt indefinitely.

Recommended rules:

1. Give each specialist a narrow description and explicit input/output schema.
2. Reuse saved result IDs instead of copying full row sets into prompts.
3. Require thread and source provenance when reading an artifact.
4. Assign skills and filesystem permissions explicitly; custom subagents do
   not inherit all coordinator capabilities automatically.
5. Decide whether the capability is read-only or mutating and place HITL at
   the actual side-effect boundary.
6. Keep final answer ownership with the coordinator.
7. Test routing, artifact scope, failure behavior, and repeated calls.

## Invariants

- Registry entries are trusted configuration, not user input.
- One conversation cannot span or join sources.
- Semantic context is selected before agent construction.
- Backend-native safety remains inside the backend.
- Application rows remain outside model context except for at most `head(10)`;
  immutable full-result profiles are safe bounded metadata.
- Structured output is validated at specialist and coordinator boundaries.
- A backend or specialist must not require Streamlit-specific logic.

## Common architectural mistakes

- Treating the selector as the only source-isolation control.
- Creating one global mutable cloud connection and changing schema/role with
  session commands across concurrent sources.
- Putting credentials or client objects in `data_sources.yaml`.
- Letting the coordinator execute SQL directly.
- Returning whole DataFrames through model tool messages.
- Adding a specialist without an artifact/provenance contract.
- Confusing SQL parsing with database authorization.
- Describing process-local storage as durable persistence.

## Verification checklist

- Unit tests can inject a fake `SQLBackend` without importing SQLite.
- Creating two conversations with different sources produces independent IDs.
- Cross-source result access fails.
- Agent construction uses the selected OSI path and dialect.
- Source switching creates a new conversation.
- Visualization-disabled construction leaves SQL analysis intact.
- Approved chart specs remain tied to the saved result and reconstruct after
  conversation rehydration.
