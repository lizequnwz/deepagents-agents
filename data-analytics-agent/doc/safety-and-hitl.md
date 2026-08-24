# SQL safety and human review

## Purpose and mental model

Safety is layered. No prompt, parser, human decision, or database permission is
sufficient by itself.

![SQL and statistical Python review sequence](diagrams/query-approval.svg)

[Open the interactive diagram](diagrams/query-approval.html) ·
[Edit the Archify source](diagrams/query-approval.sequence.json)

## Safety layers

| Layer | Current control |
| --- | --- |
| Trusted source catalog | Users cannot submit arbitrary targets or semantic files |
| Semantic model | Curated tables, fields, joins, metrics, and caveats |
| Agent permissions | Read access limited to required project context |
| Prompt contract | One read-only query; OSI first; fallback metadata only when needed |
| Structural parser | SQLGlot parses one dialect-specific statement |
| Allowed query class | One `SELECT`, CTE, or set operation |
| Forbidden operations | DDL, DML, transactions, commands, procedures, administrative/session and metadata operations |
| SQL approval | `REQUIRE_SQL_APPROVAL` optionally pauses `execute_sql` for approve/edit/reject |
| Python approval | `REQUIRE_PYTHON_APPROVAL` optionally pauses with complete code and immutable input provenance |
| Chart execution | `create_chart` auto-runs a constrained, result-scoped spec |
| Edit validation | Edited text is parsed again before resume |
| Chart validation | Strict schema, known columns/types, readability limits, immutable result ID |
| Backend validation | Adapter validates again immediately before execution |
| Native database control | Adapter-enforced read-only access, provider timeout/cancellation, and capped retrieval |
| Limits | Per-run agent execution budgets, timeout, capped fetch, bounded model sample |
| Python limits | Secret-stripped subprocess, hard timeout, initial attempt plus one repair, bounded stdout/tables/figures |
| Provenance | Every final result reference is resolved from source/conversation-scoped storage |

## Statistical Python lifecycle

The coordinator first selects one
untruncated source/thread-scoped saved SQL result by ID. If no clearly suitable
result exists, text-to-SQL produces an analysis-ready dataset through the
configured SQL execution flow.

The statistical specialist sees only result provenance, the full-result column
profile, and at most 10 sample rows. It submits `result_id` plus complete Python
to `execute_statistical_python`. Streamlit shows that code, the parent SQL,
originating question, row count, columns/profile, and at most 10 preview rows.
The parent result ID is immutable. When Python approval is enabled, the reviewer
may approve, edit the code, or reject with feedback; otherwise the same bounded
tool executes immediately.

Before execution, the server revalidates result thread/source scope and refuses a
result marked `truncated`. It loads the stored rows into pandas `df`; `pd` and
`np` are also preloaded. The exact submitted or human-edited text executes in a child process
with service secrets removed from its environment. This POC does not isolate
the network, filesystem, imports, or child processes and must be treated as a
trusted-local feature.

Execution has a configurable hard timeout and bounded stdout, stderr, compact
tables, textual values, and PNG figures. Code must assign a named dictionary to
`analysis_outputs`; the complete input DataFrame is never returned. A failure
returns bounded diagnostics to the specialist and requires a repaired proposal.
At most two actual executions are allowed: one initial program and one targeted
repair. Review rejections do not count. Inspection reports the run's remaining
attempts before code is proposed, so an exhausted run does not create another
Python review.

Terminal outcomes are `analysis_completed`, `needs_sql_reshape`,
`needs_clarification`, and `cannot_analyze`. Truncation always prevents
`analysis_completed`. One `needs_sql_reshape` recovery is permitted.

## Structural validation is not execution

[`validation.py`](../data_analytics_agent/backends/validation.py) parses SQL locally.
It does not submit a preflight query to the database.

The validator:

- rejects empty SQL;
- filters parser nulls;
- requires exactly one statement;
- accepts only `Select` or `SetOperation`;
- rejects forbidden AST nodes.

Validation is deliberately conservative. Expanding allowed query classes must
be treated as a security change and covered by adversarial tests.

