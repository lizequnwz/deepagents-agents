# Draft implementation plan: specialist efficiency and conversational progress

Status: increments 0–5 implemented and deterministically verified on 2026-09-08. See [delivery and verification](agent-efficiency-and-progress.md). Live-model performance comparisons remain outstanding.

This plan supersedes the earlier review's proposal to merge the coordinator and analytical specialists. Preserve the existing specialist architecture and improve efficiency inside it.

## 1. Agreed direction

1. Keep the coordinator, text-to-SQL subagent, and data-analysis subagent.
2. Consolidate text-to-SQL instructions into one concise system prompt. Remove its mandatory query-writing skill read and obsolete skill file.
3. Keep the data-analysis skill and its methodological references. Interpret the user's phrase “keep the SQL for data analysis specialist” as “keep the skills for the data-analysis specialist.”
4. Consolidate chart guidance into the prompt of its existing owner. The current implementation has a coordinator-owned `create_chart` tool, not a chart subagent. Put concise chart guidance in the coordinator prompt; do not introduce a new agent solely to house a prompt.
5. Keep report-design as an on-demand skill. Every data-backed answer still requires an HTML report.
6. Return semantic definitions, physical mappings, and declared relationships together. Inline compact definitions for small catalogs; retrieve bounded relevant context for larger catalogs. Cache by semantic content version.
7. Distinguish simple answers from investigations through instructions and observed task needs, without a classification model or rigid keyword router.
8. Replace the disconnected progress/log presentation with one assistant-turn activity experience, including in-run steering and explicit clarification.

Retain source-bound conversations, sequential source assignments, exact execution evidence, typed datasets, chart versions, Stop/Resume, and configured optional approvals. Source access remains exclusively with text-to-SQL. This work does not add direct SQL execution to the coordinator or Python specialist.

## 2. Intended user experience

For a straightforward total over a known small catalog:

```text
User asks question
  → coordinator delegates a complete SQL brief
  → SQL specialist uses definitions already in its prompt
  → SQL executes and saves the result
  → specialist returns its compact response
  → coordinator publishes the answer and produces the required report
```

No SQL skill read, redundant semantic lookup, todo list, investigation record, Python execution, or forced chart is needed. Retaining subagents and report composition means the whole turn will still require several model responses; do not promise a two-request end-to-end workflow.

For a larger or unfamiliar catalog, one cohesive semantic-context call should normally establish the definitions needed for a straightforward query. Additional discovery is appropriate when the first result is incomplete or ambiguous.

Complex work still uses plans, investigation records, several SQL/Python assignments, and analysis skills. Simplicity is judged by the work required, not by the number of words in the question. A short “Why did sales drop?” can require an investigation.

The UI renders the user's question first. Directly beneath it, the assistant turn contains one current action, elapsed time, Stop, and one Activity expander. Findings appear in that same turn as soon as published. Report preparation becomes a secondary status attached to the findings. The composer remains available for corrections.

The previous progress mockup is a visual reference, not production code or real data: [mockup source](/Users/charlie/.codex/visualizations/2026/09/08/01a080a4-60d5-77d0-b59c-54be9bdfe370/analyst-progress.html).

## 3. Deliver working increments

### Increment 0 — Isolate verification and establish a baseline

Fix test-storage isolation before executing the default suite. `test_settings` currently inherits `ANALYTICS_STORAGE_DIR=.analytics`, and import-time app construction can instantiate application services. History-deletion tests must never operate on the developer's configured workspace.

- Set a fresh per-test storage root explicitly, regardless of `.env` or inherited process settings.
- Make collection/import-time service construction safe through the app factory or isolated test bootstrap; a fixture applied after imports is not sufficient for all import-time effects.
- Preserve normal application startup behavior; avoid an environment-specific compatibility branch in production logic.
- Capture the baseline using isolated scripted-model cases and existing diagnostics: model requests by agent, tool calls, skill reads, semantic calls, computation time, time to first published findings, and report duration.
- Use deterministic tests for behavior and opt-in synthetic live cases for model quality and latency. Do not use business databases for mutation-capable UI tests or enable external model calls automatically.

Primary files: `tests/conftest.py`, test app/service fixtures, `data_analytics_agent/api.py` if needed for safe construction.

Acceptance: an inherited workspace path containing sentinel records remains untouched after collection and the full deterministic suite. All test storage is temporary and isolated from other tests.

### Increment 1 — Consolidate SQL and chart guidance

**SQL system prompt**

Rewrite the specialist prompt as the single source of operational SQL instructions. Consolidate, do not append the full skill verbatim to the existing prompt. Retain:

