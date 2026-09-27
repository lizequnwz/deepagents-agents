# Data analytics agent review — 26 September 2026

The current design should be evolved rather than replaced. Its strongest features are explicit semantic definitions, SQL/Python separation, saved evidence, application-owned artifact receipts, and completion immediately after a successful report. The changes in this review address concrete discovery noise and response duplication, and add file-based voice transcription using the existing Streamlit/FastAPI/OpenAI stack.

Baseline: `903fb351b50222688d252b31662e9c656b5a1576`. No security-hardening or SQL-validation redesign was undertaken.

## End-to-end implementation

1. `streamlit_app.py` loads health/source information and conversation history through `ui/api_client.py`. Native chat input supports text and one file attachment. Files create an isolated conversation and wait for schema confirmation; configured sources bind a conversation to one warehouse.
2. `api.py:Services` owns the stores, source catalog, backend instances, cached semantic catalogs, compiled source-bound agents, and run manager. Readiness loads OSI YAML, binds expressions, and inspects the declared physical schema. Catalog changes require a restart.
3. `RunManager` drives the Deep Agents graph, persists activity and checkpoints, handles stop/resume/review/clarification, and separates analysis and report budgets. Run IDs own checkpoints; conversation IDs scope reusable evidence.
4. `coordinator.py` installs SQL and Python specialists, publication/report tools, chart tools, and planning/delegation middleware. Metadata-only discussion can finish directly; a data-backed answer publishes evidence and generates HTML.
5. `text_to_sql/agent.py` receives full definitions if the complete catalog fits the 12,000-character budget; otherwise it receives an overview and discovery tools. It owns exact semantic grounding, SQL, descriptive calculations, category lookup, and saved-data reshaping. `semantic_context.py` expands metric dependencies, selected fields, keys and declared join paths.
6. Source SQL and saved-result DuckDB queries produce typed Parquet datasets, compact previews and complete stored-row profiles. SQL's assignment receipt attaches the datasets deterministically. Python receives saved dataset IDs, executes isolated processes, persists derived datasets, and finishes through an application-owned analytical receipt.
7. `publish_findings` resolves selected evidence and transitive lineage through `EvidenceResolver`. Reports bind numbers to saved cells and attach published charts/analyses. `ReportCompletionMiddleware` ends successful data-backed turns without another model-written answer. API/UI models expose the stored evidence and execution diagnostics.

This means a large `FinalAnswer`, `RunResponse`, or `DataAnalysisResult` schema is not automatically a large LLM structured-output burden. The relevant question is which boundary generates each field.

## 1. Semantic discovery

### What already works

The entire YAML stays in application memory. Large catalogs are not blindly injected into every SQL prompt. Discovery has independent metric/dataset/field/time quotas, two field candidates per dataset, bounded descriptions, and no claim of complete question coverage. Exact resolution includes selected fields, metric operand dependencies, primary keys, bridge datasets and join keys rather than every column on a selected table.

Relationship discovery is already stronger than ordinary table search: declared paths are inspected, alternative routes are exposed, self-joins are retained, and the agent must resolve ambiguity. Cache identity includes catalog version, source, dialect and projection. Small models can avoid discovery altogether through complete inline definitions.

### Concrete weaknesses and changes

| Previous behavior | Consequence | Implemented change |
|---|---|---|
| Candidate search appended the parent table description to every field description | A table description mentioning chargebacks made every unrelated column a chargeback match | Fields are indexed using their own names, synonyms and descriptions; a parent name can only boost an already relevant field |
| Fixed overlap tiers, many alphabetical ties, no corpus term rarity | Common words could crowd out a rare discriminative business term | Cached TF-IDF unigram/bigram ranking with exact-name/synonym priority and phrase boosts |
| Browsing and candidate discovery used different field descriptions/scorers | A concept could appear in one tool and disappear or reorder unexpectedly in the other | Both use `SemanticCatalog.search_index` |
| Every query normalized all metadata again; discovery ran separate searches per role | Repeated CPU work on thousands of fields | Normalize/index once per catalog; one ranking pass supplies the four candidate quotas |
| Browsing materialized definitions before paging | Thousands of dictionaries were built to return a small page | Retain entity identities and construct field/metric/dataset payloads only for the requested page |
| Large-model overview filled up with an alphabetical table prefix | Repeated prompt tokens conveyed arbitrary tables and could crowd out metrics | Models with more than 25 tables receive counts, global orientation and discovery guidance rather than a prefix |
| Prompt language prescribed separate searches even after useful candidates were returned | Could induce redundant tool/model turns | Resolve sufficient candidates directly; browse only missing/ambiguous roles, scoped by dataset |