Validation is structural rather than a database preflight. Expected validation,
timeout, and provider query errors are returned to the SQL specialist as handled
tool observations. This permits bounded repair without weakening read-only
enforcement or resetting budgets. Saved result IDs remain opaque evidence
handles and are never exposed as database relations.

## Configurable HITL lifecycle

The text-to-SQL specialist calls `execute_sql`, but Deep Agents middleware
interrupts the action before the tool body runs only when
`REQUIRE_SQL_APPROVAL=true`. Autonomous mode omits that middleware entirely and
executes through the same validation, backend, timeout, row cap, budget,
storage, and provenance paths. Python approval follows the same conditional
construction using `REQUIRE_PYTHON_APPROVAL`.

[`run_manager.py`](../data_analytics_agent/run_manager.py):

1. extracts only a reviewable `execute_sql` request;
2. preserves its opaque LangGraph interrupt ID and returns source, dialect,
   timeout, cap, and exact SQL to the application;
3. waits in `approval_required`;
4. translates exactly one decision to an ID-addressed LangGraph
   `Command(resume=...)`;
5. resumes the same checkpoint thread.

Coordinator policy requires text-to-SQL delegations to run sequentially, so an
investigation never creates parallel SQL reviews. Each later assignment starts
only after the previous validated result is available.

Model and tool-call counters are checkpointed with that run. Approving,
editing, or rejecting does not reset them. A proposed `execute_sql` call counts
before review, including rejected or invalid attempts, and the fourth proposal
is stopped before another approval is displayed. A new user message receives a
new budget.

If a budget is exhausted, the run fails with a safe public message and typed
diagnostics. Optional debug diagnostics retain only the last five bounded,
secret-redacted tool payloads. Those payloads can still contain SQL and
business data, so debug mode is intended only for trusted local operation.
The rotating API log always includes bounded, recognized-secret-key-redacted
tool results for operational debugging and can therefore also contain business
data; treat the log file as sensitive application data.

### Approve

The pending SQL is validated and the tool resumes unchanged.

### Edit

The edited SQL is required, validated, and replaces the pending tool arguments.
The exact editor content becomes the executed query.

### Reject

Feedback is returned to the specialist. The query is not executed. The
specialist must revise, validate, and call `execute_sql` again. That call creates
a new interrupt. Rejection is a loop, not a terminal run state.

## Backend enforcement

[`SQLiteBackend`](../data_analytics_agent/backends/sqlite.py) adds:

- URI `mode=ro`;
- an authorizer that denies mutation and administrative opcodes;
- a progress handler tied to a monotonic deadline;
- capped `fetchmany(max_rows + 1)`;
- connection cleanup in `finally`.

[`SnowflakeBackend`](../data_analytics_agent/backends/snowflake.py) additionally
uses the configured least-privilege Snowflake role, forwards provider-native
timeouts, and caps cursor fetching. Application parsing does not replace
warehouse authorization.

## Automatic chart lifecycle

The visualization specialist can read only a saved result from the current
thread and source. It cannot run SQL or arbitrary generated code.

1. `inspect_result_for_chart` exposes the immutable full-result profile, row
   count, truncation state, and at most the first 10 rows.
2. `validate_chart` checks the strict `ChartSpec` against the full capped
   result without rendering.
3. `create_chart` revalidates the spec against the saved result and returns the
   exact `ChartSpec` plus a canonical success message.
4. Progress events expose the chart type and a bounded subset of mappings, but
   omit the result ID and full tool payload.
5. Visualization terminates with `chart_created`, `needs_sql_reshape`, or
   `cannot_create`. The coordinator permits at most one validated SQL-reshape
   recovery cycle.
6. Streamlit renders deterministic trusted Plotly code from that spec and the
   saved rows.

No arbitrary model-generated Python executes. Renderer code and curated styles
remain trusted application code. Histogram
binning and box quartiles are the only analytic chart-layer operations; other
business transforms require validated SQL.

## Result isolation

[`tools.py`](../data_analytics_agent/agents/text_to_sql/tools.py) stores the capped result as an
application artifact and returns only:

