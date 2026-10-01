# Handoff: next analytics release

Updated 1 October 2026. Start here for the next implementation session.
The [capability status](doc/roadmap/implementation-progress.md) describes what
exists; the [roadmap](doc/roadmap/roadmap.md) gives feature acceptance gates; the
[ablation plan](doc/roadmap/simplification-and-ablation.md) governs behavioral
simplifications. Keep these roles separate rather than adding another review.

## Where the product stands

The local business analyst supports one configured warehouse or one reviewed
CSV/Parquet/Excel table per conversation. SQL owns source execution; iterative
Python consumes named saved datasets and produces typed datasets and diagnostic
figures. Findings, charts and the required HTML report share durable evidence.
Approvals, corrections, Stop/Resume, restart recovery and report retry remain
part of the product.

The latest implementation added:

- `.xlsx` worksheet/range selection followed by the existing schema/key review.
  Identifiers, dates, formula-cache choices, warnings and original-file provenance
  persist. One selected table is supported; workbook editing and joins are not.
- **Download analysis**: selected report/evidence, typed snapshots, exact successful
  Python steps and necessary producers, exact SQL query files linked to their
  saved snapshots, SQL provenance, versions and hashes.
- An editable `analysis.ipynb` with stored outputs in the same bundle. Script and
  notebook replay preserve a fresh local process per analytical step. SQL remains
  a saved snapshot boundary; replay does not refresh a warehouse or rewrite findings.
- Removal of the no-op debug setting and dead validation branch, plus exact
  all-input Python review. Existing enforcement limits remain.
- Complete ordered review of native multi-action interrupts, with per-proposal
  edits/rejections, stale-review checks and one common review view. Unused review state
  and the duplicated review forms are removed.
- Guided workbook rows/columns with a live population count, column notes first
  in file review, a plain-language confirmed-data summary, and analysis ZIPs
  prepared on click. Optional review requires deliberate decisions and validates
  feedback beside each proposal. SQL/Python review remains off by default.

Checked same-snapshot KPI comparisons, direct chart/report presentation edits,
compact application-owned receipts, lexical semantic retrieval, voice drafts,
visible plans and bounded independent analysis assignments were already delivered.
Do not rebuild them under a new name.

[Release verification](doc/reviews/release-verification-2026-09-30.md) records
342 passing tests and six skipped provider tests, fresh-kernel notebook replay,
browser Excel intake/download, and the limits of those checks. The
[portable example](doc/examples/README.md) contains synthetic data. These are
local deterministic/scripted checks, not a live-model quality benchmark.
Older live-trial claims without receipts are unverified.

The [1 October ablation outcome](doc/reviews/ablation-outcomes-2026-10-01.md)
records a rejected prompt candidate, 138 preserved live runs in an early-ended
study, and a successful live batch-review repair smoke with independently checked
complete populations. The mixed corpus is not fully graded and has no performance
adoption claim.
Final review/comparator verification passed **376 tests**, with six opt-in provider
tests skipped. The live smoke includes operator edits and is not an unassisted
accuracy benchmark.

The subsequent [business usability verification](doc/reviews/business-usability-2026-10-01.md)
passed **378 tests**, with six opt-in provider tests skipped. It exercises the
guided file setup, preserved edits after validation errors, optional review
readiness and deferred revision-bound downloads through native widgets and the
real API. This revision has no new browser or business-user study.

The [SQL export follow-up](doc/reviews/sql-export-2026-10-01.md) adds exact query
files and links them to their saved snapshots. Its focused export, workbook and
presentation suite passed **27 tests**, including notebook replay.

The work is in the local working tree; it has not been committed or deployed.
Preserve it when continuing. API contract is **17**: restart both services together
and use fresh storage for older incompatible records, preserving needed artifacts
separately. Do not add migrations or compatibility readers.

## Product constraints

Favor capability and usability over infrastructure. Keep FastAPI, Streamlit,
existing typed evidence, and the local Python runner. **Dedicated execution
isolation is deferred by the user.** Do not make it a prerequisite for the next
features. Local subprocess execution does not enforce filesystem/network isolation.

No Bash agent tool, live notebook editor, persistent IPython kernel, new agents,
general workflow engine or vector database is planned. Python already executes
real code; portable notebook export is delivered. Add further coding facilities
only for observed workflows that the current runner cannot serve well.

Preserve one source/file per conversation, mandatory upload review, SQL-only
warehouse access, full-population checks, declared units, honest source completeness,
immutable revisions and mandatory evidence-backed HTML. A chart sample is not an
analytical population. A query timestamp is not a source cutoff. Agent-authored
report composition remains a requirement.

## Next implementation sequence

