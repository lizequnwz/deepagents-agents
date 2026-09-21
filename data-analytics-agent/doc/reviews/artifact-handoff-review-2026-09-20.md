# Artifact handoff and agent design review — 20 September 2026

The reported failure is confirmed in the local saved run. A one-character chart-ID transcription error aborted an otherwise successful investigation. The main architectural improvement is to make application code carry artifact identity and lifecycle state, while agents decide analytical questions, evidence relevance, and presentation.

The review below records the original behavior on 20 September. The prioritized improvements were implemented on 21 September; see the implementation record at the end. Saved conversations were not modified.

## Confirmed incident

Read-only inspection of `.analytics/metadata.sqlite` found failed run `46287769-fa45-4b34-823e-876567435196`, in conversation `18acdb81-3abf-4770-8c23-d56c81443b32`, source `chinook`. Its question requested two parallel analyses of the saved monthly invoice series.

Both analysis assignments completed. All six recorded Python executions succeeded. The coordinator created charts and then called `save_investigation` with twelve artifact references. Eleven references resolved in the conversation/source scope.

| Reference | Value |
|---|---|
| Chart ID returned by `create_chart` | `d0f1be23-5803-4635-885f-fe5459217488` |
| ID supplied to `save_investigation` | `d0f1be23-5803-4633-885f-fe5459217488` |

The third UUID group changed from `4635` to `4633`. This was a coordinator transcription error for a coordinator-created chart, not a missing specialist result or demonstrated parallel-write race.

`presentation.py:125` accepts a model-supplied `artifact_ids` list. It constructs the allowed set from datasets, analyses, and charts for the current conversation/source. At line 153 it rejects any reference outside that set with an ordinary `ValueError`. Only `publish_findings`, not `save_investigation`, is configured for recoverable tool errors. The run manager consequently marks the run failed.

The first failed tool event occurred at 22:12:22 UTC. A retry at 22:13:26 UTC repeated the same tool-call ID and identical arguments, including the bad reference, and failed again. It did not give the coordinator a recoverable tool result from which to repair the ID. No findings or report were published for this run, although the specialist evidence and charts were saved.

A separate isolated reproduction using the actual investigation tool confirmed:

- The mistyped reference raises the exact reported `ValueError`.
- `save_investigation.handle_tool_error` is `False`.
- The correct reference succeeds with `{"ok": true}`.

The scope check itself is appropriate. Do not remove it, accept arbitrary references, or silently substitute the closest-looking UUID.

## How references currently move

The application generates and saves UUIDs; the models subsequently repeat them in messages and tool arguments.

1. SQL saves a result and returns its ID to the SQL specialist. The specialist produces `SQLAnalysisResponse`, including a model-written `result_id`.
2. Python execution saves derived datasets and execution records. The specialist supplies input/execution IDs to `finish_analysis`, which saves an analysis and returns its ID.
3. The Python specialist is then instructed to write the saved analysis ID and summary in a final message. It has no configured structured response. The parent receives that final prose through the native `task` tool.
4. The coordinator copies selected references into subsequent analysis briefs, chart specifications, the investigation record, publication, report blocks, and its final structured answer.

