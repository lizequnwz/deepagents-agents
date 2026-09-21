# Architecture

```mermaid
flowchart TD
    UI[Streamlit chat and saved conversations] --> API[FastAPI lifecycle and artifact API]
    API --> C[Deep Agents coordinator]
    API --> Edit[Validated presentation edits over saved evidence]
    C --> S[Text-to-SQL specialist]
    C --> P[Data-analysis specialist]
    S --> OSI[Curated semantic catalog]
    S --> Source[Configured SQL source]
    S --> Duck[DuckDB saved-data queries]
    P --> Py[Fresh Python subprocess per execution]
    Source --> D[Typed Parquet datasets]
    Duck --> D
    D --> Duck
    D --> Py
    Py --> D
    C --> Chart[Shared immutable Plotly charts]
    D --> Chart
    C --> Findings[Published findings]
    Findings --> Report[Required evidence-backed HTML report]
    Chart --> Report
    Edit --> Chart
    Edit --> Report
    API --> Metadata[SQLite conversations / runs / artifacts / events]
    C --> Checkpoints[AsyncSqliteSaver / run-scoped checkpoints]
```

## Responsibilities and persistence

The coordinator routes by required work, not surface keywords. It handles
metadata-only discussion directly. SQL owns warehouse access and descriptive
transformations; Python owns analysis over explicit saved artifacts. Python can
request more data through the coordinator, which makes a sequential SQL
assignment and resumes the analysis. There are no fixed one-delegation rules.

`datasets.py` handles bounded extraction, typed Parquet and full-artifact
summaries. `stores.py` handles conversation/run/analysis/report state using
`persistence.py`. Durable metadata uses typed JSON, with large content in files.
`execution.py` and the Python runner manage local cancellation. `run_manager.py`
owns execution/resume/stop/report retry; `approvals.py` translates exact edits;
`diagnostics.py` aggregates provider usage and bounded tool events.

The graph is constructed per configured source and uses one run ID as its
checkpoint identity. FastAPI opens/closes the maintained SQLite checkpoint saver.
On startup, unfinished computations become paused and pending reviews remain
reviewable. Each tool registers artifacts directly and journals its committed
output under run/assignment/tool-call identity for specialist work. Final assembly resolves explicit references;
it does not scan backward through messages or guess embedded JSON schemas.

## Findings, reports, and recovery

`evidence.py` provides the shared scoped resolver for publication and reports,
including transitive dataset lineage.
Chart versions are immutable. Chat and report consume the same chart spec and
presentation dataset. Report metric values reference exact stored rows/columns.
A published answer remains visible if rendering fails; successful completion
requires its report. The coordinator selects and publishes findings once.
`ReportCompletionMiddleware` ends the graph after successful report attachment;
the run manager finishes from stored findings without requesting a duplicate
model-authored final answer. Metadata-only responses still use ToolStrategy.
Report blocks may arrange only published evidence, and omitted published charts
and analyses are attached automatically. Retry report reuses a valid
attached artifact, renders the saved specification, or requests presentation-only
repair using published findings. Computation tools reject execution after publication.
Resume selects this same recovery path after publication; active workers prevent
overlapping attempts.

## Direct presentation edits

`presentation_edits.py` handles `POST /api/runs/{run_id}/presentation` without
constructing agents or opening sources. Its typed allowlist admits title, labels,
palette, and compatible chart-type edits; scope and dataset bindings cannot be
edited. The caller supplies the displayed report/chart IDs. Stale IDs and active
conversations are rejected. Shape/data validation precedes candidate creation.
Sampled display datasets cannot change chart type.

The existing renderer renders a revision of the agent-authored report specification.
Original analytical turns, charts and reports remain immutable. Candidate records
in `presentation_edits` retain preparing/failed/ready status. A single atomic
`presentation_views` metadata write commits the new chart/report pair only after
both artifacts exist. Conversation and run reads resolve that view, including
history supplied to later analytical turns. Rendering failure leaves the previous
view intact; resubmitting the explicit edit retries it. History deletion includes
these records and their report files. No new graph run or provider call is needed.

## Chart intervals

Chart bounds require `interval` metadata: kind, method, optional label, and
optional nominal coverage. Scenario/sensitivity ranges cannot declare coverage.
The shared renderer displays the same label/method in chat and HTML; declaring
nominal coverage does not certify empirical calibration. This strict contract
does not migrate old bound specifications that omitted interval meaning.

## UI lifecycle and deployment constraints

Streamlit refreshes active content using a timed fragment, preserving stable
widget keys. Immutable previews/reports are cached by ID with bounded caches.
Full downloads stream separately from preview pages. Conversation changes cause
an app rerun; ordinary active-run refresh does not rebuild the conversation.

Constraints: one process, one local user, one source per conversation, sequential
source queries. No persistent arbitrary Python object state, cross-conversation
learning, or obsolete in-memory-state migration.


