---
name: query-writing
description: Write one safe, dialect-aware, chart-ready SELECT query from the OSI semantic model already loaded for the assignment, falling back to its runtime path only when absent, truncated, or compacted. Submit it for human-reviewed execution for database analysis, metrics, ranking, time series, distributions, relationships, heatmap grids, and other result shaping.
---

# Query Writing

## Ground the query

1. Use the OSI semantic model already loaded for this assignment. If it is
   absent from context, truncated, or compacted, read the exact OSI path from
   the runtime prompt with `limit=1000`.
2. Apply its metric definitions, relationship paths, ambiguity guidance, and
   source-specific instructions.
3. Use exact physical dataset `source` and field-expression names. Select only
   columns needed for the answer or requested chart.
4. Use `write_todos` only when the assignment has several dependent analysis
   steps.

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

1. Use `list_tables` or `get_table_schema` only for a concrete OSI gap or
   suspected schema drift.
2. Call `validate_sql`, then `execute_sql`. Only `execute_sql` runs the query
   and pauses for human review.
3. If review rejects the query, apply the feedback and submit a revised,
   validated query. If review edits it, treat the executed edit as
   authoritative.
4. Finish only after a successful `QueryResult`.

Return the business answer plus the exact executed SQL, result ID, columns,
full-result profile, at most the provided first 10 rows, stored row count, and
truncation flag. Never claim the stored row count is the uncapped database
total when `truncated` is true.
