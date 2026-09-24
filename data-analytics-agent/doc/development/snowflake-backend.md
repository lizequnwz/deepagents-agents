# Snowflake backend

Snowflake is an optional source adapter. The API creates a shared `snowlib`
client only when a Snowflake source is configured. `snowlib` owns authentication,
connection management, and the default role, database, and schema. Configure a
read-only Snowflake role; the application's SQL validation is an additional
execution control, not warehouse authorization.

## Configure a source

The adapter uses one default `snowlib` context. Every Snowflake source must
declare the `snowflake` dialect, its own OSI semantic model, and an empty
`target` mapping:

```yaml
default_source: example

backends:
  default_snowflake:
    type: snowflake

sources:
  example:
    name: Example warehouse
    description: Curated Snowflake source
    backend: default_snowflake
    dialect: snowflake
    target: {}
    semantic_model: semantic/example.osi.yaml
```

Keep credentials outside the source registry and OSI model. Multiple semantic
sources can use the same default context; the adapter does not switch roles or
schemas per source. A failed Snowflake source does not disable healthy sources.
See [adding data sources](adding-data-sources.md) for the full registry and
readiness process.

## Execution boundary

`SnowflakeBackend` validates read-only SQL, sends it through the shared client
with the source timeout, and yields typed Arrow record batches. The artifact
writer applies dataset row and byte limits and records incomplete extraction.
The adapter checks cancellation between fetch batches and closes cursors on
completion or failure. It reads requested table metadata from
`INFORMATION_SCHEMA.COLUMNS` in the current schema for source readiness.

SQL review is optional and disabled by default. Set `REQUIRE_SQL_APPROVAL=true`
to review, edit, or reject a proposed query before execution. An approved edit
is executed exactly against the selected source. Python
review is configured separately; the analysis specialist receives saved
datasets, never Snowflake credentials or a client. See
[configuration](configuration.md#controlling-a-run) for review and limits.

Normal backend tests use an injected fake client and cover exact SQL, timeout
and cancellation handling, typed batches, metadata, and cursor cleanup. Live
Snowflake authentication and connector behavior require separate provider tests.
