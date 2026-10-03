# Current capability status

Updated 3 October 2026. This is the current delivery inventory. The
[handoff](../../HANDOFF.md) owns the selected analytics workspace direction,
priorities and acceptance gates. That broader direction is not implemented yet;
the boundaries below describe the current product. Dated reviews describe earlier
versions.

## Delivered

| Capability | Current behavior and boundary |
|---|---|
| Local onboarding | One locked install/start path; upload entry does not require a warehouse; advanced settings documented separately |
| Source grounding | One configured SQLite/Snowflake source or reviewed file per conversation; curated warehouse semantics; shared cached lexical discovery/browsing |
| Semantic reliability | Batched unresolved role candidates; SQL-only exact physical relationship key pairs; structured actionable join/metric/fan-out validation feedback; specialist-owned coverage |
| File intake | CSV, Parquet and one selected `.xlsx` worksheet table; guided range selection with population counts, columns with notes first, explicit all-column review and confirmed-data summary; original hashes, immutable typed snapshots and warnings |
| SQL and Python | SQL-only warehouse execution; saved-data SQL reshaping; iterative Python with named inputs, fresh processes, saved derived datasets and diagnostic PNGs |
| Evidence and reports | Application-owned receipts, scoped findings, shared versioned charts, required agent-composed HTML, numerical bindings and report retry |
| Comparisons | Same-snapshot current/baseline bindings, deterministic deltas and calculation disclosure; checks for grain, dimensions, periods, units and completeness |
| Presentation | Direct chart styling and exact report-title revisions over saved evidence; immutable revisions, stale-write protection and failure recovery |
| Analytical visibility | Visible plans, compact investigation records, bounded independent Python assignments, ordered batch review, exact all-input review and code inspection |
| Run recovery | Durable conversations/checkpoints, approvals/corrections, Stop/Resume and history deletion; blocking source cancellation remains cooperative |
| Explicit saved inputs | Native dataset selector with population, completeness and known scope; complete SQL/upload/Python datasets; authoritative exact references in requests, specialist briefs, history, reports and downloads; explicit source-expansion clarification |
| Shared population | Categories and typed date ranges over one complete saved dataset; immutable scoped input and analytical turn; stale-write guards; exact SQL input aliases preserve supported aggregate periods through CTEs and saved dependencies; unrepresentable applied filters block form submission |
| Forecast evaluation | Named predictions and independently recomputed finite scores; training/holdout/origin/horizon/frequency/baseline/sample size; measured versus nominal coverage; anchored weekly calendar and distinct interval bindings; forecast-specific band/start marker and portable replay |
| Manual refresh | Warehouse-only source-backed run, equivalent typed input with reapplied scope and linked immutable report; typed empty/removed-category populations remain usable; exact unchanged follow-up input reuse; prior view survives failure and saved history remains readable without a valid source configuration; file refresh requires a new upload/conversation |
| Voice | Record → transcribe → edit composer draft; no automatic question submission |
| Portable work | Selected report/data/code ZIP prepared on click with native loading feedback, exact SQL files linked to saved snapshots, provenance, versions and hashes; editable notebook with stored outputs; script/notebook replay over saved snapshots |
| Evaluation tooling | 40-case synthetic corpus with 20 timed semantic cases over small/large catalogs; role/grain/clarification expectations; all complete SQL snapshots retained; independent scalar checks and first-correct timing; separate routing/batching/join protocols and strict paired gates; opt-in provider tests |

The latest cleanup removed the unused debug-details setting and inactive validation
branch. Enforced data/output limits remain. Python review shows every named input.
Native multi-action review now preserves every proposal, exact per-action decisions
and checkpoint recovery; stale submissions are rejected. Duplicate review forms
and unused review-type state are removed. API contract is **19**, with no migrations
or compatibility readers. Older
incompatible storage requires a fresh directory; restart both services together.

SQL/Python execution remains automatic by default. Optional review requires
explicit decisions, validates feedback beside each proposal and preserves
independent edits. Earlier usability and export checks are retained in the
[historical record](../reviews/README.md#earlier-implementation-checks).

## Evidence and limits

[Extended priority verification](../reviews/priority-followup-tests-2026-10-02.md)
records **490 passed, six skipped** and **108 focused passes**, with retained
before/after failures. It covers calendar/type/empty-population/forecast/error
boundaries, source configuration recovery, native scope submission guards and
portable replay. The local discovery probe finds expected roles with dataset
hints, reduces batch response size about 52%, and exposes broad date browsing's
need for narrowing in the competing catalog. Its warmed timings do not establish
live SQL performance. A 25-node shared-lineage check fell from 12,286 lookups to 25.

[Priority verification](../reviews/priority-releases-2026-10-01.md) records
**423 passed, six skipped**, native-widget/API/browser population checks,
clarification/Stop/Resume/restart binding checks, successful and failed local
source refresh, and moved forecast bundle/fresh-kernel notebook replay. New bundles
use format 2. The current instruction is to keep verification local: no new live
provider accuracy or speed claim is made.

[Historical implementation checks](../reviews/README.md#earlier-implementation-checks)
retain the completed Excel, usability and SQL-export outcomes and their limits. The
[example bundle](../examples/README.md) is synthetic and usable outside the app.

These checks verify implementation behavior; they do not establish broad live-model
analytical accuracy or comparative superiority. Historical live results whose
receipts are absent are unverified. The superseded 29 September review was removed
during the 3 October documentation cleanup. The
[current capability review](../reviews/agent-review-2026-10-03.md) assesses the
present implementation and proposes improvements; it does not change delivery
status or satisfy pending accuracy gates.

[Ablation outcomes](../reviews/ablation-outcomes-2026-10-01.md) record the rejected
prompt candidate, the early-terminated 138-run study and the batch-review repair.
The 1 October operator-reviewed live workflow completed and its downloads independently
recomputed; it is not first-attempt model accuracy or a completed mixed-corpus
ablation. Later behavioral studies remain open. See the
[evaluation guide](../development/ablation-evaluation.md).
The final suite for the review/comparator repair passed **376 tests**, with six
opt-in provider tests skipped.

## Open

- Broader independently graded statistical/business outcomes and usability studies.
- Three separately isolated, complete live semantic paired studies and independently
  reviewed targeted failures; speed adoption still needs at least 15% improvement.
- Live specialist suitability/leakage assessment and business-user scope recognition;
  arbitrary saved grain and Python fitting code cannot be certified by structural checks.
- Cross-snapshot comparison scope proof, explicit source cutoffs and general derived
  metric semantics. Current checks cannot certify arbitrary source joins.
- Held-out competing date/metric meanings without dataset hints, and user recognition
  of changed or empty scopes; add explicit calendar/grain preparation as workflows
  require it.
- A narrower prompt study and paired routing, parallelism and file-only specialist ablations.
- Demand-led file/output formats and bounded visual diagnostic inspection.

Dedicated execution isolation is deferred by the user; local processes are retained.
No Bash tool, app notebook editor/persistent kernel, workbook recalculation,
multi-file/sheet joins or mixed-source analysis is included. See the
[handoff](../../HANDOFF.md) and [evaluation guide](../development/ablation-evaluation.md)
before changing behavioral components. Earlier restrictions on workspace tools and
conversation-wide source binding remain current runtime limits, not permanent
requirements for the selected next version.
