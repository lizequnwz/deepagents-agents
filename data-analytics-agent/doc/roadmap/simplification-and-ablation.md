# Simplification and ablation recommendations

Reviewed 19 September 2026. Companion to the [product roadmap](roadmap.md).
These are proposed changes, not measured improvements or implemented removals.

## Direction

Reduce setup decisions, repeated instructions, and model work that ordinary code
can perform reliably. Preserve flexible investigation, exact saved evidence,
source isolation, correction handling, and restart/retry behavior. Removing
capabilities is not a successful simplification.

Start with configuration and direct presentation edits. Test more consequential
agent changes separately. Current LangChain documentation describes context
isolation as a reason for subagents; their value should be measured on long and
iterative tasks, not judged solely by a short SQL question.
[Deep Agents subagents](https://docs.langchain.com/oss/python/deepagents/subagents)

## Strong candidates

| Candidate | Observed complexity | Smaller design | Capability to preserve |
|---|---|---|---|
| Minimal first-run configuration | `.env.example` exposes provider, service URLs, feature flags, extraction limits, Python output limits, framework budgets, and tracing settings together | Show only credentials and an optional model override initially; retain documented advanced overrides with code defaults | Provider choice, execution limits, optional reviews, diagnostics |
| One setup path | README asks users to run `uv sync`; the launcher already runs `uv sync --locked` | One documented installation/start path; development-only reload settings outside normal onboarding | Reproducible environment, readiness checks, useful startup errors |
| One owner per instruction | Coordinator routing/publication rules appear in both `AGENTS.md` and its generated prompt | Keep policy in one canonical location; runtime prompt supplies source context; tool/schema contracts own executable constraints | Correct routing, clarification, partial findings, evidence requirements |
| Direct artifact edits | Chart refinements are currently conversational agent work | Validated title/label/style edits call the existing revision/rendering services directly | Immutable revisions, shared chat/report charts, report retry |
| One visible result workspace | Answer, assumptions, analysis, charts, expanded report, and ancestor datasets are rendered as successive sections | Primary result plus scope; expose Data, Method, and Report on demand | All evidence remains accessible and downloadable |
| Upload without warehouse onboarding | Startup requires a ready configured source; configured sources require a semantic model | Once uploads exist, allow an unconfigured-source state with an upload entry point; infer a draft file schema for review | Typed data, explicit ambiguity, provenance and conversation isolation |

Evidence: [settings](../../data_analytics_agent/config.py),
[example environment](../../.env.example), [launcher](../../scripts/start.sh),
[coordinator](../../data_analytics_agent/coordinator.py),
[policy](../../AGENTS.md), [report tools](../../data_analytics_agent/reporting/tools.py),
[run lifecycle](../../data_analytics_agent/run_manager.py),
[UI](../../data_analytics_agent/ui/components.py),
[source configuration](../../data_analytics_agent/data_sources.py).

**Accepted product constraint:** report composition remains agent-driven for all
data-backed answers. The agent chooses structure, narrative, and presentation to
fit the question, evidence, and audience. Replacing this with deterministic
standard reports is excluded from the simplification and ablation plan.

Keep the existing trusted renderer, evidence bindings, publication-before-render,
report failure/retry, and correction boundaries. Rendering an agent-authored
specification and applying an explicit title/style edit remain ordinary code
operations; they do not replace the agent's report composition.

Removing repeated wording needs evaluation: some repetition may help models
follow critical boundaries. Preserve each rule in its authoritative location,
and check behavior before deleting redundant copies.

For uploads, schema inference describes columns; it does not establish business
meaning. A file can support exploratory analysis without a manually authored OSI
catalog, but unclear metrics and join keys still need clarification. Keep curated
warehouse semantics. Reuse Parquet artifacts, DuckDB saved-data queries, and the
Python analysis path rather than adding a second ingestion/analysis platform.
Research documents need page/section citations; a vector database or a dedicated
research agent is not a prerequisite for a bounded initial document workflow.

## Changes to test, not assume

An ablation removes or replaces one element while holding the model, fixtures,
task wording, limits, and evaluation method fixed. Compare both outcome quality
and interaction/recovery behavior. Complementary graders and repeated trials
are more informative than a single successful demonstration.
[Agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

| Experiment | Change | Evidence needed before adopting |
|---|---|---|
| A: prompt consolidation | Remove duplicate coordinator policy wording | Stable routing, source isolation, clarification, and partial-report behavior across paraphrases and multi-turn tasks |
| B: internal feature flags | Remove visualization/analysis enable switches if no supported deployment needs those disabled states | Every supported deployment still works; approval and resource-limit settings remain available |
| C: planning persistence | For complex work, compare existing todos plus investigation summaries with one compact persisted investigation record | Equal restart continuity and completion on long tasks; fewer redundant planning calls. Simple tasks already skip both |
| D: subagent harness weight | Compare the current specialist harness with lighter specialist agents using the same tools and execution restrictions | Equivalent repair, clarification, nested approval, steering, and resume behavior; meaningful net reduction in cost/maintenance |

Experiment D is optional and lower priority. Do not collapse warehouse access into
the coordinator or grant it to Python as a shortcut. A specialist's role/tool
boundary can remain even if its internal harness becomes lighter. Avoid keeping
both implementations as permanent configurable paths after choosing a winner.

Use versioned held-out cases for scalar/ranking queries, ambiguous periods,
multi-result analyses, forecasts, edits, corrections, and restart/report recovery.
For ingestion variants, add misleading type inference, duplicate join keys, and
document citation checks. Run deterministic checks first; live trials remain
subject to the project's explicit authorization policy.

Record task success by category, unsupported-claim rate, model/tool calls,
tokens or measured provider cost, time to usable findings, report-ready latency,
repair rate, and user actions required. Pair trials and repeat model-driven
cases. Establish a non-inferiority tolerance before inspecting results; retain
the simpler variant only if critical correctness/recovery invariants pass and
quality remains within that tolerance with adequate evidence. A small inconclusive
sample does not establish equivalence. No performance savings are claimed yet.

## Keep or defer

- **Keep SQLite metadata, checkpoints, and Parquet.** They serve different
  purposes: product state, suspended execution, and typed datasets. Merging them
  into conversation history would weaken inspection and recovery.
- **Keep FastAPI for now.** It owns the background lifecycle and serves artifacts
  independently of Streamlit reruns. A two-process implementation can still have
  one startup command. Removing the API is a lifecycle redesign, not simple cleanup.
- **Keep SQL/Python responsibilities, read-only checks, lineage, completeness
  checks, and exact reviewed edits.** These are substantive guarantees.
- **Keep the existing chart library and declarative renderer.** Avoid a frontend
  rewrite, arbitrary generated dashboard code, a plugin registry, or additional
  agents until a measured requirement warrants them.
- **Defer persistent Python kernels, automatic cross-conversation learning,
  unrestricted multi-source execution, and scheduling infrastructure.** Uploads
  can be useful before any of these exist.

## Suggested delivery order

1. Simplify onboarding and consolidate instructions, with targeted regressions.
2. Deliver direct presentation edits while preserving agent-driven report composition.
3. Add isolated tabular uploads through the existing evidence pipeline; keep
   research documents and warehouse enrichment as subsequent bounded increments.
4. Run planning/harness ablations only if traces show material overhead remains.

No application code, configuration, or runtime policy was changed for this review.
No live model or ablation experiment was run. The recommendations identify what to
measure; they do not certify that proposed removals preserve effectiveness.
