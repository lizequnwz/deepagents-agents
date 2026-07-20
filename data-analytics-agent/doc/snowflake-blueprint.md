# Snowflake backend

## Status and scope

Snowflake is implemented as a thin optional adapter over the separately
provided `snowlib` package. `snowlib` owns authentication, environment/config
loading, connection lifecycle, and the default role/database/schema context.
The Data Analytics Agent owns SQL validation, bounded result conversion,
metadata normalization, and the generic backend contract.

The objective is to add Snowflake without changing the coordinator, text-to-SQL
contract, HITL lifecycle, generic API responses, result storage, or Streamlit.

## Desired shape

The current intentionally small integration uses one configured Snowflake
context and may support multiple semantic sources over that same context:

```text
snowlib default context
├── OAuth, credentials, and connection management
├── source A -> OSI A + trusted database/schema context
├── source B -> OSI B + trusted database/schema context
└── source C -> OSI C + trusted database/schema context
```

Their OSI models and user-facing metadata may differ. Multiple profiles and
per-source context switching are deliberately out of scope. Snowflake sources
therefore declare an empty `target` mapping.

## Adapter responsibilities

`SnowflakeBackend` implements the existing `SQLBackend` contract:

- readiness and target-access diagnostics;
- `snowflake` dialect validation;
- exact reviewed-query execution;
- provider-native timeout/cancellation;
- bounded fetch and accurate truncation;
- JSON-safe value normalization;
- table/view listing in the configured context;
- normalized schema metadata;
- connection/cursor cleanup and sanitized failures.

It must use a genuinely read-only Snowflake role. The shared parser and human
review remain defense-in-depth layers, not warehouse authorization.

## Connection boundary

Implemented design:

- the application lazily creates `SnowflakeManager().get_client()` only when a
  Snowflake source is configured;
- the API injects that long-lived client into `SnowflakeBackend`;
- the client safely handles authentication refresh, reconnection, and
  concurrent queries;
- the registry selects `type: snowflake` and uses `target: {}`;
- `run_query(query, timeout_seconds=...)` returns a cursor-like result;
- the adapter calls `fetchmany(max_rows + 1)` and closes the cursor without
  closing the client.

Do not:

- put credentials in YAML or OSI;
- let a user choose arbitrary account/database/schema;
- switch role/schema on one global mutable connection;
- make the agent aware of connection objects;
- expose provider-native results through generic APIs.

## Registry shape

```yaml
backends:
  default_snowflake:
    type: snowflake

sources:
  example:
    backend: default_snowflake
    dialect: snowflake
    target: {}
```

The explicit factory has one Snowflake branch and retains dialect consistency
checks. A failed Snowflake client or context marks only its source unavailable;
SQLite-only startup does not require `snowlib`.

## Semantic considerations

Snowflake OSI models should:

- prefer `ANSI_SQL` expressions when genuinely portable;
- use `snowflake` expressions for provider-specific dates, variants, or
  functions;
- use a consistent rule for database/schema qualification;
- account for quoted identifier case sensitivity;
- model views and secure views intentionally;
- document timezone, currency, and semi-structured data semantics;
- align metadata introspection with the exact execution context.

## Test strategy

Normal tests use a fake injected client/cursor and cover:

- empty-target and injected-client construction;
- exact SQL, timeout, and row cap passed to the adapter;
- timeout/cancellation translation;
- capped decimal/date/binary result normalization;
- metadata and case handling;
- cursor cleanup;
- lazy client creation and SQLite-only isolation.

Live Snowflake and `snowlib` tests remain outside this repository. Adapter tests
use a fake cursor/client and do not test authentication or connector behavior.

## Acceptance criteria

The integration is complete for its intentionally narrow scope when:

- Snowflake sources use their required OSI models over the configured default
  context;
- changing source creates a new conversation;
- coordinator, agent contracts, API responses, and UI remain provider-neutral;
- every query still pauses for review;
- exact edited SQL executes under a read-only role;
- metadata and execution observe the same database/schema;
- results use the existing normalized artifact contract;
- SQLite tests continue to pass;
- fake adapter tests pass.

## Relationship to future specialist agents

Snowflake should remain only a data-execution capability. Future visualization
or statistical specialists should consume saved, provenance-scoped result
artifacts. They should not receive Snowflake clients or credentials.
