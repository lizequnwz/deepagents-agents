# Simplification and ablation plan

Updated 1 October 2026. Simplify the delivered product while preserving correct
outcomes and usability. See [current capabilities](implementation-progress.md) and
the [handoff](../../HANDOFF.md). No completed paired ablation currently establishes
that an entire specialist, planning/recovery mechanism or publication requirement
can be removed. Historical smoke trials and deterministic regressions are not
substitutes for those experiments.

The [execution guide](ablation-execution.md) now provides the frozen synthetic
corpus, serving-runtime fingerprints, failure-preserving runner, independent
grading and paired gates. The first prompt-ownership patch was rejected after a
metadata-only regression in all three live repetitions; the mixed study ended
early. Its shared multiple-action review failure was repaired, and duplicate review
forms and unused review state were removed. See the
[dated outcomes and remaining gates](../reviews/ablation-outcomes-2026-10-01.md).

## Direct cleanup versus behavioral change

Remove provably unused code, no-op options, duplicate application-owned receipts
and obsolete documentation directly, with appropriate regressions. Recent cleanup
removed the debug-details setting and inactive input-validation branch, corrected
all-input Python review, and removed superseded plans/dead review references.
The later review cleanup preserves every action in a native interrupt through one
common form; decisions are ordered and bound to the current interrupt ID.

Already simplified: one startup path, shared lexical retrieval, compact model
responses, application-owned artifact IDs/lineage, direct presentation edits and
one bundle/notebook export preparation path. Do not introduce another parser,
renderer, executor, provenance model or runtime configuration variant for a feature
that these existing components can serve.

Deleting instructions or workflow components changes agent behavior. Test such
changes one at a time. Keep source ownership, upload confirmation, completeness,
units, exact approvals, recovery, immutable evidence and HTML reporting as hard
requirements. No compatibility layer or production experiment switch is needed:
compare branches/worktrees with the existing evaluation runner, then retain one
implementation when the experiment concludes.

## Prioritized experiments

| Priority / candidate | Controlled change and hypothesis | Evidence needed before adoption |
|---|---|---|
| 1. Prompt ownership | Replace repeated routing/completeness/reporting explanations with one authoritative instruction per owner; less context and contradiction | Correct scope, delegation, clarification, interrupted recovery and report agreement across simple and iterative tasks; lower tokens/repairs |
| 1. Redundant metadata lookup | Resolve only missing business roles instead of repeating already resolved discovery/browse calls | Required-entity/relationship/date-role recall and final SQL/result accuracy preserved; fewer calls and less context |
| 2. Serial versus bounded parallel analysis | Compare one worker with the current bounded workers on independent analytical questions | End-to-end time and total cost, first-attempt quality, separate approvals, Stop/Resume and partial outcomes; serial wins if parallel benefit is negligible |
| 2. Feature-disable variants | Inventory supported deployments and usage of analysis/chart disable switches | If no supported need exists, remove switches and branches directly; if removal changes routing, grade affected tasks first |
| 3. File-only specialist handoff | Compare current SQL/Python separation with one file-only analyst using existing saved-data tools | Same correct populations, units, clarification, derived lineage and reports; material reduction in handoffs/time/cost. Warehouse execution stays SQL-only |
| 3. Presentation instructions and chart arguments | First categorize actual repair failures; shorten redundant guidance/defaults or narrow chart requests only where failures justify it | Fewer invalid arguments and lower composition overhead without losing supported chart types, agent-authored composition, numerical bindings or retry |
| Conditional. Hybrid retrieval | Test only after lexical misses are established; identical candidate/context budgets | Better downstream SQL/results and ambiguity handling, with cold/warm latency and operating cost justified. Similarity scores alone are insufficient |

Planning and investigation persistence may be examined later if traces show cost
without benefit. Include interruption/resumption and multi-part evidence coverage
before attempting removal. Do not drop persistence merely because a simple total
does not need a plan; the current policy already avoids planning for simple work.

## Small, repeatable study protocol

1. Save the baseline revision, provider/model, settings, prompts, instruction/code
   hashes and frozen input snapshots. Use the existing runner/grader and temporary
   storage. Obtain provider/data authorization when required; prepare fixtures and
   deterministic checks independently.
2. Predeclare the hypothesis, changed component, target improvement and correctness
   gates. Start with 20–30 mixed cases and 3–5 independent runs per variant as a
   diagnostic batch, including held-out paraphrases. Use common inputs and pair by
   case/repetition; interleave variants where practical to limit provider drift.
3. Grade scope, joins/grain, arithmetic, units, assumptions, methodology and report
   agreement independently. Include ambiguous requests, incomplete data, multiple
   inputs, approval edits, interruptions and report failure/retry. Retain failed and
   partial runs; record first-attempt correctness and repair counts separately.
4. Record end-to-end and presentation latency, source/model/tool calls, token/cost
   data where available, user task success and repairs. Report paired differences
   and uncertainty, including per-case regressions. Missing telemetry is unknown,
   not zero cost. Repeat inconclusive studies rather than infer equivalence.
5. Adopt only when the declared gate passes, add meaningful regressions, remove the
   obsolete path, and record a compact dated result. If quality falls or evidence
   is inconclusive, retain the baseline. A diagnostic batch does not prove general
   non-inferiority; expand boundary cases before removing a major component.

Suggested provisional gates: **no hard-boundary failures**, no newly failing
independently graded case, and at least **15% lower median target latency, tokens
or cost**. Choose the target and any quality tolerance before observing results;
these numbers are proposed study settings, not measured gains or universal claims.
Major specialist/recovery removals require stronger repeated evidence than wording
cleanup. If fewer lines reduce maintenance without changing behavior, document that
benefit separately rather than invent a runtime performance improvement.

## Usability simplification

Test compact primary evidence with expandable lineage, and safe type suggestions
with risky-column warnings. Business users must still find scope, method,
limitations, complete downloads and review choices. Analyst users must trace named
inputs and replay the package. Record successful tasks, time and observed errors;
visual preference alone is insufficient.

Do not add a universal critic agent, vector service, distributed executor or live
kernel by default. Fixed templates for every answer would remove required report
composition. Dedicated execution isolation remains deferred; ablation experiments
use the existing local runner and synthetic/authorized inputs.
