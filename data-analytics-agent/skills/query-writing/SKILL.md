---
name: query-writing
description: Write safe dialect-aware SELECT queries and submit them for human-reviewed execution against the selected data source.
---

# Query Writing

1. Read the exact OSI path identified by the runtime system prompt first, with
   a limit of at least 1000 lines. Treat it as the primary source of tables,
   columns, joins, metric definitions, and source-specific instructions.
2. For a complex multi-step question, use `write_todos` before writing SQL.
   Skip todos for a straightforward lookup or aggregation.
3. Use exact physical names from OSI expressions. Query only needed columns.
4. Use `validate_sql` before `execute_sql`. Use `list_tables` and
   `get_table_schema` only if OSI lacks necessary detail or appears stale.
5. Call only `execute_sql` to run SQL. It pauses for human approval and may
   return an edited query result after review.

## SQL rules

- Use the SQL dialect named in the runtime system prompt.
- Exactly one read-only query: SELECT, WITH/CTE, or a set operation.
- No DML, DDL, stored procedures, administrative or session commands,
  metadata commands, transactions, or multiple statements.
- Default list/ranking output to `LIMIT 5` unless the user specifies otherwise.
- Aggregations that naturally return one row do not need a limit.
- Never use `SELECT *`.
- Follow source-specific metric definitions and ambiguity warnings in OSI.
- Avoid fan-out errors when joining facts at different grains.
- Always apply a deterministic ordering to top/bottom questions.

## Response

Return the business answer, exact executed SQL, result ID, capped row count,
brief assumptions, and a concise interpretation. Do not expose chain of thought.
