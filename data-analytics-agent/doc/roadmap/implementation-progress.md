# Roadmap implementation progress

Updated 27 September 2026. This is a dated implementation record; the roadmap and ablation
documents retain their review-time recommendations. Delivery follows the
simplification plan's initial setup and presentation increments, with the
independent forecast-label correction from the product roadmap, followed by
isolated tabular uploads.

## Delivered

1. **Focused onboarding.** `.env.example` exposes credentials, model selection,
   independent SQL/Python approval, source registry, time budgets and tracing. Advanced settings remain supported and documented in
   [configuration](../development/configuration.md). The README has one start
   path; the launcher installs locked dependencies. API reload is opt-in and
   Streamlit does not rerun automatically on file saves.
2. **Direct presentation edits.** Titles, axis labels, colors, and compatible
   chart types use saved data and the existing rendering services. Edits preserve
   agent-authored report composition and original analytical turns. Chart/report
   revisions become visible together, survive restart, reject stale submissions,
   and retain the previous view after rendering failure. Saving again retries.
   A no-op creates no revision; downsampled charts cannot change type.
3. **Report display.** The mandatory report remains downloadable; its preview
   opens expanded and can be collapsed. Primary evidence uses a neutral
   selection badge.
4. **Typed forecast-bound meaning.** Bounds declare prediction/confidence
   intervals or scenario/sensitivity ranges and their method. Optional nominal
   coverage is explicitly nominal, and is rejected for scenario/sensitivity
   ranges. Labels and method notes match in chat and HTML. This is the independent
   labeling slice, not the full forecast evaluation/multiple-series contract.

5. **Isolated CSV/Parquet uploads.** A file starts its own conversation and
   requires explicit type review before analysis. Full-population conversion and
   key checks preserve identifiers, reject invalid dates/duplicate declared keys,
   and never truncate an oversized upload. Original bytes, hashes, reviewed
   snapshots and SQL/Python descendants persist across restart. Uploaded sources
   have no warehouse tools or fabricated semantic catalogs. Existing chart/report
   services carry their lineage; HTML includes the file hash and review choices.
   Warehouse configuration is optional for the upload entry path. Native Parquet
   decimals/timestamps survive ingestion; previews safely serialize nonfinite
   values. History deletion includes uploads and refuses imports/reviews in flight.
6. **Run-control reference.** Documented Stop/Resume, corrections, independent
   SQL/Python review, active-time and presentation budgets, emergency model/tool
   call limits and data/output caps. Key controls remain in the starter example;
   additional settings retain their runtime defaults. A dollar/token budget is not yet
   implemented.

7. **Chat attachments, parallel analysis and visible work.** Native composer
   attachments replace the sidebar upload. A file and optional question go through
   explicit schema review before execution. Independent saved-data analyses use
   bounded native subagent calls (default two workers; one for sequential mode),
   private checkpointed execution ownership, separate approvals and cancellation.
   Source assignments remain sequential. The coordinator explicitly installs the
   framework planning tool; public plan updates and current work appear above the
   collapsed Activity panel. Assumptions start collapsed; analytical warnings stay
   visible. Report analysis outputs are collapsed inspection details with ten-row
   table previews; main conclusions and warnings stay visible.
8. **Application-owned artifact handoff.** Specialist receipts now come from
   saved run and assignment state. Investigation notes no longer repeat artifact
   ID lists; invalid selections return repair feedback. Published findings are
   the authoritative answer, and successful report attachment completes the run
   without another model-written answer. Failed runs expose committed work for
   continuation. The [artifact handoff review](../reviews/artifact-handoff-review-2026-09-20.md)
   records the failure, implementation, and verification.

9. **Large-catalog retrieval and smaller model responses.** Discovery/browsing
   share a cached lexical index with exact-name/synonym priority. Fields rank on
   their own descriptions. Model-authored evidence selections are separated from
   application-owned provenance, chart IDs, and versions. Duplicate interpretation
   fields were removed; API contract 14 is strict and has no old-record migration.
