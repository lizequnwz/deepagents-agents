# SQL files in analysis downloads

1 October 2026. Analysis ZIP downloads now include one exact executed query per
supporting SQL result under `sql/query-001.sql`, `sql/query-002.sql`, and so on.
The package README links the files and identifies source versus saved-data
queries. `sql-provenance.json` maps each file to its result ID, Parquet snapshot,
purpose label, original question and input result IDs. File hashes are recorded
in the manifest.

Selection follows the existing exported evidence lineage, including reused
results from earlier turns. Chart copies of query text and unrelated queries
are excluded. Comments, Unicode, whitespace and reviewed edits are preserved
exactly. Evidence without SQL produces an empty index and an explicit README
note. Python replay continues to use saved snapshots; no SQL/source or model
execution occurs during export.

Verification: **27 passed** across `tests/test_exports.py`, `tests/test_excel.py`
and `tests/test_presentation_edits.py`, in 64.14 seconds, including fresh-kernel
notebook replay. New/extended tests verify exact UTF-8 SQL bytes, hashes, README
links, reused source/saved-query lineage, snapshot mappings, exclusion of chart
copies/unrelated results and query-free Python exports. Static checks and
`git diff --check` passed. No provider evaluation was run for this change.

API/storage contract remains **17**. Existing source, approval and execution
settings are unchanged. Earlier downloaded ZIPs need to be downloaded again to
receive the new SQL files.