The implementation uses scikit-learn, which was already a project dependency. No embedding provider, vector database, extra LLM classifier, or retrieval framework was added. Exact SQL definition/relationship behavior remains unchanged.

### Target discovery sequence

Use the existing source as the domain boundary. Discover candidate metrics and tables/fields in one pass. The field-first path remains available because table descriptions can be weak even when a field description is excellent. Once a table is plausible, browse its grouping/filter/time fields with `dataset_name`. Resolve exact selections once, including metric dependencies and required relationship paths. Ask for additional metadata only when a business role or route is unresolved.

Do not enforce a hard domain → table → column funnel: the OSI loader has no curated domain hierarchy, and an incorrect early domain/table choice would suppress the correct column. Introducing domain taxonomy or a model call to invent it is not justified here.

For example, “monthly revenue by genre” still requires distinguishing invoice-level revenue from line revenue and choosing an invoice date. A lexical question may have no date match for “monthly.” The prompt now explicitly instructs the specialist to browse declared time fields with an empty query within the relevant dataset. Retrieval must not silently interpret missing time candidates as proof that the question is grounded.

### Evidence and limits

The checked-in [benchmark script](semantic-retrieval-benchmark-2026-09-26.py) reproduces the pre-review scorer from Git and compares a controlled 300-table, 12,001-column fixture. The only relevant column is `dataset_299.dispute_amount`; every table has a chargebacks description, but its other fields do not.

| Measurement | Before | After |
|---|---:|---:|
| Correct column in first six field results | No | Yes, first |
| Median warm field-search time, 10 repeats | 102.034 ms | 13.099 ms |
| Initial index creation and first lookup | No index | 1,559.729 ms |
| Updated large-catalog overview | — | 885 characters |

The first lookup includes importing the retrieval library. Timings are local descriptive measurements, not latency guarantees. [Raw results](semantic-retrieval-benchmark-2026-09-26.json) are saved. Regression tests also cover exact names/synonyms, rare terms, browse/discovery agreement, paging, dataset/date scope, dependency expansion and join-path behavior.

This is not a measured general SQL-accuracy improvement. Remaining limitations are explicit:

- Lexical search does not recognize every unstated synonym, language, spelling variation or business abstraction. “Revenue by country” still exposes customer, billing and employee country candidates; semantic selection remains necessary.
- Fixed six-candidate quotas may miss secondary concepts in long multipart questions. Progressive role-specific browsing remains necessary.
- Character budgets do not guarantee token budgets, and tool responses accumulate across turns.
- Large indivisible instructions/definitions can still exceed the exact-context budget. Narrower selections help only when the oversized unit itself is not the problem.
- Relationship search can hit its work cap in dense graphs. Choosing the shortest path automatically would hide business ambiguity rather than solve it.

Before introducing embeddings, create a held-out question set covering the actual production catalog: required metrics/tables/columns, alternate join/date roles, expected clarification, and reviewed result semantics. Compare the new lexical baseline against lexical-plus-embedding retrieval under equal context budgets. Measure required-entity recall, irrelevant context, clarification accuracy, final result correctness, total metadata tokens, tool/model calls, cold/warm latency and cost. Preserve lexical exact matches in any hybrid design. Relationship expansion should remain deterministic after selection.