- result ID;
- executed SQL;
- columns;
- at most the first 10 rows;
- immutable profile metadata computed across all stored rows;
- row count, truncation, and elapsed time.

[`stores.py`](../data_analytics_agent/stores.py) associates every result with
`thread_id` and `source_id`. Model-facing discovery tools require both and
cannot paginate beyond `head(10)`.
`RunManager` resolves every claimed evidence ID from the current
conversation/source, stably deduplicates claims, puts the primary result first,
and replaces all model-provided metadata with authoritative `ResultStore`
references. Unknown, cross-thread, cross-source, or primary-missing claims fail.

When a run attaches completed statistical analysis, its execution parent is the
primary result even if the answer or report references additional SQL results.
The report retains its complete input-result list independently.

The HTTP result endpoint is unscoped by thread because this POC is explicitly
single-user and local. That endpoint must be authenticated and authorized
before any multi-user deployment.

## Trust boundary

Trusted:

- repository configuration;
- curated OSI models;
- server-created source/backend objects;
- application-generated IDs.

Untrusted:

- user questions;
- model-generated SQL;
- edited SQL until validation;
- model-generated result IDs and SQL claims;
- model-generated chart specifications before result-scoped validation;
- provider error messages before sanitization.

Human approval is informed consent for one reviewed query, not authorization
to broaden source access or run arbitrary statements.

### Report-rendering boundary

The reporting capability does not add an execution approval. It is a
read-only composition flow over artifacts that already passed their existing
SQL or Python review boundaries.

Treat model-produced `ReportBrief` and `ReportSpec` values as untrusted until
schema, artifact scope, and content bindings are validated. The renderer and
its small optional interaction library are trusted application code. The model
may select audited interactions declaratively, but it cannot provide scripts,
event handlers, remote embeds, or raw executable HTML. The self-contained file
may combine only current-thread/current-source artifacts, and Streamlit should
preview it in an isolated frame rather than inject it into the application DOM.

See [Reporting capability](reporting-capability.md) for the complete
renderer, artifact, and UI contract.

## Safe change method

When modifying validation, approval, execution, or result access:

1. State which trust boundary changes.
2. Add failing tests first for allowed and denied behavior.
3. Keep structural validation provider-neutral when possible.
4. Put native controls in the adapter.
5. Verify edited SQL and rejection loops.
6. Verify exact SQL/result provenance.
7. Re-run the live review flow.
8. Update this guide and the sequence diagram.

## Common mistakes

- Executing a query to “validate” it before review.
- Approving generated SQL but executing an invisible rewritten query.
- Treating reject as completed analysis.
- Allowing multiple decisions for one action.
- Trusting SQL or result ID from final model output.
- Returning the entire result through model context.
- Logging unbounded prompts, query payloads, rows, or credentials as progress.
- Enabling debug tool payloads in a shared or untrusted environment.
- Assuming an opaque result ID is an authorization boundary.
- Adding a new specialist that can read artifacts without source/thread scope.

## Production hardening checklist

Before production:

- authenticate users and authorize sources/results;
- persist conversations, runs, checkpoints, and artifacts durably;
- encrypt secrets and connections through a managed secret boundary;
- enforce database least privilege and network policy;
- add request, query, and cancellation observability without data leakage;
- define retention and deletion;
- isolate tenants and rate-limit/constrain concurrency;
- audit approval decisions and exact executed SQL;
- review provider error redaction;
- threat-model prompt injection and semantic-model supply chain.

## Verification checklist

- Multiple and mutating statements are rejected.
- Validation does not touch the database.
- Approval-enabled executions interrupt before the tool body; autonomous
  executions preserve validation, limits, and provenance without an interrupt.
- Edited SQL is validated and executed exactly.
- Reject causes revision and another review.
- Timeout and result cap work at the backend.
- Full rows stay outside model messages.
- Cross-source and cross-thread model result access fails.
- Every final evidence reference contains SQL and metadata resolved from the
  saved artifact.
- Every ordinary chartable data answer attempts one validated chart tied to
  final evidence; reports use `ReportSpec` charts.
- Chart specs cannot inject arbitrary Plotly/Python.
