# Semantic-model best practices

## Purpose and mental model

The OSI model is the curated contract between business language and physical
SQL. It should answer:

- What business entities exist?
- Which physical tables and columns implement them?
- How do entities join?
- Which measures and definitions are canonical?
- Which encoded values, dates, units, and caveats matter?

The model is primary schema context. Live metadata tools are fallbacks for
ambiguity and drift, not substitutes for curation.

Authoritative examples:

- [`chinook.osi.yaml`](../semantic/chinook.osi.yaml)
- [`financial.osi.yaml`](../semantic/financial.osi.yaml)

## Required structure

The readiness validator currently requires:

```yaml
version: "0.1.1"

semantic_model:
  - name: example
    description: Business purpose.
    datasets: []
    relationships: []
    metrics: []
```

Exactly one semantic model must exist in each source file.

## Model datasets completely

For every dataset:

```yaml
- name: customers
  description: One row per customer.
  source: Customer
  primary_key:
    - customer_id
  fields:
    - name: customer_id
      description: Stable customer identifier.
      expression:
        dialects:
          - dialect: ANSI_SQL
            expression: CustomerId
```

Best practices:

- Use a stable logical `name` meaningful to the agent.
- Set `source` to the exact physical table/view name.
- State the dataset grain in the description.
- Include every relevant physical field, not only fields used by one example.
- Use logical field names consistently in primary keys and relationships.
- Keep physical expressions exact, including quoted/case-sensitive names when
  required by the backend.

The agent must use `source` and field `expression` values in SQL, not semantic
dataset and field names.

## Prefer portable expressions

Use `ANSI_SQL` for portable identifiers and expressions:

```yaml
expression:
  dialects:
    - dialect: ANSI_SQL
      expression: amount
```

Add a dialect-specific expression only when behavior differs:

```yaml
expression:
  dialects:
    - dialect: snowflake
      expression: TO_DATE(raw_date, 'YYYYMMDD')
    - dialect: sqlite
      expression: date(raw_date)
```

The runtime chooses an exact dialect match first and falls back to
`ANSI_SQL`. A field with neither is a blocking error.

Do not claim portability merely because a query works in SQLite. Date,
timezone, string, quoting, null, and numeric semantics often differ.

## Describe business meaning, not labels

Weak:

```yaml
description: Transaction amount.
```

Stronger:

```yaml
description: Absolute transaction value. Direction is encoded separately in
  transaction_type; do not infer inflow or outflow from the sign alone.
```

Descriptions should capture:

- grain;
- inclusion/exclusion rules;
- direction/sign semantics;
- units and known unknowns;
- date meaning;
- null meaning;
- code enumerations;
- whether a value is authoritative or derived.

Never invent currency, timezone, or business interpretation. The Financial
model deliberately calls out that its dictionary does not reliably document
currency.

## Relationships

Relationships use logical dataset and field names:

```yaml
relationships:
  - name: customers_to_invoices
    from: customers
    to: invoices
    from_columns:
      - customer_id
    to_columns:
      - customer_id
```

Best practices:

- Define the join that preserves intended grain.
- Match `from_columns` and `to_columns` lengths.
- Document bridge/many-to-many tables as datasets.
- Do not skip a relationship because an LLM might infer it.
- Avoid relationships that create ambiguous fan-out without explaining the
  correct aggregation grain.
- Test all relationship references.

Readiness validates references, not cardinality. Cardinality correctness remains
a modeling responsibility.

## Canonical metrics

Metrics reduce repeated invention:

```yaml
metrics:
  - name: transaction_volume
    description: Sum of absolute transaction amount.
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: SUM(amount)
```

For each metric, document:

- aggregation;
- base dataset and grain;
- filters;
- null behavior;
- units;
- date convention;
- distinctness;
- whether negative values have meaning.

Prefer a few well-defined metrics over a long list of ambiguous aliases.
Missing metrics currently produce a warning rather than blocking the source.

## AI context and coded values

Use AI instructions for cross-cutting rules that cannot be inferred safely:

- encoded status mappings;
- direction codes;
- date encodings;
- ranking defaults unique to the domain;
- caveats that affect several datasets;
- preferred canonical metric.

Keep instructions factual and testable. Do not use them to bypass SQL safety,
human review, or source isolation.

## Use data dictionaries systematically

When CSV or written dictionaries exist:

1. Map each documented table to one OSI dataset.
2. Map every intended column to a logical field.
3. Transfer descriptions and code mappings.
4. Record missing/ambiguous documentation explicitly.
5. Compare against live schema.
6. Add relationships from keys.
7. Add canonical metrics only after confirming their business definitions.
8. Add tests for critical codes, dates, and metric names.

The dictionary is evidence, not executable runtime configuration.

## Validation behavior

[`semantic.py`](../data_analytics_agent/semantic.py) checks:

- file existence and YAML mapping;
- version `0.1.1`;
- exactly one semantic model;
- non-empty datasets and fields;
- duplicate logical names;
- physical source presence;
- selected dialect or `ANSI_SQL` expression;
- primary-key references;
- relationship endpoints and column mappings;
- live table existence;
- simple physical identifier existence.

Complex expressions are not fully checked against the database. Add focused
tests and representative queries.

## Invariants

- One source always has one required OSI file.
- The OSI model contains meaning, not credentials.
- Logical names are stable internal vocabulary.
- Physical source and expression values are executable vocabulary.
- Metrics and code mappings never guess undocumented business facts.
- Schema fallback tools do not replace a stale semantic model.

## Common mistakes

- Modeling only the columns needed for one demo.
- Leaving coded statuses unexplained.
- Joining on physical names in the relationship section.
- Using SQLite-only date expressions under `ANSI_SQL`.
- Omitting dataset grain.
- Defining a sum after a one-to-many join without controlling duplication.
- Claiming a currency or timezone absent from the dictionary.
- Renaming a logical field without updating keys and relationships.
- Treating readiness success as proof that business semantics are correct.

## Verification checklist

- OSI version is exactly `0.1.1`.
- Every intended table and field is covered.
- Every description explains business meaning or known ambiguity.
- Primary keys and relationships use logical field names.
- Physical expressions match live columns.
- Portable expressions use `ANSI_SQL`; dialect-specific behavior is explicit.
- Critical status/date mappings appear in AI context.
- Metrics state grain, aggregation, filters, and units.
- Semantic tests and source-readiness tests pass.
- Representative reviewed queries use intended joins and metrics.
