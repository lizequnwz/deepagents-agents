# Analytical capability expansion

17 October 2026. Implemented locally on starting checkout `50048c6`; changes remain
uncommitted. The user prioritized agent feature breadth and authorized all seven
capability families, implemented in layers using the existing application. The
[comparative assessment](improvement-plan-2026-10-17.md) records the pinned DB-GPT,
Data Formulator and conference research. The [handoff](../../HANDOFF.md) owns next
priorities; this document records the resulting implementation and verification.

## Delivered layers

1. **Reusable analytical methods.** The existing Python specialist can import
   procedures from `data_analytics_agent.analysis`, documented in its skill.
   Exploration includes complete-population profiles, missingness, distributions,
   correlations with sample sizes and category remainders. Preparation applies
   only declared conversions, date formats, derived columns, filling, row removal
   and deduplication, recording operations and preserving original inputs.
2. **Diagnostic and customer work.** Keyed reconciliation separates unmatched
   groups from observed missing values and reconciles additive contributions.
   Retention records cohort membership, denominators and censored calendar cells.
   Ordered funnels retain entity outcomes and explicit observation windows; RFM
   requires transaction grain and saves entity scores and segment profiles.
3. **Inference, prediction and scenarios.** Independent-group numeric/binary
   comparisons save effects, intervals, sample accounting and undefined cases.
   Ridge/logistic pipelines fit preprocessing only on training data, use declared
   random/time/group holdouts and compare against a dummy baseline. Scenario grids
   save all supplied assumption combinations, formulas and undefined outcomes.
4. **Time-series work.** Explicit regular calendars expose gaps without filling
   them as zero. Trend/STL and residual screening retain unassessed cases when
   scales are undefined. ETS forecasts use chronological holdout, naive baseline,
   final refit and conditional model prediction intervals, with saved predictions,
   scores and metadata for the existing forecast-evaluation descriptor.
5. **Shared analytical presentation.** Waterfalls require a saved absolute start,
   relative contributions and reconciled ending total. Funnels require explicit
   stage order and nonincreasing integer counts. Both reuse existing charts,
   immutable presentation revisions and report rendering.
6. **Reviewed multi-table workspaces.** **Add data and documents** explicitly adds
   tables to one file conversation. Each CSV, Parquet or selected Excel table gets
   its own review and saved population. Existing saved-data SQL can combine them
   after key/cardinality/population checks. Pending table review blocks analysis;
   concurrent source staging and message submission cannot overlap. Every review
   names an exact upload ID; obsolete first-table routes and their fallback context
   branch were removed. One configured
   warehouse or one file workspace remains the conversation boundary.
7. **Document-informed analysis.** Readable PDF, UTF-8 text and Markdown become
   bounded, cited context. PDF text/tables use `pdfplumber`, the only added direct
   dependency. Tools list, read and search attached documents using exact page/line
   references. Extracted tables enter normal explicit schema review before numerical
   use. Reports and analysis bundles retain material document identities, originals,
   parsed context and hashes; derived table provenance also records source page.

The coordinator loads an analytical workflow skill, plans broad tasks, inspects
findings and adapts within approved scope. It still sends simple descriptive work
to SQL, clarifies material business ambiguity and respects selected input scope.
No agent per method, new workflow engine, separate chart renderer or live kernel
was introduced. Reviewed metrics remain authoritative; clear custom calculations
state their formula, population and units. Procedures are starting methods, not
an exhaustive algorithm catalog.

## Portable execution and storage

API/storage contract is **20** and new bundles use format **3**. Restart both
services together using fresh storage for incompatible history. There are no
migrations, fallbacks or compatibility readers. Preserve needed older artifacts
separately before changing storage.

Each Python execution snapshots the exact analytical helper sources it can import.
The bundle saves these per step under `steps/libraries/`; standalone replay uses
those sources and verifies hashes. It does not install the application package,
reconnect to a warehouse or recompute published interpretations. Existing script
and notebook paths share the replay runtime. Material document originals and parsed
context are hashed alongside typed data, code, figures and the report.

## Verification

Final full suite: **617 passed, six skipped**, in 130.92 seconds. The six skips
are opt-in provider checks, not passes. Command:

```bash
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false .venv/bin/python -m pytest --tb=short
```

The final run followed the explicit-upload-ID cleanup and Decimal-feature repair.
The cleanup also passed 67 focused upload, Excel, file-workspace, export, ablation
and example-runner checks, including fresh-kernel notebook replay. Ruff undefined/
unused-symbol checks over the application, UI, tests and scripts, and
`git diff --check`, passed. Local links in the updated current guides and review
records were checked. No browser layout or human usability study was performed.

New deterministic checks cover analytical arithmetic, retained populations and
exclusions, calendar censoring/gaps, declared dates, reconciled contributions,
training-only preprocessing, chronological forecast evidence, waterfall/funnel
validation, same-workspace joins and restart, blocked cross-conversation review,
upload/message concurrency, real synthetic PDF extraction and Markdown table
review. Native Streamlit tests inspect document pages and ensure only file
workspaces offer extracted-table review. Integration checks pass helpers through
actual Python execution, saved evidence, reporting and a moved portable replay;
source tampering is rejected. Document originals/extractions survive report export.
Existing notebook checks use a fresh local kernel.

The first full regression run found two stale test fixtures: the coordinator's
skill list and a rejected historical ablation patch. The skill expectation now
includes analytical workflows; the patch was refreshed against current wording
without adopting it or changing the historical failed-study result. Method review
also found ambiguous date inference and date-conversion missingness loopholes;
regressions now require explicit preparation instead of silently guessing. Native
Parquet Decimal prediction features retain numeric meaning rather than being
one-hot encoded as categories, with float-parity regression coverage.

No provider, live warehouse or business-user study was run. Upstream projects were
inspected, not executed. These checks establish local implementation behavior,
not broad model task accuracy, causal validity, calibrated future coverage or
comparative superiority. Existing opt-in provider tests remain skipped.

## Limits and next work

- Cohort/event eligibility, source cutoff, feature availability, independence and
  business keys require defensible analyst choices. Structural checks do not
  certify arbitrary joins, leakage-free features or source completeness.
- Delivered inference is independent two-group estimation. Prediction uses fixed
  simple candidates; forecasting uses one declared series with ETS and a naive
  baseline. Richer methods can use installed libraries but need their own method
  review, evidence and evaluation. Scenario ranges have no probability coverage.
- Documents are unreviewed context, not authoritative instructions or curated
  business definitions. Extraction is not OCR and may need correction. Limits
  include 200 PDF pages, two million text characters, bounded extracted JSON and
  the configured upload size. Warehouse conversations accept context documents,
  without combining their file tables with warehouse execution.
- General repository reading, code authoring, external documentation research,
  broader approved cross-schema discovery and semantic authoring remain later
  workspace capabilities. Local fresh-process execution remains outside a security
  sandbox, as before.
- Earlier count/grain, empty Snowflake type, optional forecast-completion descriptor,
  final-output selection, metric identity, business-equivalent refresh and narrative
  binding gaps are not claimed fixed by this feature release. See the handoff for
  next priorities. No behavioral ablation was adopted without comparative evidence.
