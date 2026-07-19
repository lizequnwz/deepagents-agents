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
| Streamlit | Source selection, conversation URL, polling, SQL editor, result presentation | Agent graph, credentials, SQL execution |
| FastAPI | Source catalog, conversations, runs, decisions, result endpoint, service construction | Business interpretation |
| Coordinator | Conversational context, delegation, final structured answer | Direct SQL execution |
| Text-to-SQL specialist | OSI reading, query design, structural validation, execution request, interpretation | Source switching |
| HITL middleware | Pause and approve/edit/reject resume shape | Database authorization |
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

[`data_sources.py`](../text2sql_agent/data_sources.py) strictly validates the
registry with Pydantic, resolves semantic paths under `semantic/`, merges global
and source-specific limits, and produces immutable runtime `DataSource`
objects.

[`api.py`](../text2sql_agent/api.py) builds and caches one backend and agent
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

[`agent.py`](../text2sql_agent/agent.py) builds:

- `data-analytics-agent` coordinator;
- one custom `text-to-sql` specialist;
- no default general-purpose subagent;
- source-specific prompts and tools;
- explicit query-writing and schema-exploration skills;
- filesystem read access only to `AGENTS.md`, `semantic/**`, and `skills/**`;
- provider/tool structured-output contracts;
- a source-specific in-memory LangGraph checkpointer.

The coordinator delegates database work through the built-in `task` tool. It
can read saved results but cannot execute SQL. The specialist must read the
selected OSI model before query generation.

## Request and result flow

1. Streamlit creates or rehydrates a source-bound conversation.
2. FastAPI creates a run and rejects concurrent runs for the same thread.
3. `RunManager` invokes the source-specific coordinator with `AgentContext`.
4. The coordinator delegates database work.
5. The specialist reads OSI context, validates SQL, and calls `execute_sql`.
6. HITL pauses before the tool runs.
7. Approve/edit resumes execution; reject returns feedback to the specialist.
8. The backend returns normalized capped rows.
9. `ResultStore` saves the artifact with thread and source provenance.
10. The model sees a small sample and result ID.
11. `RunManager` verifies final-answer provenance and records the turn.
12. Streamlit retrieves and displays the full capped artifact.

See [Safety and HITL](safety-and-hitl.md) for the detailed sequence.

## Backend boundary

[`backends/base.py`](../text2sql_agent/backends/base.py) defines five required
operations:

- readiness diagnostics;
- read-only SQL validation;
- capped execution;
- table listing;
- normalized table-schema inspection.

The current [`SQLiteBackend`](../text2sql_agent/backends/sqlite.py) owns
SQLite-specific read-only URI handling, authorizer rules, timeout progress
handler, cursors, and PRAGMA metadata. Those details do not leak into the
agent, API schemas, or Streamlit.

## Adding specialist capabilities

Future specialists, such as visualization, should be added through an explicit
coordinator capability rather than by expanding the text-to-SQL prompt
indefinitely.

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

A visualization specialist should initially consume a saved result and return
a chart specification or application artifact. It should not receive database
credentials or bypass reviewed SQL execution.

## Invariants

- Registry entries are trusted configuration, not user input.
- One conversation cannot span or join sources.
- Semantic context is selected before agent construction.
- Backend-native safety remains inside the backend.
- Application results remain outside model context except for a bounded sample.
- Structured output is validated at specialist and coordinator boundaries.
- A future backend or specialist must not require Streamlit-specific logic.

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
- New specialist designs define inputs, outputs, provenance, and side effects
  before implementation.
