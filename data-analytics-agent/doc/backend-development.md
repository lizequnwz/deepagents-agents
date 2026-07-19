# Backend development

## Purpose and mental model

`SQLBackend` is the database-provider boundary. The agent supplies reviewed SQL
and execution limits; the adapter validates, executes, caps, normalizes, and
returns metadata through stable Python values.

The protocol is defined in
[`backends/base.py`](../data_analytics_agent/backends/base.py). It is structural:
adapters do not need to subclass a base class if they satisfy the contract.

## Required contract

| Member | Responsibility |
| --- | --- |
| `dialect` | SQLGlot dialect expected by the adapter |
| `backend_type` | Registry/factory discriminator |
| `readiness_errors()` | Return actionable expected setup errors without raising |
| `validate_sql(query)` | Reject anything except one safe read-only query |
| `execute(query, timeout_seconds, max_rows)` | Execute exact validated SQL and return a normalized capped result |
| `list_tables()` | List queryable tables/views in the source context |
| `get_table_schema(table_names)` | Return normalized table and column metadata |

Execution returns:

```text
BackendExecutionResult
├── columns: list[str]
├── rows: list[dict[str, Any]]
├── truncated: bool
└── elapsed_ms: float
```

## Execution invariants

Every adapter must:

1. Validate inside `execute` even if the caller already validated.
2. Execute the exact reviewed query without invisible rewriting.
3. Enforce `timeout_seconds` using provider-native cancellation or deadline
   controls.
4. fetch at most `max_rows + 1` when practical;
5. return no more than `max_rows`;
6. report `truncated` accurately;
7. close/release cursors and connections in success and failure paths;
8. normalize provider-native values;
9. propagate an actionable provider error without exposing credentials.

Use [`normalize_result_value`](../data_analytics_agent/backends/base.py) for common
values:

- `Decimal` becomes string to avoid precision loss;
- dates/times become ISO strings;
- bytes become hexadecimal;
- unknown native objects become strings.

If a provider returns pandas or Arrow objects, convert at the backend boundary.
The rest of the application should never depend on that provider library.

## Metadata methods

`list_tables` and `get_table_schema` support:

- startup source/OSI readiness;
- agent fallback when semantic context is ambiguous or stale.

Return provider-independent `TableInfo` and `ColumnInfo`. Preserve the
provider's physical name while making lookup behavior explicit.

Metadata operations may use provider-specific catalog APIs or internal
`INFORMATION_SCHEMA` queries. They are not user-generated SQL actions, but
should still use least-privilege credentials and bounded operations.

## Validation

Reuse:

```python
validate_readonly_sql(query, dialect=self.dialect)
```

The shared validator parses exactly one statement with SQLGlot and accepts
`SELECT`, CTE, and set-operation queries while rejecting DDL, DML,
administrative/session commands, procedures, transactions, metadata commands,
and multiple statements.

Provider-native safety is still required. SQLite adds a read-only connection,
authorizer, and progress handler. A cloud warehouse should add least-privilege
roles, provider timeout/cancellation, and restricted source context.

## Adapter procedure

### 1. Define connection ownership

Decide whether the adapter receives:

- an existing client;
- a connection factory;
- a pool/provider;
- immutable connection settings resolved by the API.

Prefer dependency injection. Do not load credentials from the semantic model,
agent prompt, or user request.

For a stateful cloud provider, avoid one globally shared connection whose
database, schema, warehouse, or role is changed per request. Acquire a correctly
configured connection/session for each source-bound operation.

### 2. Implement the protocol

Create `data_analytics_agent/backends/<provider>.py`. Keep imports provider-local so
SQLite-only development does not require the optional cloud package.

### 3. Register construction

[`backends/factory.py`](../data_analytics_agent/backends/factory.py) currently uses a
small explicit branch. Add the backend type and verify its declared dialect
matches the constructed adapter.

When adding Snowflake, evolve this into an injected provider registry rather
than growing a long `if/elif` chain. The API service can cache source-bound
backend wrappers while a provider layer manages shared configuration or pools.

### 4. Add registry support

`BackendDefinition.options` and `SourceDefinition.target` are generic mappings:

- `options` identifies non-secret backend/profile configuration;
- `target` selects trusted source-specific context.

Never serialize a client object or credential into YAML.

### 5. Add contract tests

Follow [`test_backends.py`](../tests/test_backends.py). A fake cloud-like
adapter should prove that `execute_query`:

- accepts dependency injection;
- passes limits;
- preserves exact SQL;
- stores source provenance;
- separates full result and model sample.

Provider-specific tests should also cover:

- readiness failures;
- invalid/multiple/mutating SQL;
- timeout and cancellation;
- row truncation;
- null/decimal/date/binary normalization;
- cursor/connection cleanup;
- table and schema introspection;
- quoted/case-sensitive identifiers;
- provider error sanitization.

Do not require live cloud credentials in the normal suite. Put live smoke tests
behind an explicit marker and environment opt-in.

## Current factory limitations

The current construction layer is adequate for SQLite and one next adapter, but
is not yet a plugin system:

- backend types are registered manually;
- instances are cached per source;
- no explicit close/cancel lifecycle exists in the protocol;
- execution is synchronous;
- result metadata has no provider query ID or cost information.

Do not expand the protocol speculatively. Add optional execution metadata,
cancellation, or async methods only when a real adapter requires them and tests
can define the behavior.

## Keep backend and agent contracts separate

A new database backend should not require a new subagent. A new specialist
agent should not know how a cursor works.

Use this division:

- backend: connection, SQL dialect, safety, execution, metadata, normalization;
- text-to-SQL specialist: semantic interpretation and query design;
- coordinator: capability routing and final response;
- application: lifecycle, persistence, UI, and artifact access.

The visualization specialist demonstrates this separation: it consumes a
scoped saved result and never imports a database driver.

## Common mistakes

- Returning a DataFrame directly to the model.
- Applying an unreviewed `LIMIT` rewrite.
- Validating only before HITL, not inside execution.
- Treating SQLGlot as the database authorization layer.
- Fetching all cloud rows before applying the cap.
- Mutating a shared cloud session context across concurrent sources.
- Returning exception text that includes a connection string.
- Implementing metadata methods with different source context than execution.
- Adding provider-specific fields to generic API response schemas.

## Verification checklist

- Adapter satisfies `SQLBackend` at runtime.
- Source dialect equals backend dialect.
- One invalid source does not break healthy sources.
- Exact approved/edited SQL is executed.
- Timeout and cap are enforced by the adapter.
- Normalized values are JSON compatible and precision safe.
- Metadata matches the same target used by execution.
- Result artifact contains the correct source and thread.
- Normal tests use fakes; live smoke is opt-in.
- Agent, API schemas, and Streamlit contain no provider-specific branches.