- Role: semantic grounding, retrieval, descriptive analysis, value lookup, and saved-data shaping.
- Use the provided exact definitions when sufficient; discover additional context only when needed.
- Source dialect versus DuckDB dialect for saved results.
- Declared joins, correct business grain, metric meaning, deterministic rankings, and complete appropriate populations.
- Existing read-only query rules and authoritative edited-code behavior.
- Fresh requests require source execution; suitable saved snapshots can answer follow-ups.
- Repair expected failures using tool feedback; preserve successful evidence.
- Finish with the existing compact `SQLAnalysisResponse`.

Keep tool-argument syntax, bounds, and examples primarily in tool schemas/descriptions. Do not duplicate detailed `field_names` or chart-field rules in several places.

Remove `skills/text-to-sql/query-writing/SKILL.md`, its skill registration, and all instructions requiring its read. Use a plain prompt constant or a small builder in the agent module; no prompt registry, templating framework, or runtime reading of the deleted skill.

**Chart guidance**

Fold a concise chart-design section into the coordinator system prompt, conditionally included when visualization is enabled. It should explain purposeful chart choice, respecting the user's requested type, exact dataset columns, appropriate grain, uncertainty, and reuse/revision of shared chart IDs. Shape constraints belong in `ChartSpec` field descriptions and validation feedback.

Remove `skills/data-visualization/chart-design/SKILL.md`, its registration, and all “load chart-design” references. Preserve existing chart rendering, evidence bindings, and report references. Avoid promoting arbitrary business transformations into chart rendering.

Keep `skills/analysis/` and `skills/reporting/` registered with their current owners. Do not redesign analysis methodology or report generation in this increment.

Update the runtime `AGENTS.md`, agent prompts, tests, documentation, and tutorial references together so no instructions point to deleted skills. Keep runtime instructions distinct from coding-agent implementation notes.

Primary files: `data_analytics_agent/agents/text_to_sql/agent.py`, `data_analytics_agent/coordinator.py`, `AGENTS.md`, the two obsolete skill directories, relevant tool descriptions/tests/docs.

Acceptance:

- A scripted SQL assignment does not call `read_file` for query-writing instructions.
- A chart request does not read chart-design instructions.
- SQL/analysis ownership, report skill loading, exact edits, and chart revision still work.
- No stale registrations, duplicated skill content, or references to the deleted files remain.

### Increment 2 — Cohesive, bounded semantic context

Introduce one ordinary discovery tool, tentatively named `get_semantic_context`. It accepts a business question and optional exact dataset/metric selections for refinement. Its output contains the selected definitions and joins needed to proceed, not just search candidates.

**Implement a deterministic context builder** shared by prompt construction and the tool:

1. Reuse the current catalog search and exact-name resolution.
2. Select relevant datasets/metrics and resolve catalog-backed fields referenced by selected metrics.
3. Include necessary declared join paths, bridge datasets, join-key fields, and primary-key/grain information.
4. Return logical names, business definitions, critical instructions, relevant field types, physical sources/expressions for the SQL projection, selected metrics, and relationships together.
5. Return the catalog content hash, what was included, omissions, unresolved references, and ambiguity indicators. Clearly distinguish missing context from a known disconnected relationship graph.
6. On invalid names, return valid alternatives in a repairable response. Never guess a physical field or join solely to fill the response.

Do not present the first shortest path as proven business intent when multiple declared routes have different meanings. Surface relevant alternatives or the ambiguity. Resolve dependencies using existing metadata and SQLGlot where practical; explicitly flag expressions that cannot be resolved reliably rather than adding a speculative SQL compiler.

**Bound context by serialized size**, rather than dataset count alone. A table with hundreds of fields is not a small catalog. Reuse an initial internal budget comparable to the existing 12,000-character overview budget, and tune from fixtures. Do not add numerous environment settings.

- Small catalog: if the complete compact SQL definitions fit, insert them directly into the SQL specialist's prompt, with an explicit completeness marker and content hash. No separate discovery call is required for definitions already present.
- Large catalog: provide a compact orientation and use `get_semantic_context` to retrieve relevant definitions. Keep whole definitions and necessary joins intact; omit lower-priority entities rather than cutting expressions or instructions mid-string.
- If a relevant package exceeds the budget, report what is missing and provide a refinement path using exact selections and existing paginated browsing. Never mark an incomplete package as sufficient.
- The coordinator receives business-facing metadata only, preserving the existing projection and responsibility boundary. Do not duplicate full physical catalogs across agents.

