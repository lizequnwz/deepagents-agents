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
| Streamlit | Source selection, conversation URL, polling, conditional SQL/Python review, progress, multi-result/statistical/Plotly presentation | Agent graph, credentials, SQL or Python execution |
| FastAPI | Source catalog, conversations, runs, SQL decisions, result endpoint, service construction | Open-ended business interpretation |
| Coordinator | Conversational context, semantic research, direct-versus-investigation planning, sequential delegation, evidence selection, structured answers | Direct SQL execution |
| Text-to-SQL specialist | Targeted semantic discovery, query design, structural validation, execution request, interpretation | Source switching |
| Visualization specialist | One constrained chart spec over one scoped saved result | SQL, arbitrary Python, source switching |
| Statistical specialist | General validated Python over one scoped saved SQL result | SQL, source switching |
| HITL middleware | Deployment-configurable pause and approve/edit/reject resume shape for SQL and Python | Database authorization or a production code sandbox |
| `SQLBackend` | Provider dialect, validation, execution, metadata, native safety controls | Business semantics |
| Semantic catalog | Immutable parsed OSI entities, physical expressions, relationships, metrics, indexes, and AI context | Credentials or connection lifecycle |
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

[`api.py`](../data_analytics_agent/api.py) builds and caches one semantic
catalog, backend, and agent graph per source. A future backend-provider layer may share connection
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
- an optional `statistical-analysis` specialist when
  `ENABLE_STATISTICAL_ANALYSIS=true`;
- no default general-purpose subagent;
- source-specific prompts and tools;
- agent-scoped `skills/text-to-sql/` and `skills/data-visualization/`
  and `skills/statistics/` namespaces, each exposed only to its matching
  specialist;
- filesystem read access only to `AGENTS.md` and `skills/**`;
- provider/tool structured-output contracts;
- a source-specific in-memory LangGraph checkpointer.

The coordinator delegates through the built-in `task` tool. Direct questions
use one SQL assignment; investigations use `write_todos` and sequential atomic
assignments whose later steps can depend on earlier evidence. It can inspect
saved results but cannot execute SQL. Result IDs are opaque application evidence
handles, not relations in the configured source. Every later SQL assignment is
therefore restated as a complete source query. `agents/text_to_sql/` owns
database analysis; `agents/visualization/` owns the chart schema, result-scoped
tools, validation, geocoding, and deterministic renderer. The root `agent.py`
remains a thin compatibility import for Deep Agents tooling.

The coordinator and text-to-SQL specialist share three source-bound read-only
semantic tools. `search_semantic_model` returns compact lexical candidates,
`get_semantic_entities` returns exact selected definitions, and
`get_relationships` returns declared adjacency or a deterministic shortest
path. The coordinator receives business semantics; text-to-SQL additionally
receives physical sources and selected-dialect expressions. Agents never read
raw OSI YAML.

`agents/statistical_analysis/` owns result inspection, the Python HITL tool,
bounded subprocess execution, typed statistical outputs, and the terminal
statistical outcome contract. It receives a result ID, not row data in the task
message.

## Request and result flow

1. Streamlit creates or rehydrates a source-bound conversation.
2. FastAPI creates a run and rejects concurrent runs for the same thread.
3. `RunManager` invokes the source-specific coordinator with typed run-scope
   state containing the conversation, run, and source IDs.
4. The coordinator answers metadata-only research with its business-facing
   semantic tools, or delegates when observed values are requested.
5. The specialist uses the compact overview and targeted semantic tools, then
   calls `execute_sql`. The backend
   validates once immediately before execution. Expected validation or provider
   query errors return as tool observations so the specialist can revise within
   the existing execution budget.
6. When `REQUIRE_SQL_APPROVAL=true`, HITL pauses before the tool runs;
   otherwise the same tool executes immediately.
7. In review mode, approve/edit resumes execution and reject returns feedback.
8. The backend fetches `cap + 1`, returns at most the configured cap, and uses
   the extra row only to detect truncation.
9. `ResultStore` saves the rows and an eager immutable full-artifact profile
   with thread/source provenance.
10. The SQL specialist and coordinator see the profile plus at most the first
    10 rows and the result ID. Investigations may repeat steps 4–10 sequentially.
11. The coordinator returns a primary result ID and every material supporting
    result ID. `RunManager` resolves exact primary-first `ResultReference`
    objects from current-thread/current-source storage.
12. Streamlit retrieves and displays every final evidence artifact.
13. For an ordinary data answer, the visualization specialist inspects the
    selected final chart-ready result and proposes one `ChartSpec`; report turns
    keep chart composition inside `ReportSpec`.
14. `create_chart` validates the constrained spec and completes the
    visualization subagent directly, without a second model packaging step.
15. Progress shows the chart type and a bounded subset of safe mappings.
16. A terminal `chart_created`, `needs_sql_reshape`, or `cannot_create` result
    returns to the coordinator. A reshape outcome permits one validated SQL
    recovery cycle.
17. `RunManager` preserves the business answer, attaches the exact generated
    spec, and verifies that its result belongs to final evidence.
