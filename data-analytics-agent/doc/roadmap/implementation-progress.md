# Current capability status

Updated 1 October 2026. This is the current delivery inventory. Start with the
[handoff](../../HANDOFF.md) for implementation order and the
[roadmap](roadmap.md) for acceptance gates. Dated reviews describe earlier versions.

## Delivered

| Capability | Current behavior and boundary |
|---|---|
| Local onboarding | One locked install/start path; upload entry does not require a warehouse; advanced settings documented separately |
| Source grounding | One configured SQLite/Snowflake source or reviewed file per conversation; curated warehouse semantics; shared cached lexical discovery/browsing |
| File intake | CSV, Parquet and one selected `.xlsx` worksheet table; guided range selection with population counts, columns with notes first, explicit all-column review and confirmed-data summary; original hashes, immutable typed snapshots and warnings |
| SQL and Python | SQL-only warehouse execution; saved-data SQL reshaping; iterative Python with named inputs, fresh processes, saved derived datasets and diagnostic PNGs |
| Evidence and reports | Application-owned receipts, scoped findings, shared versioned charts, required agent-composed HTML, numerical bindings and report retry |
| Comparisons | Same-snapshot current/baseline bindings, deterministic deltas and calculation disclosure; checks for grain, dimensions, periods, units and completeness |
| Presentation | Direct chart styling and exact report-title revisions over saved evidence; immutable revisions, stale-write protection and failure recovery |
| Analytical visibility | Visible plans, compact investigation records, bounded independent Python assignments, ordered batch review, exact all-input review and code inspection |
| Run recovery | Durable conversations/checkpoints, approvals/corrections, Stop/Resume and history deletion; blocking source cancellation remains cooperative |
| Voice | Record → transcribe → edit composer draft; no automatic question submission |
| Portable work | Selected report/data/code ZIP prepared on click with native loading feedback, provenance, versions and hashes; editable notebook with stored outputs; script/notebook replay over saved snapshots |
| Evaluation tooling | Documented/held-out and synthetic ablation corpora; serving-runtime fingerprints; failure-preserving receipts; independent grading and paired adoption gates; opt-in provider tests |

The latest cleanup removed the unused debug-details setting and inactive validation
branch. Enforced data/output limits remain. Python review shows every named input.
Native multi-action review now preserves every proposal, exact per-action decisions
and checkpoint recovery; stale submissions are rejected. Duplicate review forms
and unused review-type state are removed. API contract is **17**, with no migrations
or compatibility readers. Older
incompatible storage requires a fresh directory; restart both services together.

The [business usability pass](../reviews/business-usability-2026-10-01.md) retains
contract 17 and automatic SQL/Python execution by default. Optional review now
requires explicit decisions, validates feedback beside each proposal and
preserves independent edits. Verification passed **378 tests**, with six opt-in
provider tests skipped; native-widget/API checks are distinct from browser or
business-user evidence.

## Evidence and limits

[30 September release verification](../reviews/release-verification-2026-09-30.md)
records **342 passed, six skipped**, focused regression checks, browser workbook
review/download, and script/fresh-kernel notebook replay. The
[example bundle](../examples/README.md) is synthetic and usable outside the app.

These checks verify implementation behavior; they do not establish broad live-model
analytical accuracy or comparative superiority. Historical live results whose
receipts are absent are unverified. The
[29 September review](../reviews/capability-review-2026-09-29.md) preserves the
pre-release assessment and comparison sources; dated historical material is not
current delivery guidance.

[Ablation outcomes](../reviews/ablation-outcomes-2026-10-01.md) record the rejected
prompt candidate, the early-terminated 138-run study and the batch-review repair.
The new live reviewed workflow completed and its complete downloads independently
recomputed; it is not first-attempt model accuracy or a completed mixed-corpus
ablation. Later behavioral studies remain open. See the
[execution guide](ablation-execution.md).
The final suite for the review/comparator repair passed **376 tests**, with six
opt-in provider tests skipped.

## Open

- Broader independently graded statistical/business outcomes and usability studies.
- Explicit dataset follow-ups, shared filters and manual warehouse refresh.
- Inspectable forecast holdouts/baselines, multi-series charts and forecast-start markers.
- Cross-snapshot comparison scope proof, explicit source cutoffs and general derived
  metric semantics. Current checks cannot certify arbitrary source joins.
- A narrower prompt study and paired routing, parallelism and file-only specialist ablations.
- Demand-led file/output formats and bounded visual diagnostic inspection.

Dedicated execution isolation is deferred by the user; local processes are retained.
No Bash tool, app notebook editor/persistent kernel, workbook recalculation,
multi-file/sheet joins or mixed-source analysis is included. See the
[ablation plan](simplification-and-ablation.md) before removing behavioral components.