Keep paginated browsing for unknown vocabulary/large catalogs and `lookup_values` for actual data-bearing category discovery. The context tool must not execute warehouse SQL or retrieve source values.

Replace the normal `search_semantic_model` → `get_semantic_entities` → `get_relationships` model-facing chain. Reuse their internal algorithms, but remove obsolete public wrappers once callers and tests move over. Do not retain overlapping tools as compatibility aliases.

**Cache semantics, not observations.** Use the existing `SemanticCatalog.content_hash`, not only the OSI format version. Cache a compact catalog representation and bounded context packages, keyed by source identity, content hash, dialect, physical/business projection, normalized request, exact selections, and output budget. A bounded process-local cache is enough; no Redis, vector database, or persistent cache service.

Keep graph/prompt/context construction coherent with the loaded catalog version. Rebuilding a loaded catalog invalidates its prompt/context cache; an old checkpoint must not silently switch definitions halfway through a run. Retain and document the existing restart-to-reload workflow for this scope; do not claim live file reload merely because the cache key includes a hash. Cache invalidation tests must construct/reload a new catalog version and prove no prior package or graph prompt is returned.

Primary files: `data_analytics_agent/semantic.py`, `semantic_tools.py`, `coordinator.py`, `agents/text_to_sql/agent.py`, `api.py` for graph/catalog cache coherence, semantic discovery tests.

Acceptance:

- A small fixture can generate a correctly grounded SQL query with zero semantic tool calls.
- A straightforward large-catalog fixture gets exact fields, metric definitions, and required joins in one discovery call.
- Multi-hop joins include bridge definitions; ambiguous or missing paths are explicit.
- Output limits cannot silently remove a required definition.
- Catalog hash, dialect, source, and projection changes cannot share stale context.
- Metadata context retrieval performs no source-value query.

### Increment 3 — Proportional work through prompts

Add concise routing examples to the coordinator and SQL prompts, and reconcile `AGENTS.md` with them:

| Request | Intended behavior |
|---|---|
| Greeting, help, metadata explanation | Coordinator answers directly; no data query/report |
| Simple total or ranking | SQL assignment; no todos, investigation record, Python, or artificial chart |
| Descriptive monthly series | SQL; chart when useful/requested; Python only if the requested method needs it |
| Forecast, uncertain estimate, competing explanations | Plan when useful; SQL/Python iteration; investigation continuity |
| Chart title/type refinement | Reuse suitable saved evidence and existing chart ID; retrieve/reshape only if actually needed |

A simple task can become an investigation when results reveal meaningful issues. An investigation can stop when evidence is sufficient. Do not impose one-query rules, prohibit necessary repair, or add a classifier call.

The coordinator should delegate a complete business brief once, let the specialist finish its assignment, and inspect only what is needed for synthesis. Avoid repeated lookups of evidence already returned. Do not suppress meaningful validation to meet a latency target.

The required report remains in scope even for a scalar answer. Keep it compact; do not incorrectly interpret “simple” as “skip evidence/reporting.”

Acceptance: scripted scenarios enforce ownership and optional-work behavior; opt-in live scenarios evaluate whether the model actually follows the intended paths. Use separate measurements for model calls, tool calls, and computation; one `task` call can contain several model requests.

### Increment 4 — One activity experience inside each assistant turn

Refactor `render_active_run` so it no longer emits phase/tool summaries above the user's question. Establish a stable turn shell used before and after findings publication:

```text
User message

Assistant
  Checking revenue for August · elapsed time                 Stop
  ▸ Activity

  Published findings and selected artifacts, when available
  Report: preparing / ready / retry available

Composer: add context, correct the request, or follow up
```

Avoid rendering the user message a second time when calling the existing `render_turn` after publication. Separate user-message rendering from assistant content so the shell remains in place.

**One activity model, several levels of detail:**

- Always visible: one current meaningful action and honest elapsed time. Avoid a fake percentage or fixed checklist of stages.
- Activity expansion: concise substantive steps, their actual status, and useful outputs. Example: “Revenue definition loaded,” “Queried monthly sales,” “Compared forecast models.”
- Step inspection: exact SQL/Python, bounded I/O, artifact links, duration, and repair attempts.
- Developer diagnostics: model counts, tokens, agent/tool names, and framework details, accessible without a second duplicated timeline.

Use existing events, execution purposes, artifact metadata, and callback identities to generate deterministic labels. A short purpose field on Python execution may be added if needed; do not add a model call or mandatory progress tool just to narrate activity. Do not label “definition loaded” as “definition verified” unless verification happened.