18. Streamlit reconstructs Plotly and exposes every evidence table/CSV and SQL.
19. When inference materially improves an answer, the coordinator conservatively
    reuses an untruncated suitable result or obtains a new validated SQL result.
20. The statistical specialist inspects bounded provenance/profile/sample data,
    writes Python, and calls `execute_statistical_python` with the result ID.
21. With `REQUIRE_PYTHON_APPROVAL=true`, HITL exposes complete code and immutable
    dataset provenance; otherwise execution proceeds immediately. The exact
    submitted or edited code runs in a secret-stripped subprocess where `df`,
    `pd`, and `np` are preloaded.
22. The runner returns bounded text, scalars, compact tables, and PNG figures;
    `RunManager` attaches the authoritative code and outputs while the
    coordinator retains final-answer wording.
23. For each successful data-bearing turn, the coordinator loads the report
    skill after final analysis and creates one `ReportSpec` over the same
    material evidence. Ordinary turns may reuse the exact automatic
    `ChartSpec`; explicit report turns keep chart composition in the report.
24. Trusted code resolves the scoped artifacts, renders and stores one
    self-contained HTML file, and returns immutable report metadata.
25. `RunManager` attaches the report without discarding an ordinary top-level
    chart. Streamlit verifies the content hash before isolated preview and
    byte-identical download.

LangGraph checkpoints are isolated by `run_id`. Typed graph state retains the
conversation `thread_id`, `run_id`, `source_id`, and current question for
artifact scoping and is inherited by inline subagents. `RunManager.start`
reconstructs completed
human/assistant turns for each new run, including all evidence references and
the exact chart spec.

See [Safety and HITL](safety-and-hitl.md) for the detailed sequence.

## Backend boundary

[`backends/base.py`](../data_analytics_agent/backends/base.py) defines two
required operations:

- validated capped execution;
- targeted table-schema inspection for OSI readiness.

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

## Statistical-analysis capability

`ENABLE_STATISTICAL_ANALYSIS` defaults to `true`. Disabling it removes the
specialist and makes the coordinator report statistical execution as
unavailable. The specialist is not limited to a catalog of tests: validated code
may use pandas, NumPy, SciPy, statsmodels, scikit-learn, matplotlib, and seaborn.
The coordinator leaves ordinary descriptive trends and comparisons to SQL and
visualization, and invokes Python only when uncertainty or modeling matters.
The skill progressively loads regression or time-series guidance for predictive
models, trend inference, seasonality, anomaly detection, and forecasting.

The input contract is one source/thread-scoped saved result ID. The execution
tool loads its rows as pandas `df` after optional approval. `pd` and `np` are
preloaded. Executed code must assign a named `analysis_outputs` dictionary;
supported values normalize to bounded text, scalar, table, or figure outputs.
Truncated inputs cannot execute. `needs_sql_reshape` permits one validated SQL
recovery cycle; an execution failure permits one targeted repair after the
first attempt. Dataset inspection exposes attempts already used by the run, so
a fresh recovery specialist cannot propose code after the budget is exhausted.

## Adding specialist capabilities

Additional specialists should follow the same explicit coordinator capability
pattern rather than expanding the text-to-SQL prompt indefinitely.

Recommended rules:

1. Give each specialist a narrow description and explicit input/output schema.
2. Reuse saved result IDs as artifact references instead of copying full row
   sets into prompts; never reinterpret them as source relations.
3. Require thread and source provenance when reading an artifact.
4. Assign skills and filesystem permissions explicitly; custom subagents do
   not inherit all coordinator capabilities automatically.
5. Decide whether the capability is read-only or mutating and place HITL at
   the actual side-effect boundary.
6. Keep final answer ownership with the coordinator.
7. Test routing, artifact scope, failure behavior, and repeated calls.

## Reporting capability

Reporting is implemented without adding another specialist. The coordinator
already owns the conversation and receives evidence from all three specialists,
so every successful data-bearing turn ends by lazy-loading the `report-design`
skill and calling a trusted deterministic HTML renderer. Conversational or
failed turns with no final evidence do not create empty reports.

The coordinator uses the same material same-thread, same-source evidence as the
final answer. Ordinary turns get a compact default report after analysis is
already sufficient; explicit report requests may invoke additional SQL,
visualization, or statistics when evidence is missing. It produces a structured
`ReportSpec`; application code resolves full required data outside model context
and renders canonical, self-contained HTML. Every safe preview is downloadable
in Streamlit and can be revised conversationally, without an approval or
finalization ceremony.

This capability introduces an artifact-composition seam rather than an execution
seam. A future reporting subagent is justified only if report context pressure,
independent lifecycle needs, or specialist tooling outweigh the added handoff
and model-call complexity.

`StatisticalAnalysisStore` gives completed analyses reusable IDs, while
`ReportStore` retains exact HTML bytes, the validated specification, input
references, version lineage, renderer version, and content hash. FastAPI serves
the stored artifact, and Streamlit verifies the hash before isolated preview and
download.

See [Reporting capability](reporting-capability.md) for the contracts, design
rules, implementation map, limitations, and graduation criteria.

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
