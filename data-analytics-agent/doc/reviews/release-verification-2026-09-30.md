# Cleanup, Excel and portable analysis verification

30 September 2026. Implemented in the local working tree; no deployment or commit performed.

## Delivered

- Removed unused `AGENT_DEBUG_DETAILS`/manager argument and the inactive full-input validation branch. Enforced output limits remain. Python review now resolves and displays every named input with its saved provenance; obsolete single-input fields and `df` wording are removed.
- Added `.xlsx` composer attachments, workbook inspection, explicit worksheet/header/table-range selection, then existing full-population schema/key review. Original bytes/hash, range and formula-cache acceptance persist. Native dates, text identifiers and simple zero-padded formats survive; mixed types retain text with warnings. Merged cells within the selected table, invalid headers, errors, missing formula caches and oversized data produce explicit errors. Selected blank/subtotal/footer rows are retained.
- Added **Download analysis** for completed reported turns. Its ZIP contains complete supporting typed snapshots and selected outputs, exact successful Python steps and necessary producers from earlier turns, saved figures, dependencies, lineage/hashes, SQL provenance, chart definitions, report specification and exact current HTML. Failed attempts and unrelated evidence are excluded from executable replay.
- Added `analysis.ipynb` through the same export preparation. It includes narrative, explicit inputs, exact editable step files and saved scalar/table/figure outputs. Replay uses the same standalone worker as the script, with a fresh local process for every step. Saved notebook edits do not invalidate immutable evidence checks.
- New Python executions record imported package/Python versions. Old executions without these records are explicitly uncertified. SQL is a saved snapshot boundary, not a warehouse refresh or SQL transformation replay.
- Updated current guides and marked missing historical review receipts unavailable. API contract is 16; there are no migrations or compatibility paths. Use fresh application storage when upgrading older contracts and preserve needed artifacts separately.

Local execution remains the existing process runner. No dedicated sandbox infrastructure, Bash agent tool, live notebook editor, persistent kernel, new agent or ingestion service was added. Excel uses read-only `openpyxl` for cell types, formatting and formula-cache inspection, then the existing Arrow/Parquet path; a second pandas ingestion path would duplicate conversion/review logic. Notebook construction uses `nbformat`, with `nbclient` for verification.

## Verification

- Complete regression suite: **342 passed, 6 skipped**, across 348 collected cases. The skipped cases are opt-in provider tests. No live provider calls or paid competitor tests were made.
- Fresh Jupyter kernel execution requires temporary loopback ports, so the complete suite ran with elevated tool permissions. The restricted tool environment's initial notebook failure was a local port restriction; the same check passed outside that restriction.
- Final reporting/Excel/Python/upload regression checks after the scope-display cleanup: **35 passed**. Ruff undefined/unused-name checks and whitespace checks passed.
- Synthetic checks cover workbook selection, dates, leading zeros, formula caches, headers, merged titles outside the table, invalid keys, limits, immutable review/reopen, real agent harness with a scripted model, report generation and ZIP download.
- Replay checks cover SQL-only and partial/incomplete exports, multiple named inputs, derived-data chains, producers reused from earlier turns, failure exclusion, unrelated-evidence exclusion, current report revisions, dependency records, hashes, decimal/date/identifier retention and diagnostic images. Output datasets and scalar/table diagnostics use declared numerical tolerance (`rtol=1e-7`, `atol=1e-10`); figure pixel equality is not asserted.
- Notebooks validate and execute from a fresh kernel in a moved extraction directory. Saving the executed notebook and rerunning in another fresh kernel also passes. Original script step semantics prevent variable state from leaking between executions.
- Browser walkthrough on a temporary synthetic local preview: attach `.xlsx` → send → select `Sales!A2:C4` → schema preview showing `00007`, `00008` and two rows → confirm → usable conversation. Reopened a completed analytical turn and used **Download analysis** to obtain the ZIP. The downloaded package had 18 files, four typed datasets, two Python steps and the notebook; it replayed from another directory.

Screenshots: [confirmed Excel conversation](excel-browser-2026-09-30.jpg), [analysis download control](export-browser-2026-09-30.jpg). The [downloadable example](../examples/README.md) uses synthetic data.

## Limits

Excel contributes one selected `.xlsx` table per conversation. No workbook editing/recalculation, multiple-sheet/file joins or additional workbook formats are included. Cached formula freshness and source completeness remain unknown unless explicitly established.

Exports reproduce selected Python over saved snapshots; they do not regenerate published interpretations or business charts, which remain in the self-contained HTML report with exported chart definitions. Custom code depending on external paths/services or dynamic imports may need manual environment setup. Randomized code requires its original seeds to reproduce results. Successful execution does not establish analytical correctness.

Historical live-trial claims whose detailed receipts are absent are unverified in this checkout. Current checks are synthetic/scripted where an agent is used; model quality and larger behavior-changing ablations remain separate work.
