---
name: query-writing
description: Ground a database question with the source-bound semantic discovery tools, then write one safe, dialect-aware, chart-ready SELECT query and execute it with optional review. Use for database analysis, metrics, ranking, time series, distributions, relationships, heatmap grids, and other result shaping.
---

# Query Writing

## Ground the query

1. Use the semantic overview for orientation. When the relevant entities are
   not obvious, call `search_semantic_model` with business terms from the
   assignment. For initial selection, search only dataset and metric kinds;
   include fields only when exact field discovery is still needed. Keep the
   result limit between 1 and 10 and normally request no more than 5 matches.
2. Fetch the exact relevant datasets, fields, and metrics in one batched
   `get_semantic_entities` call, with at most 10 datasets and 10 metrics. Every
   requested name, including names in `field_names`, is a logical snake_case
   name from the overview or search results, never a physical SQL name such as
   `InvoiceId`. Use the returned physical sources and selected dialect
   expressions exactly as declared.
   When requesting more than two datasets, provide `field_names` for every
   dataset and list only fields required by the query; use an empty list when
   only dataset metadata is needed.
3. When more than one dataset is required, call `get_relationships` and use
   only the returned declared path and join fields. Make this call after exact
   entity selection and request only the datasets required by the query.
4. Identify the relevant logical datasets and fields, metric definitions,
   synonyms, source-specific instructions, and requested business grain.
5. Resolve the requested business grain and note only material ambiguity that
   changes the query or answer. Stop schema exploration when the OSI model
   provides enough information to write the query.
6. Use only declared relationship paths and exact physical dataset `source`
   and field-expression names. Select only columns needed for the answer or
   requested chart.
7. Treat a missing physical source or field as a source-readiness problem. Do
   not explore undeclared database objects or probe row values for discovery.
8. Use `write_todos` only when the assignment has several dependent analysis
   steps.

When explaining schema, distinguish physical source or expression names from
logical OSI dataset and field names.

## SQL rules

- Use the SQL dialect named in the runtime system prompt.
- Exactly one read-only query: SELECT, WITH/CTE, or a set operation.
- No DML, DDL, stored procedures, administrative or session commands,
  metadata commands, transactions, or multiple statements.
- Do not add `LIMIT` unless the user explicitly requests a row count. Ranking
  words such as "top" or "highest" require deterministic ordering but do not
  imply a hidden count.
- Keep the user-requested SQL row count separate from the application's
  configurable retrieval cap. The cap protects execution and storage; it is
  not a reason to write `LIMIT`.
- Never use `SELECT *`.
- Avoid fan-out errors when joining facts at different grains.
- Always apply a deterministic ordering to top/bottom questions.

## Shape complete analytical results

- Put business filters, grouping, calculations, binning, and requested
  limiting in SQL. The visualization layer must not reconstruct business
  logic.
- Return the complete grain needed by the question: all requested rows, the
  full ordered time series, the full observation set for distributions, or the
  full relationship dataset, subject only to the retrieval cap.
- For heatmaps, return one row per unique x/y cell with both axes categorical,
  temporal, or explicitly binned numeric and a numeric value column.
- For pies and choropleths, aggregate to one row per category or location.
- Give result columns clear, stable aliases suitable for coordinator and chart
  field selection.

## Validate, review, and finish

1. Call `execute_sql`. It validates the query once immediately before execution
   and pauses for human review when approval is enabled.
2. If review rejects the query, apply the feedback and submit a revision. If
   review edits it, treat the executed edit as authoritative.
3. Finish only after a successful `QueryResult`.

Return the business answer plus the exact executed SQL, result ID, columns,
full-result profile, at most the provided first 10 rows, stored row count, and
truncation flag. Never claim the stored row count is the uncapped database
total when `truncated` is true.

## Reuse saved data

Use query_saved_results with explicit alias-to-artifact bindings and DuckDB SQL
for descriptive reshaping of saved snapshots. Inspect the resulting profile.
Use browse_semantic_model for paginated dataset/field discovery and lookup_values
for bounded source category discovery. Reuse is a snapshot; fresh/current
requests require new source execution. Source queries remain sequential.