1. **Broaden outcome evidence and identify the largest usability friction.**
   Extend the existing corpus/grader with independent checks for file/Excel
   questions, multiple inputs, forecast leakage/baselines, nullable decisions,
   reconciliation and report agreement. Use existing runners, not a new evaluation
   platform. Observe whether users can identify scope, understand review warnings,
   refine a result, and replay the download. Record task success and repairs.
2. **Add one explicit saved-dataset follow-up.** Let a user choose a named saved
   dataset and ask, for example, “For these saved sales, compare the West region.”
   Show the dataset and population supplied to the follow-up; verify that its grain
   can answer the request. Reuse complete evidence where sufficient, otherwise
   explain the needed source retrieval. Deliver this end to end before linked
   chart selections or a shared-filter workspace.
3. **Make forecast evaluation inspectable.** Use saved evaluation tables and a
   small report/chart descriptor for training/holdout boundaries, actuals,
   candidate/baseline errors, forecast start and interval meaning. Recompute scores;
   test temporal leakage, short/noisy series and structural breaks. Preserve the
   existing Python tool and renderer; do not build an algorithm registry.
4. **Extend scope controls only after explicit follow-ups work.** Apply one shared
   scope consistently to metrics, charts, tables and exports. Then add manual
   warehouse refresh as a new analytical run/revision, retaining the last successful
   view on failure. Under current policy a file refresh is a new upload/conversation.

Usability evidence can reprioritize this sequence. Keep every increment usable
before starting the next. See the [roadmap](doc/roadmap/roadmap.md) for completion
criteria and existing implementation boundaries.

## Simplifications to investigate

The [ablation execution guide](doc/roadmap/ablation-execution.md) supplies the first
predeclared study and its rejected prompt-ownership patch. The serving-runtime
fingerprints, 25-case synthetic corpus, failure-preserving runner, complete grader
and paired comparator are implemented. The candidate lost a unique structured
terminal-response instruction and failed all three metadata repetitions. Keep the
baseline instructions. Any narrower candidate needs a fresh frozen study; use the
repaired batch-review implementation in both variants. The comparator suppresses
aggregate performance for incomplete, failing or unreviewed outcome pairs.

Start with prompt ownership and redundant metadata lookup, then measure serial
versus bounded parallel analysis. Consider a single file-only SQL/Python analyst
only if handoff latency is material; warehouse ownership stays unchanged. Remove
feature-disable variants only after establishing that no supported deployment
uses them. Measure chart/report argument repairs before changing schemas.

There is **no completed paired ablation** establishing that a specialist,
planning persistence, parallelism or report composition can be removed. Run one
change at a time on identical frozen inputs/configuration, using held-out cases
and repeated trials. Check correctness, clarification, approvals, interruption,
recovery and report/export agreement alongside calls, latency and cost. Keep failure
receipts. Adopt a simplification only after its declared gate passes, then remove
its obsolete path rather than retain runtime variants. Detailed experiments and
provisional adoption thresholds are in the
[ablation plan](doc/roadmap/simplification-and-ablation.md).

## Demand-led follow-ons

- Validate the delivered guided file review with business users; explicit
  confirmation and all-column/full-population checks remain. Add `.tsv`, flat JSON/JSONL, other workbook formats or Excel result
  export only when requested workflows justify them; reuse ingestion/export paths.
- Add bounded inspection of registered diagnostic images if visual reasoning is
  needed. Currently the analyst receives image receipts, not the image pixels.
- Add focused cohort, retention, funnel or driver-analysis examples and outcome
  checks before introducing method-specific agents. Separate arithmetic/association
  from causal claims.
- Extend metric definitions and cross-snapshot comparison proof deliberately.
  Existing comparison checks do not establish join correctness or source freshness.
- Evaluate hybrid semantic retrieval only after demonstrating misses in the current
  lexical index, at equal context budgets and with downstream result grading.

Multiple-file/sheet joins, warehouse/file enrichment, document research, automatic
cross-conversation learning, scheduling and hosted collaboration remain product
scope decisions. Scheduling depends on validated refresh. Do not introduce these
through an implicit relaxation of existing boundaries.

## Verification for the next session

Use [testing](doc/development/testing.md) and temporary storage. Run appropriate
deterministic regressions and browser checks for changed flows; check moved bundle
replay when changing evidence/export contracts. Record exact inputs, model/version,
code/instruction fingerprints, independent grading and limitations. Do not count
report completion, successful code execution or skipped provider tests as accuracy.

Live provider evaluation requires authorization covering the fixture contents and
configured provider. Historical authorization is not a blanket authorization for
new data or providers. Preparation and deterministic checks can proceed independently.
Update current guides and a compact dated verification record after delivery;
keep useful dated reviews with their actual receipts; remove obsolete indexes
instead of linking to absent archives.
