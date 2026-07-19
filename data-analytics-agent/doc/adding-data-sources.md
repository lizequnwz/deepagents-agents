# Adding data sources

## Purpose and mental model

A data source is a trusted pairing of semantic meaning and executable context:

```text
source = OSI model + backend profile + target + dialect + limits + UI metadata
```

Adding another source on an existing backend should require no agent, API, or
Streamlit code changes.

![Data-source onboarding workflow](diagrams/data-source-onboarding.svg)

[Open the interactive diagram](diagrams/data-source-onboarding.html) ·
[Edit the Archify source](diagrams/data-source-onboarding.workflow.json)

## Current registry contract

The strict schema in [`data_sources.py`](../data_analytics_agent/data_sources.py)
accepts:

```yaml
version: 1
default_source: chinook

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
    target: {}
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
    examples:
      - label: Low inventory
        question: Which five products have the lowest available inventory?
      - label: Fulfillment time
        question: Show average fulfillment time by month.
    limits:
      timeout_seconds: 15
      max_result_rows: 1000
      model_sample_rows: 20
```

Limit constraints:

- `timeout_seconds` must be greater than zero;
- `max_result_rows` is 1–10,000;
- `model_sample_rows` is 1–100 and cannot exceed the result cap.

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
- a simple physical field expression references a missing column;
- primary keys or relationships reference unknown logical fields;
- declared dialect does not match the backend.

One broken source does not disable healthy sources. Errors and warnings are
returned independently.

Readiness validates simple identifier expressions against live metadata.
Complex SQL expressions cannot be fully proven by this check; tests and
curation remain necessary.

## Cloud sources

A cloud source uses the same semantic/source contract but a different backend
profile. Credentials remain outside the registry. The target may carry trusted
database/schema context, while several sources reuse one backend profile.

Do not add a cloud source entry until its backend adapter exists. An unsupported
backend is intentionally unavailable. See the conceptual
[Snowflake blueprint](snowflake-blueprint.md).

## Invariants

- Every selectable source has a valid OSI model.
- Source IDs are stable identifiers; display names may change.
- A source declares the same dialect as its backend.
- A target is trusted server configuration, never user-submitted input.
- Credentials never appear in registry or OSI files.
- A conversation is never migrated to a different source.

## Common mistakes

- Placing the OSI file outside `semantic/`.
- Using semantic field names as physical SQL columns.
- Registering a database without a matching OSI model.
- Copying credentials into `options` or `target`.
- Assuming CSV dictionary files are loaded by the agent.
- Forgetting to restart the API after configuration changes.
- Adding `model_sample_rows` larger than `max_result_rows`.
- Declaring `snowflake` before implementing the adapter.

## Verification checklist

- Database target is readable with least-privilege access.
- OSI model covers intended tables and business meaning.
- Registry loads with no Pydantic validation errors.
- Source summary is ready.
- Sidebar name, description, examples, backend, and dialect are correct.
- Selecting the source creates a source-bound conversation.
- A representative query reaches SQL review and executes only after approval.
- Result ID, source ID, SQL, and downloaded CSV describe the same execution.
