---
name: schema-exploration
description: Ground a database question in the selected OSI semantic model and resolve logical-to-physical names, metrics, joins, synonyms, and source instructions. Use before query writing; use live schema tools only for a concrete missing detail or suspected drift.
---

# Schema Exploration

1. Read the exact OSI path from the runtime prompt with `limit=1000`.
2. Identify the relevant logical datasets and fields, their exact physical
   sources or expressions, declared relationships, metric definitions,
   synonyms, and AI instructions.
3. Resolve the requested business grain and note only material ambiguity that
   changes the query or answer.
4. Stop when the OSI model provides enough information to write the query.
5. Use `list_tables` or `get_table_schema` only to fill a named gap or verify
   suspected drift. These tools inspect metadata; do not use SQL to probe row
   values for schema discovery.

When explaining schema, distinguish physical source/expression names from
logical OSI dataset and field names. Use only declared relationship paths and
honor source-specific AI instructions.
