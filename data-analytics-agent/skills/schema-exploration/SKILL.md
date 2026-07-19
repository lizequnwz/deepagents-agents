---
name: schema-exploration
description: Ground questions in the selected OSI semantic model, with backend-neutral live schema inspection only as fallback.
---

# Schema Exploration

1. Always read the exact OSI path identified by the runtime system prompt
   before using database introspection. Use a read limit of at least 1000 lines.
2. Locate relevant datasets, physical sources, fields, relationships, metrics,
   AI instructions, and synonyms in that file.
3. Use `list_tables` or `get_table_schema` only to resolve a concrete gap or
   verify drift between the semantic model and the database.
4. Never probe the database with exploratory SQL when the semantic model
   already answers the question.

When explaining schema, distinguish physical source/expression names from
logical OSI dataset and field names. Use only declared relationship paths and
honor source-specific AI instructions.