The adopted pattern is consistent with [LlamaIndex's table retrieval guidance](https://docs.llamaindex.ai/en/stable/examples/pipeline/query_pipeline_sql/) and the emphasis on curated names/descriptions/synonyms in [Snowflake Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst). These are design references, not evidence that adding either product would improve this agent. TF-IDF behavior follows the existing library's [documented vectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html).

## 2. Response and Pydantic contracts

### Implemented target

```python
class SQLAnalysisResponse:
    answer: str
    assumptions: list[str]

class CoordinatorResponse:
    answer: str
    assumptions: list[str]
    result_ids: list[str]       # ordered, first is primary
    analysis_ids: list[str]
    chart_ids: list[str]
    partial: bool
    unresolved_questions: list[str]
```

Lists and `partial` retain their defaults. The coordinator goes from nine fields to seven; SQL goes from three to two. `answer` includes business interpretation. There is no separate `interpretation` field in SQL, coordinator, analytical findings, final answers or resolved report inputs.

`ChartRequest` contains model-authored chart choices. `ChartSpec` extends it with application-generated `chart_id`, `source_result_id`, and `version`. This removes three irrelevant fields from the chart tool's model-facing schema while preserving all supported chart capabilities. `previous_chart_id` remains an explicit model choice for revisions. The unused ten-field `ReportBrief` model was removed; it had no production consumer.

### Field ownership review

| Component/fields | Should the LLM generate it? | Decision |
|---|---|---|
| Answer/business interpretation | Yes | One `answer`, remove duplicate narrative field |
| Assumptions, method, analytical warnings | Yes, when material | Retain: semantic/statistical meaning cannot be reliably inferred from executed code |
| Partial status, unresolved questions, analytical outcome/requested data | Yes; runtime may also mark budget exhaustion | Retain: empty unresolved questions do not prove completeness |
| Selected result/analysis/chart IDs | Yes | Retain minimal references: not all saved diagnostic evidence should be published |
| Primary/supporting result split | No separate field needed | One ordered `result_ids`; derive primary and deduplicate through evidence resolution |
| SQL result receipts, exact SQL, labels, lineage | Application | Already application-owned; preserve authoritative saved values |
| Analysis ID, execution IDs, inputs/outputs, code, logs, elapsed time | Application | Already attached by `finish_analysis`; do not make the model copy these |
| Chart ID, version, original source ID | Application | Separate from `ChartRequest`; tool assigns these |
| Chart type, columns, title, labels, intervals and declared meaning | Model choices | Retain; distinguish confidence from prediction/scenario ranges |
| Profiles, counts, missingness, representative values, truncation, physical types | Application | Retain stored facts; do not move them into generated findings |
| Run state, diagnostics, checkpoint/assignment IDs, corrections and review state | Application | Keep internal models separate; flattening them into a final answer would make ownership worse |
| Report title, narrative and presentation blocks | Model choices | Retain declarative report specification and its defaults |
| Report ID, hash, path, version, creation time, resolved chart/analysis payloads | Application | Already deterministic; retain generated artifact/reference models |
| `ReportBrief` | Nobody in the production workflow | Remove unused intermediate model |

`FinalAnswer` remains an application-resolved view with selected results, charts, analyses and report. Its nested execution information supports inspection and persistence; it is not the provider's structured response. Similarly, `RunResponse.findings` supports early publication while `answer` represents completion. Do not collapse those different lifecycle states merely to reduce field count.

The same compact coordinator contract remains usable for metadata-only answers and publication. A separate one-field greeting schema would remove optional fields but add another response type/routing boundary; there is no evidence that this is necessary. The report's `report_json` is still validated into `ReportSpec`, loaded through the reporting skill on demand. Flattening its discriminated blocks would weaken a useful contract.

Potential later work: chart-type-specific request variants could reduce irrelevant options further; lazy-loading execution details could reduce large API payloads. Neither addresses a demonstrated LLM correctness failure here, so neither was mixed into this change.

### Breaking change

This is API contract 14. Both services must restart together. Old persisted records containing removed fields are not migrated or silently accepted. Storage lives directly in `ANALYTICS_STORAGE_DIR` (default `.analytics/`), without a versioned subdirectory. The user manually cleared the incompatible history. Future breaking persisted-schema changes require empty storage or a fresh configured directory, consistent with the repository's prohibition on compatibility layers and migrations.

## 3. Voice-to-text input

The UI now uses `st.audio_input` beside the existing file/text composer inside `st.bottom`. Desktop shows adjacent controls; narrow layouts stack them. The native component handles recording, stop, permission prompts, browser capture and 16 kHz WAV encoding. Using `st.chat_input(accept_audio=True)` would require an audio submission before transcription; the separate native recorder delivers the requested stop → transcribe → edit sequence directly.

On stop:

1. Streamlit sends WAV bytes through `AgentAPIClient.transcribe` to `POST /api/transcriptions`.
2. FastAPI calls `AsyncOpenAI.audio.transcriptions.create`, defaulting to `whisper-1` through `TRANSCRIPTION_MODEL`.
3. The endpoint returns only `{"text": "..."}`. It creates no conversation, run, dataset or report.
4. The UI inserts the transcript into the same question widget. It does not submit it. The user's later Send action follows the original workflow, including clarification or correction of an active run.
5. Success resets the recorder and releases the old recording widget. Audio is never written to disk by the application.

The LangChain `whisper_transcriber` runnable uses an async SDK transport with the existing `OPENAI_API_KEY` and optional `OPENAI_BASE_URL`; the latter must provide a compatible transcription endpoint. Bedrock analytics can still use this transcription service with an OpenAI key. OpenAI is now an explicit direct dependency at the already-installed version; the lockfile changes only dependency declarations.

A spinner indicates transcription. Empty input, no recognized speech, missing credentials, provider authentication errors, timeouts, provider failures and oversized recordings return user-presentable errors. Failed recordings can be retried explicitly; rerenders do not trigger repeated paid requests. A 24 MiB request limit fits the file-transcription path; provider timeout is 60 seconds with implicit retries disabled. Microphone use requires localhost or HTTPS and browser permission. Dictation replaces the input's text; it does not concatenate with an unsent draft. The recording remains retryable in UI memory after a failure until replaced/cleared or the conversation changes.

This follows Streamlit's installed native recorder and session-state APIs and OpenAI's [file transcription API](https://developers.openai.com/api/docs/guides/speech-to-text). No realtime voice agent, websocket service, audio converter, frontend framework or temporary-file cleanup service is required.

## Verification

- Full deterministic suite: **296 passed, 6 skipped**, 56.74 seconds. The six skips are the explicitly opt-in provider/live suites.
- Final focused rerun after consolidating discovery into one ranking pass: **54 passed**.
- Ruff unused-name/import checks pass; `git diff --check` passes.
- New discovery tests exercise 300 tables/12,001 columns, rare terms, exact-match preservation, consistent browsing and pagination.
- Existing real-harness scripted-model tests cover SQL, uploads, Python assignments, reports, correction/retry and checkpoint workflows. These are deterministic integration tests, not live model accuracy trials.
- New transcription tests cover SDK request/cleanup, endpoint isolation, missing key, empty speech/input, size limit, timeout/provider error, insertion without submission, editable text, explicit retry, and no retry on unrelated reruns.
- Browser layout inspection at 1100 × 800 and 375 × 812 confirmed visible Record and Send controls, editable question input, desktop adjacency and narrow-screen stacking. The temporary preview server was stopped.
- A physical microphone recording and a live transcription-provider request were **not** performed. General end-to-end SQL accuracy improvements and production latency remain unmeasured.

## Startup and transcription follow-up

The initial clean-storage tests missed startup against old persisted conversations.
After the user manually cleared incompatible history, storage was restored to its
original directory layout. A regression runs the actual `api:app` import and lifespan
in a separate process with current-schema history present. It verifies direct use
of the configured directory, successful startup, conversation persistence across
restart, and preservation of saved artifacts.

Whisper now runs through LangChain RunnableLambda, with model binding, callbacks,
and native async invocation. Tests cover its framework integration and cancellation
cleanup in addition to provider and UI behavior. The installed community Whisper
loader was inspected and rejected for this short-recording use case because it adds
MP3 conversion/codecs and hides provider errors after retrying.
