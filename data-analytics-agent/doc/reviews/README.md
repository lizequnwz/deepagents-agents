# Reviews and evidence

Updated 1 October 2026. Use the current guides for behavior and the
[handoff](../../HANDOFF.md) for next work. Reviews are dated snapshots; they do not
supersede the [capability status](../roadmap/implementation-progress.md).

## Latest records

| Date | Record | How to use it |
|---|---|---|
| 1 October 2026 | [SQL export files](sql-export-2026-10-01.md) | Exact `.sql` files, snapshot/lineage index, query selection and export/replay regressions |
| 1 October 2026 | [Business usability](business-usability-2026-10-01.md) | Guided workbook/file review, confirmed population details, deferred downloads and deliberate optional reviews; automated interaction checks and their limits |
| 1 October 2026 | [Ablation outcome and batch review](ablation-outcomes-2026-10-01.md) | Rejected prompt candidate, preserved early-terminated live study, shared approval repair and independently recomputed live workflow; remaining ablation gates stay open |
| 30 September 2026 | [Ablation readiness](ablation-readiness-2026-09-30.md) | Frozen synthetic inputs, receipt/grading repairs and paired gates; prepared prompt candidate, without live adoption claims |
| 30 September 2026 | [Release verification](release-verification-2026-09-30.md) | Delivered cleanup, Excel, bundle/notebook exports; deterministic/browser/replay checks and limits |
| 29 September 2026 | [Capability and usability review](capability-review-2026-09-29.md) | Pre-release investigation and primary comparison sources; its delivery order is superseded by the handoff |

Supporting evidence: [29 September check record](capability-review-evidence-2026-09-29.json),
[Excel browser check](excel-browser-2026-09-30.jpg),
[download browser check](export-browser-2026-09-30.jpg), and the
[portable synthetic example](../examples/README.md).

## Historical assessments

The [14 September reading copy](data-plugin-standalone-review-2026-09-14.html)
remains as historical material. Superseded review sources and screenshots were
removed during cleanup; there is no archive directory in this checkout. Do not
treat that reading copy as current implementation guidance or available receipts
for its historical live claims.

References to unavailable September smoke/documentation/delivery reviews were
removed from current indexes. Their reported live outcomes remain unverified;
no missing or skipped evidence is counted as a pass. Existing implementation checks
are recorded separately in release verification. No paired behavioral ablation or
competitive model-accuracy benchmark has been completed.

## Adding evidence

Record the revision, exact inputs/configuration, independent checks, failures and
limitations. Distinguish deterministic/scripted execution, live-model accuracy and
browser usability evidence. Keep bulky artifacts only when they explain a finding.
Archive superseded narratives with useful receipts; remove redundant completed plans.
