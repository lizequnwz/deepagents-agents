# Backend development

`SQLBackend` owns connection setup, SQL dialect, exact execution, cancellation,
and live schema inspection. It never composes an agent answer. The current
adapters are SQLite and Snowflake; register new adapters in the backend factory
and keep source-specific configuration in the trusted data-source registry.

## Contract

See [`backends/base.py`](../data_analytics_agent/backends/base.py):

- `dialect` is the SQLGlot dialect; `backend_type` identifies the adapter.
- `execute_batches(query, *, timeout_seconds, cancel=None)` yields typed
  PyArrow `RecordBatch` objects. Validate the exact submitted SQL immediately
  before execution. The optional cancellation event belongs to the run.
- `get_table_schema(table_names)` returns metadata for requested declared tables
  in the same source context used for execution.

Yield bounded batches instead of collecting all rows in dictionaries. Preserve
Decimal and temporal types. The application artifact writer unifies compatible
batch schemas, applies row and uncompressed-byte budgets, writes Parquet, and
records incomplete extraction explicitly. It closes the iterator on budget
exhaustion; adapters must release cursors and connections in `finally` blocks.
Default dataset budgets are one million rows and 256 MiB. Agent previews contain
at most ten rows; full downloads read the complete saved artifact.

Raise `SQLExecutionError` for expected provider query rejection,
`SQLValidationError` for disallowed SQL, and `TimeoutError` for execution
expiry. Return useful, credential-free errors so SQL can revise its query.
Do not disguise application defects as query errors. Execute human-edited SQL
exactly, without silently adding limits or changing predicates.

## Cancellation and source access

Execution runs in workers with per-conversation source serialization. Check the
cancellation event between batches and use provider-native interruption where
available. SQLite installs a progress handler. A blocking provider request may
not exit immediately; the UI remains **Stopping** until the worker exits.
Never claim cancellation finished while source execution is still active.

Source access belongs to the SQL specialist. Python reads saved datasets only.
Saved-data SQL uses DuckDB with explicit artifact bindings; it does not pass
artifact IDs to a warehouse or require a new source connection. Chart creation
also consumes saved artifacts through its own shared tool.

## Verification

Follow [`test_backends.py`](../tests/test_backends.py) and
[`test_persistent_analyst.py`](../tests/test_persistent_analyst.py). Cover exact
SQL and reviewed edits, typed values including null-first batches and decimals,
source provenance, errors, resource cleanup, timeout/cancellation, and writer
budget exhaustion. A 100,000-row fixture must survive storage, analysis,
pagination and full download without becoming a preview-sized dataset.

Normal tests use local fixtures and fake provider clients. Live provider tests
are opt-in. Avoid adding speculative plugin abstractions, cost metadata, or
provider-specific fields to the agent/API contracts.
