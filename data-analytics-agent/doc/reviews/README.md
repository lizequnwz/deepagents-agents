# Reviews and evidence

Updated 3 October 2026. Use the current guides for behavior and the
[handoff](../../HANDOFF.md) for next work. Reviews are dated snapshots; they do not
supersede the [capability status](../roadmap/implementation-progress.md).

## Latest records

| Date | Record | How to use it |
|---|---|---|
| 3 October 2026 | [Agent review and improvement options](agent-review-2026-10-03.md) | Code-backed gaps, local checks and primary research; the handoff supersedes its earlier product priorities |
| 2 October 2026 | [Extended priority testing](priority-followup-tests-2026-10-02.md) | Scope/refresh/calendar/forecast/lineage/source-recovery repairs, retained failures, local discovery observations and next improvement opportunities |
| 1 October 2026 | [Priority analytics releases](priority-releases-2026-10-01.md) | Semantic study tooling, explicit saved inputs, forecast evaluation, shared scope and manual refresh; local/browser/replay checks and remaining live/user gates |
| 1 October 2026 | [Ablation outcome and batch review](ablation-outcomes-2026-10-01.md) | Rejected prompt candidate, preserved early-terminated live study, shared approval repair and independently recomputed live workflow; remaining ablation gates stay open |

Supporting evidence remains linked from each retained record. The
[portable synthetic example](../examples/README.md) remains usable outside the app.

## Earlier implementation checks

Three completed release reviews were consolidated here on 3 October. Current
behavior is documented in the [user guide](../user/using-the-agent.md) and
[architecture](../development/architecture.md). These are historical results;
none was rerun during consolidation, and no provider skip is counted as a pass.

| Date and increment | Historical checks | Evidence and limits |
|---|---|---|
| 30 September: Excel and portable analysis | 342 full-suite passes, six provider skips; 35 final focused checks | Synthetic/scripted checks; browser Excel attachment and confirmation of `Sales!A2:C4` preserved two text identifiers with leading zeros; browser ZIP download replayed from another directory; moved script and fresh-kernel notebook replay passed. These do not establish model accuracy. |
| 1 October: business usability | 378 full-suite passes, six provider skips | Native-widget/API checks covered guided workbook selection, full-column review, preserved edits, exact ordered approvals and deferred downloads. No separate browser layout/responsive test or business-user study was performed. |
| 1 October: exact SQL export files | 27 focused passes | Export/Excel/presentation checks covered exact UTF-8 SQL bytes, hashes, source/saved-query lineage, excluded unrelated queries and fresh-kernel replay. No provider evaluation was run. |

Those increments recorded API contracts 16 and 17. The current contract is 19;
older records do not supply current startup instructions. Replay numerical
tolerances and limits remain in the [testing guide](../development/testing.md#portable-replay).

## Historical assessments

The 3 October cleanup removed the 14 September generated review, the 29 September
assessment and its check record, the superseded ablation-readiness review, four
redundant screenshots and two filesystem metadata files. The
[cleanup record](agent-review-2026-10-03.md#documentation-cleanup) explains what was
retained. Current guides, compact failure receipts, active study protocols and
the tested rejected candidate remain. There is no archive directory in this
checkout.

A second pass removed the three completed release narratives above and the
duplicate `roadmap.md` and `simplification-and-ablation.md` plans. The handoff now
owns the active analytics workspace direction. The useful evaluation instructions
were moved to [development](../development/ablation-evaluation.md). Study JSON and
the rejected patch remain at their existing paths because they support evaluation
and tests. Unique failed-study and recent regression receipts remain intact.

References to unavailable September smoke/documentation/delivery reviews were
removed from current indexes. Their reported live outcomes remain unverified;
no missing or skipped evidence is counted as a pass. Existing implementation checks
are recorded in retained verification records and the historical checks above.
No paired behavioral ablation or
competitive model-accuracy benchmark has been completed.

## Adding evidence

Record the revision, exact inputs/configuration, independent checks, failures and
limitations. Distinguish deterministic/scripted execution, live-model accuracy and
browser usability evidence. Keep bulky artifacts only when they explain a finding.
Keep useful compact receipts; remove superseded narratives and redundant completed
plans once current guides and outcome records cover them.
