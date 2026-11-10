# Adding data sources

A configured source combines an OSI semantic model with a backend profile,
target, dialect, execution limits, and display metadata. To add a source to an
existing backend, update the registry and supply its semantic model.

## Current registry contract

The strict schema in [`data_sources.py`](../../data_analytics_agent/data_sources.py)
accepts:

```yaml
version: 1
default_source: source_id

backends:
  local_sqlite:
    type: sqlite
    options: {}

sources:
  source_id:
    name: Human-readable name
    description: Sidebar description
    backend: local_sqlite
    semantic_model: semantic/source.osi.yaml
    dialect: sqlite
    target:
      path: db/source/source.sqlite
    examples: []
    limits: {}
```

Unknown keys are rejected. Semantic files must resolve inside `semantic/`.

## Add another SQLite source

### 1. Prepare the database

Place the SQLite file somewhere readable by the API process. Keeping local POC
data under `db/<source_id>/` makes ownership clear.

Do not put a database file path in `.env`. Physical targets belong in the
trusted registry.

### 2. Inspect the physical schema and dictionary

Before writing OSI:

- inventory every table/view;
- inventory every column and type;
- identify primary and foreign keys;
- document coded values and date encodings;
- identify authoritative business measures;
- record unknown units or currency rather than guessing.

CSV data dictionaries are useful authoring inputs, but they are not loaded
automatically at runtime. Curate their meaning into the OSI model.

### 3. Create the OSI model

Create `semantic/<source_id>.osi.yaml` with version `0.1.1`. Follow
[Semantic-model best practices](semantic-model-best-practices.md).

At minimum, define:

- one semantic model;
- at least one dataset;
- physical `source` for each dataset;
- fields with the selected dialect or `ANSI_SQL` expression;
- valid primary keys;
- valid relationships when datasets join.

Metrics are strongly recommended. Their absence produces a warning rather than
blocking readiness.

### 4. Register the source

```yaml
sources:
  inventory:
    name: Inventory
    description: Product inventory, orders, and fulfillment performance.
    backend: local_sqlite
    semantic_model: semantic/inventory.osi.yaml
    dialect: sqlite
    target:
      path: db/inventory/inventory.sqlite
    examples: []  # Add questions after validating your own source.
    limits:
      timeout_seconds: 15
      max_result_rows: 1000
      model_sample_rows: 10
```

Limit constraints:

- `timeout_seconds` must be greater than zero;
- `max_result_rows` is positive (default 1,000,000; the application also applies its byte budget);
- `model_sample_rows` is 1–10 and cannot exceed the result cap.

Omitted limits inherit validated global defaults.

### 5. Restart and inspect readiness

Registry and source-summary caches are process-local. Restart FastAPI after a
registry, target, or semantic-model change.

Run:

```bash
uv run python -c \
  'from data_analytics_agent.api import Services; print([(s.source_id, s.ready, s.errors, s.warnings) for s in Services().source_summaries()])'
```

Or inspect:

```text
GET http://127.0.0.1:8000/api/data-sources
```

The source becomes selectable only when `ready` is true.

### 6. Test the source

Add or update tests that assert:

- expected physical tables and fields;
- relationship references;
- important metrics and AI context;
- registry target, dialect, and limits;
- live table/column readiness;
- source isolation where relevant.

Then run:

```bash
uv run pytest
```

## Adjust an existing source

| Change | File | Restart required |
| --- | --- | --- |
| Display name or description | `data_sources.yaml` | Yes |
| Starter questions | `data_sources.yaml` | Yes |
| Default source | `data_sources.yaml` | Yes |
| Backend target | `data_sources.yaml` | Yes |
| Limits | `data_sources.yaml` or global environment | Yes |
| Field description or metric | OSI file | Yes |
| Physical schema | Database and matching OSI model | Yes |

Starting a new conversation after semantic changes is preferable because an
existing agent checkpoint may contain earlier context.

## Readiness behavior

A source is blocked when:

- backend type is unsupported;
- target is missing or unreadable;
- OSI file is absent;
- OSI version or structure is invalid;
- dataset table is missing;
- a physical column referenced by a field expression is missing;
- primary keys or relationships reference unknown logical fields;
- declared dialect does not match the backend.

One broken source does not disable healthy sources. Errors and warnings are
returned independently.

Readiness checks referenced physical columns, including columns inside computed
expressions, against live metadata. It does not prove business correctness or
execute every expression; focused tests and curation remain necessary.

## Add a Snowflake source

Install the optional `snowlib` package in the API environment and configure its
default role, database, and schema. Use a read-only role. Application validation
adds query checks to the permissions already enforced by Snowflake. Keep
credentials outside the registry and OSI files.

```yaml
version: 1
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

The API creates a shared client when Snowflake sources are configured. Multiple
semantic sources can share its default context. Each declares its own OSI model
and an empty `target`; there are no per-source role or schema settings. Readiness
checks the declared tables through `INFORMATION_SCHEMA.COLUMNS` in the current
schema. For SQL review and timeout settings, see [configuration](configuration.md#controlling-a-run).

## Implement a backend adapter

Implement [`SQLBackend`](../../data_analytics_agent/backends/base.py) and register
the adapter in the [backend factory](../../data_analytics_agent/backends/factory.py).
The adapter owns the connection, dialect, exact SQL execution, cancellation, and
live schema inspection. The configured target comes from the trusted registry.
Source IDs stay stable when display names change. Conversations stay bound to the
source selected at creation. Automatic selection uses the first question and each
ready source’s name, description, example questions, and logical dataset and metric
names. Write descriptions and examples that distinguish similar sources.

- `dialect` names the SQLGlot dialect and `backend_type` identifies the adapter.
- `execute_batches(query, *, timeout_seconds, cancel=None)` validates the exact
  submitted SQL and streams bounded, typed PyArrow `RecordBatch` objects. Preserve
  decimal and temporal types and execute reviewed SQL exactly as approved.
- `get_table_schema(table_names)` returns metadata for the requested declared
  tables in the same context used for execution.

The artifact writer unifies compatible batch schemas, applies row and byte limits,
and records incomplete extraction. It closes the iterator at the limit. Release
cursors and connections in `finally` blocks. Raise `SQLExecutionError` for
expected query rejection, `SQLValidationError` for disallowed SQL, and
`TimeoutError` on expiry. Query errors should include useful details and omit
credentials.

Check cancellation between batches and use native interruption when available.
SQLite uses a progress handler. Snowflake uses its query timeout and checks for
cancellation between fetches. The UI remains **Stopping** until the worker exits.
Only the SQL specialist has source access. Saved-data SQL uses DuckDB with
explicit artifact bindings, and Python and charts consume saved artifacts.

See [backend tests](../../tests/test_backends.py),
[Snowflake tests](../../tests/test_snowflake_backend.py), and
[artifact workflow tests](../../tests/test_persistent_analyst.py) for exact
queries and reviewed edits, decimal and null-first batches, provenance, errors,
cleanup, cancellation, and extraction limits. Snowflake unit tests use an injected
client. Live authentication and connector behavior require provider tests.

## Verification checklist

- Database target is readable with least-privilege access.
- OSI model covers intended tables and business meaning.
- Registry loads with no Pydantic validation errors.
- Source summary is ready.
- Sidebar name, description, examples, backend, and dialect are correct.
- A representative first question selects the source in Automatic mode, and an explicit selection starts the same source-bound workflow.
- A representative query returns checked results; when SQL review is enabled, it pauses and executes the exact approved query.
- Result ID, source ID, SQL, and downloaded CSV describe the same execution.
