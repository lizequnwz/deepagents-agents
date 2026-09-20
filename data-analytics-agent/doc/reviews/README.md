# Reviews and evidence

This area contains dated assessments and the receipts used to support them.
They preserve project history and should be read as snapshots, not as current
implementation instructions.

Return to the [documentation index](../README.md) for current guides, or check
[implementation progress](../roadmap/implementation-progress.md) for delivery status.

## Assessments and test records

| Date | Document | Scope |
|---|---|---|
| 20 September 2026 | [Live smoke tests and retry repairs](live-smoke-2026-09-20.md) | This application's configured-provider trials, browser checks, repairs, and follow-up verification |
| 14 September 2026 | [Data plugin comparative review](data-plugin-comparative-review-2026-09-14.md) | Comparison of this project with the installed Data plugin |
| 14 September 2026 | [Standalone Data plugin review](data-plugin-standalone-review-2026-09-14.md) | Detailed assessment of the installed plugin itself |
| 10 September 2026 | [Architecture and product review](design-review-2026-09-10.md) | Earlier assessment of this project's architecture and product direction |

## Reading copies and supporting evidence

- [Combined review packet](review-packet.html) — architecture/product review and
  comparative review in one self-contained HTML file.
- [Standalone review HTML](data-plugin-standalone-review-2026-09-14.html) —
  reading copy of the standalone plugin review.
- [Standalone review evidence](data-plugin-review-evidence/README.md) — test logs,
  screenshots, source hashes, and validation receipts, with reproduction notes.

## Rebuild reading copies

The standalone review HTML is generated from its Markdown source with:

```sh
node doc/reviews/data-plugin-review-evidence/build-report.mjs
```

The combined packet is generated with:

```sh
python3 scripts/build_review_packet.py
```
