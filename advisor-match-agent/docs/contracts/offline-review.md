# Offline workbook review

Matching ends after the verified `advisor_matches.xlsx` response is built. The
application does not paginate review records, apply row-level decisions, resolve
manual CRD proposals, approve a workflow, or re-ingest downloaded edits.

`Review Required` is the post-match review surface. It contains one row per
presented candidate, or one No Match row without a candidate. Each row keeps the
source row number, input identity, candidate identity, qualitative evidence,
warnings, and hidden audit fields. Three blank highlighted fields support local
work:

- `User Decision`
- `Selected CRD`
- `Reviewer Notes`

These fields are intentionally free-form. Independently researched CRDs and
other corrections remain the reviewer's responsibility. Correct source data by
uploading a new CSV/XLSX and running matching again.

The only input augmentation is one explicitly supplied firm applied to all
copied mapped rows. It is audited in `result.json` and `Run Summary`; source
bytes and `Original Input` are unchanged.
