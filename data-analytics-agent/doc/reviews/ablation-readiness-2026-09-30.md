# Ablation readiness verification

30 September 2026. Implementation remains in the local working tree. No commit,
deployment, paid provider trial or behavioral adoption was performed.

## Baseline and delivered work

Preserved the interrupted Excel, export, all-input review and cleanup changes.
The initial regression run produced **349 passed, six skipped**, with the existing
Jupyter test blocked by restricted local socket access. That test passed when
allowed its temporary loopback port: **350 passing baseline cases** in total.

Extended the existing evaluation workflow rather than introducing a service:

- Serving-checkout code/instruction hashes, installed/locked dependency versions,
  provider/model, hashed provider route/organization options and effective execution
  settings. Requested SQLite input hashes include an existing WAL; remote contents
  remain explicitly unfrozen. Upload-only
  fingerprints work without a configured warehouse. No keys/environment files are
  included in the fingerprint.
- Explicit file path, worksheet/range and schema/key confirmation in frozen corpora.
  Prepared 25 generated cases and three held-out paraphrases, a deterministic
  120-month source, a capped source, and fixed CSV/Excel inputs. Independent fixture
  checks verify 120 observations, total index 26,280, and the selected workbook's
  eight rows, leading-zero identifiers and total index 1,080.
- Run receipts saved before artifact downloads; complete CSV/Parquet, HTML/spec and
  the existing analysis ZIP. Failed outcomes remain recorded; optional batch
  continuation retains missing dependent cases. Interrupted review/download work
  reuses the existing run. Completed collections are preserved on rerun.
- Every frozen corpus case is graded, including missing receipts and absent reviews.
  Grades bind to manifests, run IDs and exact receipt hashes. Missing artifacts,
  execution drift and missing reviews cannot become passing evidence.
- Paired case/repetition alignment, rejection of uncontrolled changes, fresh-run
  checks, first-attempt and hard-boundary review, failed-tool categories and unknown
  telemetry handling. Relative improvements collapse paired repetitions within
  cases; percentile bootstrap resamples conversations to keep follow-ups together.
- A predeclared prompt-ownership study and an isolated candidate patch. The patch
  consolidates existing policy into coordinator memory and the analyst skill;
  SQL-only source ownership, units, completeness, recovery and HTML remain.

The synthetic serving helper uses the existing FastAPI application and local
runner, isolated storage and disabled external tracing. It starts no model call
until a question is submitted. There is no production ablation switch, compatibility
reader, additional specialist, vector service or execution infrastructure.

## Checks

- Full local regression suite: **368 passed, six skipped**. Skips are opt-in provider
  checks; they were not counted as passes. The suite included fresh-kernel notebook
  replay with temporary local-port access.
- Focused receipt/grader/comparison checks after the final conversation bootstrap
  adjustment: **30 passed**. Fabricated paired receipts test the reducer's mechanics,
  never provider accuracy or measured performance gains.
- Prepared prompt candidate in an isolated code/instruction copy: **42 focused checks
  passed**, across real scripted-agent wiring, checkpoint recovery, nested approvals,
  bounded independent analysis, reports, steering and uploaded-file review/reopening.
  One initial copy omitted the unchanged Streamlit entry point; adding it allowed
  the remaining UI test to pass. That was fixture preparation, not a product defect.
- Synthetic preparation and local serving CLI checks passed. The real API returned
  healthy status and fingerprints for both generated sources; **zero run requests**
  were submitted. The temporary server was stopped. Candidate
  patch application and compilation, Ruff undefined/unused-name checks and whitespace
  checks passed.

API contract remains 16: the added read-only evaluation endpoint changes no stored
record or existing response schema. Restart the API before using the updated runner;
older servers do not receive an evaluation compatibility path.

## Decision and limits

**Retain the validated baseline.** The candidate is reviewable but unadopted.
No paired live findings establish improved quality, tokens, time or cost. Scripted
models cannot establish the effect of changed instructions on a provider model.
No usability participants, human task timings or new browser sessions were claimed.

Live corpus grading and actual approval edits, Stop/Resume and report retry are
still required by the predeclared study. Merely mentioning a scenario in a question
does not satisfy its evidence gate. Paid cost and warehouse query counts are unknown
unless separately measured; partial/missing usage is never zero. A diagnostic
comparison cannot justify removing a specialist or recovery mechanism.

The [execution guide](../roadmap/ablation-execution.md),
[study](../roadmap/prompt-ownership-study.json), and
[candidate patch](../roadmap/prompt-ownership.patch) identify the next concrete step.
