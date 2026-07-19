# SQL safety and human review

## Purpose and mental model

Safety is layered. No prompt, parser, human decision, or database permission is
sufficient by itself.

![Query execution and approval sequence](diagrams/query-approval.svg)

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
| HITL | Every `execute_sql` pauses for approve/edit/reject |
| Chart execution | `create_chart` auto-runs a constrained, result-scoped spec |
| Edit validation | Edited text is parsed again before resume |
| Chart validation | Strict schema, known columns/types, readability limits, immutable result ID |
| Backend validation | Adapter validates again immediately before execution |
| Native database control | SQLite read-only URI, authorizer, and progress deadline |
| Limits | Timeout, capped fetch, bounded model sample |
| Provenance | Results and answers are scoped to source and conversation |

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

## HITL lifecycle

The text-to-SQL specialist calls `execute_sql`, but Deep Agents middleware
interrupts the action before the tool body runs.

[`run_manager.py`](../data_analytics_agent/run_manager.py):

1. extracts only a reviewable `execute_sql` request;
2. returns source, dialect, timeout, cap, and exact SQL to the application;
3. waits in `approval_required`;
4. translates exactly one decision to LangGraph `Command(resume=...)`;
5. resumes the same checkpoint thread.

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

A future cloud adapter must use an actual read-only database role and
provider-native timeout/cancellation. Application parsing does not replace
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
   `cannot_create`. The coordinator permits at most one reviewed SQL-reshape
   recovery cycle.
6. Streamlit renders deterministic trusted Plotly code from that spec and the
   saved rows.

No arbitrary model-generated Python executes. Renderer code and curated styles
remain trusted application code. Histogram
binning and box quartiles are the only analytic chart-layer operations; other
business transforms require reviewed SQL.

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
`RunManager` rejects a final result ID outside the current conversation/source
and replaces model-paraphrased SQL with the saved executed SQL.

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
- Logging raw prompts, query payloads, rows, or credentials as progress.
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
- Every execution reaches approval first.
- Edited SQL is validated and executed exactly.
- Reject causes revision and another review.
- Timeout and result cap work at the backend.
- Full rows stay outside model messages.
- Cross-source and cross-thread model result access fails.
- Final answer SQL equals the saved artifact SQL.
- Every chart is explicitly requested, validated before rendering, and tied to
  the saved artifact.
- Chart specs cannot inject arbitrary Plotly/Python.
