# Reviews and evidence

This area contains dated assessments and the receipts used to support them.
They preserve project history and should be read as snapshots, not as current
implementation instructions.

Return to the [documentation index](../README.md) for current guides, or check
[implementation progress](../roadmap/implementation-progress.md) for delivery status.

## Assessments and test records

| Date | Document | Scope |
|---|---|---|
| 21 September 2026 | [Semantic discovery review](semantic-discovery-review-2026-09-21.md) | Reproduced semantic retrieval gaps, bounded context design, and prioritized engineering improvements |
| 20 September 2026 | [Artifact handoff review](artifact-handoff-review-2026-09-20.md) | Confirmed chart-ID failure and records the fixes delivered on 21 September |
| 20 September 2026 | [Live smoke tests and retry repairs](live-smoke-2026-09-20.md) | This application's configured-provider trials, browser checks, repairs, and follow-up verification |
| 14 September 2026 | [Data plugin comparative review](data-plugin-comparative-review-2026-09-14.md) | Historical comparison of this project with Data plugin 1.0.8 |
| 14 September 2026 | [Standalone Data plugin review](data-plugin-standalone-review-2026-09-14.md) | Detailed assessment of Data plugin 1.0.8 |
| 10 September 2026 | [Architecture and product review](design-review-2026-09-10.md) | Earlier assessment of this project's architecture and product direction |

## Reading copies and supporting evidence

- [Standalone review HTML](data-plugin-standalone-review-2026-09-14.html) —
  reading copy of the standalone plugin review.
- [Standalone review evidence](data-plugin-review-evidence/README.md) — test logs,
  screenshots, source hashes, and validation receipts, with reproduction notes.

## Rebuild reading copies

The standalone review HTML is generated from its Markdown source with:

```sh
node doc/reviews/data-plugin-review-evidence/build-report.mjs
```