The installed Deep Agents implementation serializes `structured_response` into the parent's tool message when present; otherwise it forwards the specialist's final assistant text (`deepagents/middleware/subagents.py:474`). This matches the current [Deep Agents structured-output documentation](https://docs.langchain.com/oss/python/deepagents/subagents#structured-output).

SQL therefore has a structured handoff, but Python currently has a prose handoff after a structured save. Neither a JSON schema nor UUID syntax validation proves that an identifier exists. The erroneous ID here is still a syntactically valid UUID.

## Findings and recommended changes

### 1. High priority: expected reference errors abort the workflow

The confirmed investigation failure is the strongest example. Related gaps exist in `query_saved_results`, whose result lookups happen outside its DuckDB error handler (`agents/text_to_sql/tools.py:153`), and `inspect_conversation_analysis`, which directly returns a store lookup (`reporting/tools.py:231`). Unknown references can escape as exceptions instead of becoming useful correction feedback.

Use one consistent policy at model-facing reference boundaries: an invalid reference returns a recoverable error identifying the offending references and a way to discover valid same-scope choices. Preserve strict scope validation and let unexpected infrastructure/programming failures surface normally. Changing `handle_tool_error` alone is insufficient if the tool still raises an ordinary `ValueError` rather than the handled error type.

Investigation notes should not require the model to restate a list the application already knows. Remove the `artifact_ids` argument and keep the record narrative-only, with evidence obtained from trusted run/assignment records. This removes the failing responsibility rather than merely making the model retry it.

### 2. High priority: saved specialist output is re-authored during handoff

`finish_analysis` already has the authoritative saved object, but `agents/data_analysis/agent.py:74` asks for another model message containing its ID. A completed save should produce the coordinator's compact receipt directly from code. A receipt needs the assignment outcome, saved analysis reference, named output datasets, a short summary, and any requested clarification or source data.

Use the framework's state/structured-result path to deliver that receipt. A supported mechanism is a tool returning `Command(update=...)`; fields shared across parallel calls need a reducer. See [LangChain tool state updates](https://docs.langchain.com/oss/python/langchain/tools#return-a-command). The installed native task implementation already understands structured responses and state updates, so no new task scheduler is warranted.

Have the completion boundary populate the receipt from the saved record rather than ask the model to generate the receipt's identifiers. Test termination and error recovery with the actual harness: a blanket `return_direct=True` change could also terminate an assignment when validation needs repair.

Make SQL's completion receipt application-owned too. Its current `SQLAnalysisResponse` has one `result_id` despite allowing multiple queries, and includes a model-written `sql` field even though exact executed SQL is already stored (`schemas.py:96`). Return named saved results for multi-result assignments and resolve exact SQL from storage.

### 3. Medium priority: answer completion repeats an already accepted contract

The coordinator is told to publish findings, create a report, and then restate the same `CoordinatorResponse` (`coordinator.py:266`). `RunManager._consume` requires that final structured response before choosing `run.findings` over it (`run_manager.py:336`). Therefore another formatting error can prevent completion after the accepted answer and report already exist. The prior live-smoke review records this failure class and a retry workaround.

Persist the selected answer/evidence once. After successful report attachment, finish deterministically from that saved answer, subject to existing correction/cancellation checks. Keep the separate findings/report phases because they preserve usable findings when rendering fails. Remove the redundant model-generated final copy for the data-backed path; retain an appropriate direct response path for greetings and metadata-only questions.

Report generation already attaches missing published analyses/charts (`reporting/tools.py:33`). Extend this existing ownership rather than require several independently maintained copies of the same evidence list. The agent can still choose layout, explanatory text, and which evidence is material.

### 4. Medium priority: failure recovery can lose the context of successful work

When assembling a new turn, `RunManager.start` skips a prior run if it has neither a completed turn nor published findings (`run_manager.py:69`). That is exactly the state of this incident. Saved result/analysis discovery still exists, but the new turn is not automatically told what successful work belongs to the failed request. Charts have no equivalent coordinator discovery tool.

Supply a compact continuation record for failed/partial assignments: original objective, outcome, committed evidence receipts, remaining step, and error. Distinguish resuming a checkpoint from repairing model arguments; replaying a deterministic bad call is not a repair strategy.

Use run and assignment ownership when collecting receipts. Do not infer ownership by comparing a conversation-wide artifact list before/after a task: parallel assignments would contaminate each other's results. Python already has an assignment ID; dataset metadata currently lacks a general creating-run/assignment field (`schemas.py:174`). Add only the provenance needed for reliable collection, using the existing stores/commit mechanism.

### 5. Medium priority: planning and evidence bookkeeping overlap

Complex work currently maintains todos, an investigation summary, run events, published findings, report specifications, and a final answer. Some serve separate needs, but making the model synchronize artifact lists across them creates unnecessary work and failure opportunities.

Keep todos as the user-facing plan and a compact narrative for unresolved analytical context. Derive evidence inventories from saved records. Keep one selected-evidence record as the publication/report authority. `resolve_answer` and `generate_report` also duplicate lineage traversal and artifact resolution; a shared, scoped resolver would reduce drift without requiring a generic artifact framework.

Coordinator routing/reporting policy is substantially repeated between `AGENTS.md` and the assembled system prompt. Consolidate those instructions once the ownership changes land. Preserve specialist-specific instructions and measure behavior on the existing routing/clarification/recovery cases.

### 6. Lower priority: inspection returns more execution detail than synthesis needs

`DataAnalysisResult.model_facing()` includes every execution, and `PythonExecutionResult.model_facing()` retains executed code, stdout, and stderr (`agents/data_analysis/schemas.py:59`). `finish_analysis` and coordinator inspection use that representation. This repeats information needed for the specialist's repair loop in a context where the coordinator usually needs conclusions, scope, assumptions, diagnostics, and artifact references.

Use a compact completion/inspection view by default, retaining code and detailed outputs in the existing inspection paths. This is a context-efficiency recommendation; this review did not benchmark token or latency savings.

## Proposed minimal ownership model

Keep the coordinator and its two specialists. Keep current evidence storage. Add a small typed receipt at existing save/completion boundaries, not a new registry service or orchestration framework.

The flow should be:

`execute and save → code records scoped receipt → agent selects relevant evidence → code resolves selected evidence → publish once → render report → finish from saved publication`

Persist receipts and merge parallel updates by stable identity so checkpoint replay is idempotent. Do not use a single mutable “latest artifact” pointer or blindly append duplicates. Expose short, typed, scope-bound handles where models need to select evidence, with the application resolving them to canonical IDs. Short handles improve ergonomics but still require existence/type/scope checks.

Automatic collection identifies available evidence; it must not automatically publish every historical or intermediate artifact. The coordinator still decides relevance, and explicit prior-snapshot reuse must preserve original source, population, dates, completeness, and lineage.

## What to retain

- SQL-only warehouse access and Python-only analysis over saved inputs.
- Conversation/source checks, reviewed upload schemas, truncation checks, and immutable lineage.
- SQLite product metadata, LangGraph checkpoints, and Parquet datasets: these serve different purposes.
- Native task/checkpoint machinery and bounded parallel Python assignments. The confirmed incident does not justify replacing them.
- Separate findings and report recovery, cancellation, approval handling, and accepted-correction checks.
- The declarative chart/report renderer. A new rendering agent or arbitrary generated dashboard code would not address this failure.

A lighter specialist harness may be worth a later measured experiment. It is not needed to fix artifact handoff, and replacing the framework now would expand risk without evidence of benefit.

## Delivery and verification

First remove model-owned investigation IDs and make remaining reference-selection errors recoverable. Next establish application-owned specialist receipts and failed-run continuation. Then remove repeated final-answer generation and consolidate evidence resolution/instructions. Remove superseded paths as each change becomes complete; do not retain compatibility modes.

Add regressions that exercise the real harness for:

- A malformed chart selection yielding recoverable feedback, followed by successful publication/reporting without repeating computation.
- Investigation notes saving without a model-provided artifact list.
- Two simultaneous assignment receipts remaining distinct, including replay and colliding model tool-call IDs.
- Same-source historical reuse succeeding while foreign conversation/source references remain rejected.
- A failed pre-publication run resuming synthesis from committed analyses/charts.
- Successful report attachment completing from stored findings without a second model-authored answer.
- Invalid saved-SQL and analysis-inspection references remaining recoverable.

Verification performed in this review: 36 targeted tests passed across agent workflow, parallel analysis, persistent analyst, checkpoint resume, and run manager suites. The isolated investigation reproduction failed on the mistyped ID and succeeded on the correct one as described above. No new live model runs, source queries, model-quality benchmark, or production-history repair was performed.


## Implementation completed — 21 September 2026

The six prioritized findings are addressed:

1. Removed model-supplied artifact IDs from investigation notes. Unknown dataset and analysis references now produce repair feedback; publication errors identify the invalid reference and include chart discovery as a recovery path.
2. Added application-owned assignment records in the existing run store. SQL returns interpretation only, with code attaching all saved/inspected dataset references. Python completion automatically attaches its own executions and inputs and returns the saved analysis through graph state without another model message. Both SQL and Python journal keys include assignment identity. Parallel receipts remain isolated and repeated saved calls reuse their results.
3. Published findings are the authoritative answer/evidence selection. Reports reject unselected references and automatically include published charts/analyses. Successful report attachment ends the coordinator through middleware, and the run manager completes from saved findings without requiring a duplicate final response. Direct metadata-only answers retain their structured response path.
4. New turns receive failed-run objectives, saved assignment receipts, chart references, and compact execution summaries, including after store restart. A chart discovery tool recovers exact scoped IDs. Newly accepted corrections invalidate an older completed assignment receipt before it can end the specialist automatically.
5. Added one scoped evidence resolver shared by publication and reporting, including parent lineage. Consolidated coordinator policy in AGENTS.md and retained a short operational prompt. Investigation notes remain narrative context; code owns inventories and saved completion state.
6. Analysis synthesis/inspection omits executed code, stdout, and stderr while retaining conclusions, methods, assumptions, bounded analytical outputs, and dataset references. Full execution records remain available to application inspection and provenance.

No additional agent, registry service, workflow engine, dependency, compatibility mode, or artifact-ID alias layer was introduced. Canonical IDs remain available for evidence selection; those selections retain strict validation and recoverable errors. The SQL/Python tool boundaries, source/conversation isolation, exact approval edits, cancellation, immutable lineage, and separate findings/report recovery remain intact.

Verification: **255 offline tests passed; six live tests were deselected**. Ruff F checks and whitespace checks passed. Added regressions cover a real-harness chart-ID transcription failure repaired through discovery without recomputation; automatic specialist/report completion; isolated assignment receipts and repeated call IDs; saved-snapshot reuse; foreign chart rejection; failed-run continuation after restart; correction invalidation; and rejecting report evidence outside the published selection.

An existing Streamlit test expected a collapsed report preview although the committed UI uses an expanded preview. Its expectation and name were updated to match the existing behavior; production UI behavior was not changed. No live model calls, source refreshes, or saved-conversation repairs were performed.