Prefer the actual active leaf operation over a long-running parent `task` event when choosing the current status. Preserve agent ownership and grouping using supported callback/runtime metadata; do not infer agent identity from opaque graph namespace strings, which previously caused attribution defects.

Do not expose private chain-of-thought. User-facing status describes actions and observed outcomes only.

**State behavior:**

- Quick query: compact status; no flashing stage list.
- Investigation: current action plus expandable milestones; show supported provisional findings only when explicitly published, not arbitrary intermediate output.
- Findings published: display immediately; report preparation is secondary.
- Report failure: show “Findings ready · Report needs retry,” preserving the answer and retry action. Do not present this as a failed SQL/Python analysis. Preserve the required-report completion contract and existing report-design skill.
- Recoverable tool error: visible inside activity as a repair; avoid a top-level alarm while the agent can continue.
- Input needed or unrecoverable blocker: show the question/error in the assistant turn, with clear action.
- Completed: the same turn contains its answer and Activity disclosure. Do not forcibly close a disclosure the user has opened.
- Paused/restarted: render saved steps in the same structure and keep Resume available.

Reuse keyed native Streamlit components and the existing timed fragment. Preserve expander state, composer contents, focus, and stable artifact identity during polling. Avoid re-fetching reports or recomputing full hidden diagnostics every second. Use existing incremental event support where suitable, not a new transport just for layout.

Primary files: `streamlit_app.py`, `data_analytics_agent/ui/components.py`, `ui/api_client.py`, `diagnostics.py`, and event schemas/stores only where necessary.

Acceptance: a browser/AppTest fixture confirms correct ordering, no duplicate question/answer, stable expansion during polling/publication, one timeline, correct repair/export states, and legibility on narrow screens. Preserve existing evidence downloads, chart/report rendering, Stop/Resume, and optional code-review controls.

### Increment 5 — Persistent in-run steering and clarification

This is backend work as well as UI work. A visible composer that merely returns HTTP 409 is not an implementation of steering.

**User corrections:**

- Accept a submitted correction for an active run through a small explicit API contract; preserve ordinary new-turn submission for idle conversations.
- Save the original text and a stable message ID durably with the run/conversation. Acknowledge “Received; applying after the current step” separately from “Applied.”
- Deliver pending corrections at the next supported model/tool-cycle boundary to the active specialist and coordinator as appropriate. Already executing SQL/Python may finish; retain its evidence with the original scope.
- Use supported Deep Agents/LangChain middleware and LangGraph checkpoint mechanisms, verified against installed versions. Do not edit graph internals or concurrently call `invoke` on the same run.
- Track which correction IDs were delivered in each relevant execution context so checkpoint replay does not repeatedly inject them and a later specialist receives the updated brief.
- Before final publication/completion, reconcile accepted pending corrections so a run cannot silently finish on the earlier request. Handle the race between a new correction and finalization atomically through the existing run lifecycle.
- Keep corrections visible in chronological conversation history. Do not overwrite the original question or describe old artifacts as if they came from the corrected request.
- A correction arriving after findings publication/report preparation is a follow-up turn reusing evidence; do not mutate already-published findings in place. The UI/API must clearly return which turn owns it.
- Preserve cancellation, pending approvals, restart recovery, and sequential source execution. A changed request must not silently approve an earlier proposed SQL/Python action; reconcile it before resuming affected work.

Implementation should start with an isolated integration probe proving the supported middleware delivery boundary for a nested specialist. If an executing specialist cannot receive new input at that boundary with the installed framework, use a supported checkpointed pause/resume or a clean return to the coordinator with saved evidence and an updated assignment. Do not fall back to silently deferring every correction until the original answer is complete. Document the chosen mechanism and its observable latency.

**Clarification:**

- Give the coordinator a small explicit request-for-clarification operation using the maintained interrupt/resume mechanism.
- Render its question and optional suggested choices inline; always accept a text answer.
- Distinguish clarification from optional SQL/Python approval in API/UI state.
- When the analysis specialist returns `needs_clarification`, the coordinator asks the actual business question, obtains the answer, and resumes/reassigns with preserved evidence.
- Do not require a report for an unanswered clarification with no findings. Previously published supported findings remain available.

Primary files: `data_analytics_agent/api.py`, `schemas.py`, `stores.py`, `run_manager.py`, agent middleware/wiring, `ui/api_client.py`, `streamlit_app.py`. Add a small dedicated steering module only if it keeps responsibilities clearer than extending an unrelated module.

Acceptance:

