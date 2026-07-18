---
name: query-writing
description: Write safe SQLite SELECT queries for Chinook analysis and submit them for human-reviewed execution.
---

# Query Writing

1. Read `/project/semantic/chinook.osi.yaml` first with a limit of at least
   1000 lines. Treat it as the primary source of tables, columns, joins, and
   metric definitions.
2. For a complex multi-step question, use `write_todos` before writing SQL.
   Skip todos for a straightforward lookup or aggregation.
3. Use exact physical names from OSI expressions. Query only needed columns.
4. Use `sql_db_query_checker` before `execute_sql`. Use schema tools only if
   OSI lacks necessary detail.
5. Call only `execute_sql` to run SQL. It pauses for human approval and may
   return an edited query result after review.

## SQL rules

- Exactly one read-only SQLite query: SELECT, WITH/CTE, or a set operation.
- No DML, DDL, transactions, PRAGMA, ATTACH, or multiple statements.
- Default list/ranking output to `LIMIT 5` unless the user specifies otherwise.
- Aggregations that naturally return one row do not need a limit.
- Never use `SELECT *`.
- Prefer `Invoice.Total` for invoice-level revenue and
  `InvoiceLine.UnitPrice * InvoiceLine.Quantity` for line-level analysis.
- Avoid multiplying invoice totals after joining invoices to line items.
- Always apply a deterministic ordering to top/bottom questions.

## Response

Return the business answer, exact executed SQL, result ID, capped row count,
brief assumptions, and a concise interpretation. Do not expose chain of thought.
