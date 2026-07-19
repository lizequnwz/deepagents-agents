# Conceptual Snowflake blueprint

## Status and scope

Snowflake is not implemented or installed in this POC. This document defines
the intended boundaries only. It deliberately avoids connector-specific code,
package choices, and setup instructions until a Snowflake client is selected.

The objective is to add Snowflake without changing the coordinator, text-to-SQL
contract, HITL lifecycle, generic API responses, result storage, or Streamlit.

## Desired shape

One trusted Snowflake backend profile may support multiple semantic sources:

```text
Snowflake profile
├── connection/credential provider outside registry
├── source A -> OSI A + trusted database/schema context
├── source B -> OSI B + trusted database/schema context
└── source C -> OSI C + trusted database/schema context
```

If all sources share the same database/schema context, only their OSI models
and user-facing metadata need differ. If context differs, the source target
must carry database/schema/warehouse/role identifiers while credentials remain
unchanged and external.

## Adapter responsibilities

A future `SnowflakeBackend` must implement the existing `SQLBackend` contract:

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

Recommended design:

- the API receives/injects a Snowflake connection provider;
- registry `backend.options` identifies a non-secret profile;
- source `target` identifies trusted execution context;
- each operation acquires a correctly configured connection/session;
- provider configuration or pools may be shared;
- mutable session context is not shared unsafely across concurrent sources.

Do not:

- put credentials in YAML or OSI;
- let a user choose arbitrary account/database/schema;
- switch role/schema on one global mutable connection;
- make the agent aware of connection objects;
- expose provider-native results through generic APIs.

## Factory evolution

The current explicit factory is adequate for SQLite. When Snowflake is added:

1. introduce a backend/provider registry or injected factory;
2. register `sqlite` and `snowflake` constructors;
3. keep source-bound wrappers cached by source;
4. let the provider own shared configuration/pooling;
5. keep dialect consistency checks;
6. preserve healthy-source isolation when one Snowflake source is unavailable.

This is the only construction-layer refactor anticipated. Agent and UI
behavior should remain unchanged.

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

Normal tests should use a fake injected client/provider and cover:

- source-to-profile/target resolution;
- exact SQL and limits passed to the adapter;
- timeout/cancellation translation;
- capped result normalization;
- decimal/date/time/binary/semi-structured values;
- metadata and case handling;
- unavailable target isolation;
- source/thread result provenance;
- redacted exceptions and cleanup.

An opt-in live smoke test can verify connectivity, metadata, one reviewed
read-only query, timeout behavior, and result normalization. It must not run in
the normal local/CI suite.

## Acceptance criteria

Snowflake integration is complete when:

- at least two Snowflake sources can share one non-secret backend profile;
- each source loads its own required OSI model and trusted context;
- changing source creates a new conversation;
- normal agent/API/UI code contains no Snowflake branch;
- every query still pauses for review;
- exact edited SQL executes under a read-only role;
- metadata and execution observe the same database/schema;
- results use the existing normalized artifact contract;
- SQLite tests continue to pass;
- fake adapter tests and opt-in Snowflake smoke tests pass.

## Relationship to future specialist agents

Snowflake should remain only a data-execution capability. Future visualization
or statistical specialists should consume saved, provenance-scoped result
artifacts. They should not receive Snowflake clients or credentials.