- A correction during a slow SQL call is acknowledged, applied at the next supported boundary, and reflected in later analysis.
- A correction during a Python assignment reaches the correct context without launching duplicate workers.
- Several corrections preserve order and survive pause/restart.
- A correction/finalization race has one explicit outcome: applied to the active investigation or accepted as a follow-up, never lost.
- A clarification is answerable and resumable without a new unrelated investigation.
- Report preparation does not block accepting a follow-up.
- Pending code approvals cannot execute an obsolete plan without reconciliation.

## 4. File and responsibility map

| Area | Main files |
|---|---|
| Coordinator policy and chart prompt | `AGENTS.md`, `data_analytics_agent/coordinator.py` |
| SQL specialist prompt and tool registration | `data_analytics_agent/agents/text_to_sql/agent.py` |
| Analysis skills retained | `data_analytics_agent/agents/data_analysis/agent.py`, `skills/analysis/` |
| Report skill retained | `skills/reporting/`, existing reporting tools |
| Semantic context/package builder | `data_analytics_agent/semantic.py`, `semantic_tools.py` |
| Catalog/graph cache coherence | `data_analytics_agent/api.py` |
| Activity labels and identities | `data_analytics_agent/diagnostics.py`, relevant schemas |
| Progress and composer | `streamlit_app.py`, `data_analytics_agent/ui/components.py`, `ui/api_client.py` |
| Steering/clarification lifecycle | `api.py`, `schemas.py`, `stores.py`, `run_manager.py`, supported middleware |
| Verification | Semantic, agent-workflow, UI, run-manager, checkpoint, nested-HITL, and live-evaluation tests |

Use the existing modules first. Extract small helpers only where there is genuine reuse or a coherent separate concern. Remove obsolete paths and references; do not add compatibility layers or migrations.

## 5. Validation and performance acceptance

Build one shared scenario set with at least:

1. Simple scalar over a small catalog.
2. Joined aggregation requiring a bridge table.
3. Large catalog with relevant definitions outside the overview.
4. Ambiguous metric or relationship requiring refinement.
5. Descriptive time series and requested chart.
6. Iterative Python investigation with additional SQL retrieval.
7. Chart revision using saved evidence.
8. Automatic repair followed by success.
9. Report failure and report-only retry.
10. In-run correction, clarification, Stop/Resume, and restart recovery.

Use numerical assertions and saved artifacts where relevant. Deterministic scripted models validate wiring; they do not prove a live model's intelligence or route selection. Opt-in live evaluations must use synthetic fixtures and retain traces for comparison. Keep model/configuration fixed when comparing before and after; report prompt size, request count, and latency together.

Desired measurable changes:

- Zero mandatory SQL/chart skill reads.
- Zero semantic tool calls for fully supplied small-catalog definitions in the targeted simple case.
- One cohesive discovery call normally sufficient for the targeted larger-catalog case, while allowing justified refinement.
- No added model calls for progress narration or complexity classification.
- Simple questions avoid unnecessary planning/Python/investigation artifacts.
- No regression in correctness, explicit chart-type preservation, evidence lineage, source ownership, or report availability.
- User question precedes progress; one stable activity view; findings are usable while the report is preparing.
- Accepted corrections are visibly pending/applied and never lost.

Do not enforce universal low call-count ceilings. A necessary clarification, validation query, or repair can legitimately increase the count. Compare distributions over representative live questions before claiming a percentage speedup.

After relevant deterministic checks pass, run the isolated full suite and existing Ruff command. Verify the live UI against an isolated fixture API, including open disclosures, input typing during polling, narrow layouts, and report retry. Do not rerun the unsafe default suite until Increment 0 is complete.

## 6. Boundaries and completion criteria

This scope does not merge specialists, add a chart subagent, replace the frontend, introduce embeddings, add data sources/uploads/research, change model providers, create a persistent Python kernel, or redesign the report renderer. Automatic report generation without a report skill was an earlier option; it is not part of this agreed plan.

There is a known map/report incompatibility in the existing renderer. Record it as a separate existing defect; do not count unsupported offline map output as a regression introduced by prompt consolidation, and do not silently change a user's requested chart type to hide it.

The coding agent should deliver these increments in order, keeping each end-to-end path working. Finish with updated runtime instructions/docs, removed obsolete skills/tools, isolated test results, representative before/after traces when live evaluations are enabled, and a concise explanation of remaining limitations. Update the API contract version if the public UI/backend contract changes. No legacy compatibility layer is required.

**Completion means all agreed behavior is implemented, including backend steering and clarification—not merely moving the progress labels or displaying a composer during a run.**
