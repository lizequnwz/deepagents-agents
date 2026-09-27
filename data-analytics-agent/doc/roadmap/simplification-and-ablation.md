# Simplification and ablation plan

Updated 26 September 2026. See the [current roadmap](roadmap.md),
[implementation log](implementation-progress.md), and
[live-test issues](../reviews/documentation-live-tests-2026-09-26.md).

## Already delivered

- One startup path, a compact environment example, and a separate advanced reference.
- Direct chart presentation edits with matching immutable report revisions.
- Uploads without requiring a ready warehouse, with explicit schema review.
- Application-owned artifact receipts and lineage; no redundant model-authored inventory.
- Seven-field coordinator response, two-field SQL response, and separate chart request/storage contracts.
- One cached retrieval index shared by discovery and browsing, without embedding infrastructure.

Do not propose these as future work or confuse them with broader unimplemented
scope controls, deterministic KPI comparisons, or model-quality evaluations.

## Remaining experiments

| Candidate | Experiment | Acceptance gate |
|---|---|---|
| Repeated coordinator policy | Compare current instructions against one-owner wording on held-out simple, iterative, ambiguous, and interrupted tasks | No material regression in correct scope, routing, report completion, or recovery; record paired trials and repair frequency |
| Forced metadata searches | Compare progressive unresolved-role lookup against redundant browse calls | Maintain required-entity recall and final-result accuracy while reducing calls/context |
| Embedding or hybrid retrieval | Compare with current lexical index at equal context budgets, including synonyms absent from metadata | Demonstrated gain in final SQL/results, not only retrieval similarity; disclose cold/warm latency |
| Large chart request | Measure tool-input repairs by chart type before splitting schemas | Fewer invalid arguments without limiting supported charts or adding parallel rendering contracts |
| Primary result presentation | Test compact primary evidence with expandable lineage | Users can still find complete downloads, method, scope, and limitations |

Agent-driven report composition remains a product requirement. Application code
renders and binds evidence; replacing every answer with a fixed report template
is outside this plan. Remove capabilities or prompt rules only with evidence.