10. **Voice dictation.** Native record/stop sends WAV to a LangChain Whisper
    runnable and fills the editable composer. It never submits an analytics question
    automatically. Storage remains directly under `.analytics/` or the configured root.
11. **Documentation verification.** Current guides now distinguish runtime
    behavior, repeatable test prompts, observed live outcomes, and historical reviews.
    The [live-test record](../reviews/documentation-live-tests-2026-09-26.md)
    records per-example outcomes and outstanding issues.

12. **Reproducible correctness and repair checks.** Corpus/source/code/instruction
    fingerprints, resumable receipts, explicit seven-part grading, four held-out
    cases, bounded model-visible analysis previews, and scoped reference repair hints.
    Local analysis guidance preserves units, completeness, final counts and nullable
    decisions when a statistical screen is undefined.
13. **Exact report-title revisions.** UI/API editing copies the stored specification
    without model/source calls; conversational editing invokes one dedicated tool.
    Other answer fields and report blocks remain unchanged; stale writes are rejected.
14. **Evidence-bound comparisons.** API contract 15 removes free-text metric changes.
    Current/baseline bindings drive deterministic deltas and How calculated?. Checks
    cover saved grain, dimensions, periods, units, rates, and evidence completeness.
    Canonical output bindings are persisted where source grounding establishes them;
    unverified derived bindings are explicitly disclosed.

## Verification and limits

The 27 September roadmap pass has **326 deterministic tests passing, six skipped**
across 332 collected tests.
Ten documented cases, four held-out cases, five targeted reruns, a screening rerun,
and a live KPI-card scenario were executed. Earlier failed attempts are retained.
See the [delivery review](../reviews/roadmap-implementation-2026-09-27.md) for exact
arithmetic checks, failures, repair counts, and limitations. Completion is not a grade.

The original deterministic baseline passed 188 tests. Setup/presentation and
upload increments increased coverage to 217 cases. The 20 September test/fix
pass covered 243 deterministic cases. The 21 September artifact-handoff pass
recorded 255 offline passes, with six live tests deselected. Ruff F checks and
whitespace checks passed for that change. These are dated verification records,
not a claim about subsequent unverified edits.

Regressions exercise API and Streamlit controls, immutable revisions, source/file
isolation, schema and key review, SQL approval, evidence reuse, rendering,
restart/deletion, and real agent wiring with scripted models. Retry coverage now
includes invalid final responses, invalid artifact IDs, reused chart forms,
missing/invalid report specifications, missing HTML, stale errors, cancelled
presentation attempts, and overlapping workers.

Configured-provider trials covered rankings, monthly trends, Python analysis,
uploaded-file analysis, and report recovery. See the
[live smoke record](../reviews/live-smoke-2026-09-20.md) for exact checks,
observed failures, repairs, and implemented recommendations. These examples
are not a model-quality benchmark or evidence for instruction ablation.

## Next steps and acceptance gates

- **Instruction consolidation remains an ablation.** Do not remove duplicate
  coordinator policy, feature switches, planning persistence, or specialist
  harness capabilities on the basis of deterministic tests alone. Use the
  roadmap's paired held-out live trials and declared tolerance before adopting
  behavior-changing removals. The documented smoke trials are not paired ablation trials; broader removals
  still need their own authorized evaluation.
- **Upload extensions** remain separate work: multiple files, warehouse
  enrichment and research documents are not included. The first increment has
  one file per conversation, with no in-place refresh or schema migration.
- **Comparison extensions** remain: cross-snapshot scope proof, explicit source
  cutoffs, and propagation of canonical metric meaning through arbitrary derived
  SQL/Python. Current checks do not prove a source join or free-text population.
- **Full results workspace and forecast evaluation** remain open: shared scope,
  selected-scope actions, forecast holdouts/baseline scores, multiple forecast
  series, and forecast-start markers are not supplied by these increments.
- Scope controls, refresh, reviewed corrections, driver investigations, exports,
  document evidence and monitoring retain their dependencies in the roadmap.