## Semantic context

`semantic_context.py` builds one coherent metadata package for prompts and the
context tool. SQL owns physical definitions; the coordinator sees the business
projection. Whole oversized packages request refinement. Caches contain metadata,
never source observations. SQL/chart operational guidance lives in owner prompts;
analysis and report methodology remain on-demand skills.

## Corrections and clarification

`steering.py` uses supported before-model and after-model middleware plus tool
wrappers. Agent-private checkpoint state tracks correction IDs independently in
each assignment. Ordered HumanMessages have stable IDs, making checkpoint replay
idempotent. Later specialists receive the same durable corrections in their own
context. Tool wrappers reject stale proposed steps; running steps may finish.
Publication and completion share the run-store lock with acceptance and refuse
pending coordinator corrections. No concurrent invoke or graph-internal mutation
is used. Clarifications use interrupt/resume and remain distinct from code review.

The UI has one Activity disclosure per run, retained across publication and
completion. Incremental event cursors avoid retransmitting history each second;
hidden activity/diagnostics are rendered lazily. Findings remain visible while
reporting runs, fails or is retried. The composer remains outside the polling
fragment so typing and focus persist.


## Isolated uploaded files

`uploads.py` stages one bounded CSV/Parquet file in its own conversation and
requires explicit schema confirmation before any run. CSV first enters Arrow as
text; Parquet retains supported scalar types. Type suggestions and review checks
use the full bounded population. Confirmation creates an immutable reviewed
Parquet child, retains original bytes and snapshot, and saves SHA-256, selected
types, declared grain and verified row keys. Unsupported nested types, invalid
casts, duplicate declared keys and oversized files fail without truncation.

Uploads are source-scoped evidence, not entries in the shared warehouse registry
or generated OSI catalogs. Coordinator and SQL specialist use the same harness
with reviewed file context, omitting warehouse/semantic tools. SQL binds saved
artifacts into the existing external-access-disabled DuckDB query path; Python
uses the same saved-input execution tools. Charts and reports retain the existing
parent lineage. Reports include upload provenance. Warehouse agents keep their
curated semantic catalog requirements.

`POST /api/uploads?filename=...` accepts raw file bytes and creates the staged
conversation. `GET /api/conversations/{id}/upload` returns at most ten preview rows
and review metadata; `POST /api/conversations/{id}/upload/confirm` commits explicit
types/grain/keys. `GET /api/conversations/{id}/source` resolves that isolated
source. Upload sources never appear in the reusable source listing. Imports and
confirmation run off the event loop; history deletion refuses active imports or
reviews. Restart reopens staged or confirmed files. Source-configuration errors
are separate from model readiness so files work without a warehouse registry.


## Plans and concurrent analysis assignments

The coordinator explicitly installs LangChain's `TodoListMiddleware`; the current
Deep Agents base harness does not automatically expose `write_todos`. Complex
requests record public work steps before delegation. Parallel task batches without
a plan receive a tool correction. The UI renders the latest successful coordinator
plan and meaningful work events above the collapsed diagnostic Activity panel.
Plans are public task lists, not private model reasoning. Callback invocation IDs
separate concurrent operations even when model-supplied tool-call IDs repeat.
Human-review interrupts and cancellation have waiting/stopped activity states.

`DelegationMiddleware` wraps native task calls with bounded analysis slots and one
source slot. It preserves native checkpoint and interrupt handling. Async slot
acquisition is cancellation-safe; queued work checks Stop before starting. The
coordinator owns its context fields, so subagents cannot write conflicting copies
back when they finish together. `AssignmentMiddleware` creates a private,
checkpointed assignment ID in each SQL or Python branch. Tool commit keys include
it. Each branch persists its own application-owned receipt in the existing run
record. SQL's structured response contains interpretation only; code attaches the
saved datasets, including inspected/reused snapshots and multiple query results.
Python's finish tool automatically attaches its own executions and inputs, saves
a compact receipt, and returns that receipt through graph state without a final
model-written copy. A validation failure stays in the specialist repair loop.
Separate branches cannot consume each other's unfinished executions or collide on
replay. New corrections invalidate a completed assignment receipt until reconciled.
Pending approval interrupts remain separate.

Investigation notes contain analytical context, not repeated artifact inventories.
A new turn includes unfinished prior-run objectives and committed receipts, chart
references, and execution summaries even if publication never happened. Exact
code and logs remain in stored evidence/inspection panels. Dataset, analysis and
chart discovery tools recover valid scoped references; invalid model selections
produce correction feedback rather than aborting the run. Scope validation remains
mandatory. Available artifacts are not automatically selected for publication.

The composer uses native `st.chat_input` attachments. An attachment creates a new
isolated file conversation; an optional question waits in UI session state until
schema confirmation, then is consumed once. Reloading the confirmed conversation
does not replay the question. The sidebar upload entry was removed.
