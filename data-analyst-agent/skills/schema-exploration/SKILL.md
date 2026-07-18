---
name: schema-exploration
description: Ground Chinook questions in its OSI semantic model, with live SQLite schema inspection only as fallback.
---

# Schema Exploration

1. Always read `/project/semantic/chinook.osi.yaml` before using database
   introspection. Use a read limit of at least 1000 lines.
2. Locate relevant datasets, physical sources, fields, relationships, metrics,
   AI instructions, and synonyms in that file.
3. Use `sql_db_list_tables` or `sql_db_schema` only to resolve a concrete gap
   or verify drift between the semantic model and the database.
4. Never probe the database with exploratory SQL when the semantic model
   already answers the question.

When explaining schema, distinguish physical names such as `InvoiceLine` from
logical OSI names such as `invoice_lines`. Use only declared relationship paths.
Playlist membership is not a sale.
