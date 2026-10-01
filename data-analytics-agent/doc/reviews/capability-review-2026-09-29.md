# End-to-end capability and usability review

29 September 2026 · reviewed base commit `7faeaca`

This is the assessment **before** the 30 September release. Excel intake,
portable bundles, notebook export/replay and the identified contract cleanup are
now delivered; see [release verification](release-verification-2026-09-30.md).
Dedicated execution isolation was subsequently deferred by the user. The
[handoff](../../HANDOFF.md) and [roadmap](../roadmap/roadmap.md) supersede this
review's proposed delivery order. Other findings remain review-time observations,
not current delivery claims or competitive accuracy results.

## Judgment

This is already a functioning, persistent analytics agent with genuine iterative Python execution. Its strongest design is the chain from a business question to scoped SQL, typed saved datasets, analytical code, shared charts, published findings, and a reproducible HTML report. Preserve that chain.

It is not yet a broad analytics coding workspace. The largest practical gaps are spreadsheet intake, explicit scope manipulation, portable analytical work, safe execution isolation, and measured analytical reliability. Adding Bash, a persistent kernel, more agents, or an embedding service would not automatically close those gaps.

The recommended product is a **business-facing analyst with inspectable, exportable code**, supporting one governed warehouse or one reviewed file source per conversation. Analysts can inspect and reproduce its work; business users can complete the workflow without programming. A full notebook IDE, arbitrary development environment, multi-user enterprise platform, and autonomous ML operations are different product commitments.

There is no established universal ranking that identifies the world's best analytics agent across file analysis, semantic SQL, forecasting, notebooks, governance, and usability. The comparison below uses documented leading capabilities, not a claimed competitive accuracy result.

## Evidence and limits of this review

Inspected the coordinator, both specialists, execution worker, upload path, semantic discovery and validation, saved datasets, approvals, evidence/reporting, charts, run lifecycle, Streamlit presentation, configuration, evaluation scripts, fixtures, tests, and current roadmap. Read current primary product/library documentation for comparison.

Local verification:

- Full deterministic suite: **327 passed, six skipped**, 58.72 seconds. The skipped tests are provider/live tests, not passes.
- Ruff unused-import/name checks passed across application, UI, tests, and scripts.
- A harmless worker probe successfully read a temporary sentinel outside its working directory and launched a child Python process. The probe used only review-created temporary files. Socket APIs were available; external networking was not tested.
- A Plotly figure is rejected by the statistical worker's compact output contract. Interactive Plotly charts are supported through the separate shared-chart path.
- Ten documented examples and four held-out cases are present. The four held-out cases focus on descriptive SQL, grain, and ambiguity, rather than broad statistical robustness.
- `openpyxl` and `python_calamine` are absent from this installed environment. `nbformat`, `nbclient`, IPython, and ipykernel are installed, but there is no agent notebook execution interface. Jupyter-related packages are development dependencies or their transitive dependencies.

The review made no live model calls, ran no paid competitive trials, and did not run a new browser usability study. Deterministic integration tests include real harness wiring with scripted models and real Python computation; they do not establish unrestricted model accuracy. Product documentation establishes advertised features, not their comparative quality.

Several local documents cite `documentation-live-tests-2026-09-26.md`, `roadmap-implementation-2026-09-27.md`, and related dated receipts that are absent from this checkout. Therefore their reported live outcomes cannot be independently inspected here. The implemented comparison code and current deterministic tests can be verified independently. Restore the referenced evidence or qualify/remove unsupported delivery claims.

The compact [review evidence record](capability-review-evidence-2026-09-29.json) records local checks and probe limitations. Application source was not changed for this review.

## 1. What the system can do today

| Stage | Current capability | Practical limit |
|---|---|---|
| Intake | Configured SQLite/Snowflake sources, or isolated CSV/Parquet upload; native chat attachment and voice draft | One source or file per conversation; no Excel ingestion; CSV is UTF-8 with a header and comma-oriented parsing |
| File understanding | Explicit type review, grain description, declared key validation, missing/distinct counts, immutable original and reviewed snapshots | Structural review is not business semantics; types cannot be revised in place; units and important business definitions are usually clarified conversationally |
| Warehouse grounding | Curated OSI catalog, exact definitions, lexical discovery, relationship/date-role discovery, actual category lookup | Lexical retrieval can miss vocabulary absent from metadata; catalog authoring is still required |
| SQL | Read-only structural validation; declared objects/fields/joins and metric expression checks; descriptive queries and DuckDB reshaping | Validation covers particular query forms, not every semantic error or possible source fan-out |
| Python | Arbitrary Python statements using installed libraries, execution feedback, repair, multiple successful steps, named saved inputs and derived DataFrames | Fresh process each step; no persistent objects, project editing tools, or general file-output contract |
| Analysis | EDA, inference, regression/classification, anomalies, trend/seasonality and forecasting are feasible with pandas, SciPy, statsmodels and sklearn | Broad methodological guidance and flexible code, not a demonstrated reliability guarantee for all these tasks |
| Charts | Nine shared chart types, interactive Plotly, labeled intervals, immutable revisions and direct presentation edits | Closed chart schema; no linked selection-to-question action; general Python Plotly/HTML output is unsupported |
| Findings/report | Findings published before rendering; metrics bound to saved cells; required standalone HTML; charts/analyses attached; retry without recomputation | Narrative numbers and causal/statistical claims are not all deterministically verified |
| Recovery | Durable conversations, artifact lineage, checkpoints, Stop/Resume, exact code review, corrections, partial reporting | Single local user/API process; blocking source cancellation is cooperative |
| Evaluation | Deterministic regressions, opt-in live fixtures, reproducible example runner, source fingerprints and explicit grading rubric | Live statistical tests partly check terminology and execution count; coverage and available receipts do not establish frontier-level accuracy |

### What should remain

The source execution boundary is useful: only text-to-SQL has warehouse tooling. Python consumes explicit saved inputs. This reduces accidental source switching and makes SQL/Python outputs traceable.

Typed Parquet, immutable evidence, complete-population checks, exact executed code, report recovery, and shared chart specifications are substantive capabilities. They are not incidental architecture to remove merely because the module count looks large.

Likewise, diagnostic Matplotlib figures and shared Plotly charts serve different purposes. The former support modeling inspection; the latter keep chat and report presentation consistent. Two supported purposes do not require two competing publication systems.

### Already implemented, not future recommendations

Direct chart edits, deterministic report-title revisions, native attachments, plans, bounded parallel analytical assignments, compact application-owned receipts, lexical retrieval improvements, explicit interval labels, and checked same-snapshot KPI comparisons are already present. The existing roadmap's first three increments have code and tests. Further recommendations below extend their limitations rather than propose rebuilding them.

## 2. Comparison with leading documented capabilities

| Reference | Capability worth adopting | Current position and recommendation |
|---|---|---|
| OpenAI Code Interpreter | Iterative Python in a sandbox, file processing, generated downloadable artifacts | Iterative coding already exists here. The larger gaps are enforced isolation and a richer artifact export surface. Do not replace the current runner solely to obtain a Python tool. [Official documentation](https://developers.openai.com/api/docs/guides/tools-code-interpreter) |
| Hex Notebook Agent | Generates/edits notebook cells; uses project code, outputs, schemas, and explicit cell/table references | This project is substantially narrower as an analyst workspace. Start with dataset references and portable notebooks; a full collaborative notebook UI is a later product decision. [Notebook Agent](https://learn.hex.tech/docs/explore-data/notebook-view/notebook-agent) |
| Hex Threads | Distinct conversational experience over curated data for nontechnical users | Supports keeping the business chat as the default, with code inspection available when needed. Avoid forcing all users into notebooks. [AI overview](https://learn.hex.tech/docs/getting-started/ai-overview) |
| Databricks Genie Code | Plans, creates notebook code, executes cells, examines outputs, repairs code under user permissions | The local agent has the iteration loop but lacks editable notebook context and the integrated governed compute workspace. Borrow inspectable execution and evaluation patterns, not an entire enterprise stack. [Data science workflow](https://docs.databricks.com/aws/en/notebooks/ds-agent) |
| Snowflake Cortex Agents / Analyst | Semantic SQL plus structured/unstructured tools, sandboxed Python, monitoring, feedback and evaluation; reviewed question–SQL examples | Semantic grounding is a relative strength here. Improve tested coverage, reviewed examples and execution isolation. Unstructured research is a later scope expansion. [Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents), [verified queries](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository) |
| Julius | File-first Python analysis and broader upload/download formats including Excel | The local file path excludes common business inputs and exports. Excel intake and usable analytical downloads have immediate relevance. Its advertised breadth is not evidence of higher analytical accuracy. [Start guide](https://julius.ai/faq/chat-start-guide), [downloads](https://julius.ai/faq/how-to/guides/download-data) |

The frontier is not a list of tools. A capable analytics agent must understand the requested population and business meaning, obtain sufficient data, choose defensible methods, inspect results, correct failures, reconcile its answer with saved evidence, and let users refine/reproduce the work. This system has much of the foundation. Its next improvements should make those outcomes easier to obtain and measure.

## 3. Highest-value capability and usability gaps

### A. Reliability needs broader outcome evidence

The presence of sklearn and forecast instructions does not prove that generated models avoid leakage or produce calibrated uncertainty. `finish_analysis` requires a successful execution for completion, but execution success cannot establish analytical validity. Some opt-in statistical checks search generated receipts for terms such as baseline, holdout, and uncertainty. These are useful smoke checks but insufficient correctness judges.

Extend the existing runner and grader, rather than build a new evaluation service. Add roughly 25–40 representative cases, with independent expected values or defensible method rubrics. Include duplicates/fan-out, ratios and weighted measures, ambiguous date roles, unknown completeness, missing categories, zero baselines, uploaded identifiers, temporal leakage, grouped repeated observations, short/noisy series, structural breaks, class imbalance, forecast intervals, failed-code repair, and scope-changing follow-ups. Compare at least two configured models on the same corpus; today the same model object serves all three roles, and the default is `gpt-5.6-luna`. Do not introduce an automatic model router before a measured need.

Record correctness, inappropriate certainty, correct clarification, first-attempt repair rate, time to usable findings, total time, model/tool calls, cost, and report agreement. Human-reviewed statistical interpretation remains necessary. Test cases must grade computed outcomes and split boundaries, not merely prose keywords.

### B. Source meaning and coverage need compact durable facts

Current units/completeness guidance is appropriately conservative, but repeated free-text disclosure is difficult to validate. Add only the facts that recurring failures require: reviewed measure meaning/unit, row grain, source/as-of statement, requested time window, and an explicit completeness statement when supplied. Unknown must remain a valid value.

Do not generate an OSI semantic catalog from arbitrary spreadsheet column names. Store reviewed file context alongside the upload and retain the distinction between physical types and business definitions. Do not infer currency from a name such as revenue or completeness from the last transaction date.

The comparison contract already checks saved rows, dimensions, periods, units, denominators and canonical bindings where available. However its `population` is free text, `completeness` currently permits only unknown, and derived data may lack a verified metric binding. These checks cannot prove a warehouse filter or detect all previously inflated aggregates. Make these limits visible. Before cross-snapshot comparisons or refresh, add a small scope record bound to actual source/result lineage; do not create a general semantic algebra.

### C. Follow-up scope should be explicit in the interface

There are direct style/title edits and an inspector, but charts do not connect selected data to subsequent questions. Add an explicit **Ask about this dataset** action first. It should send the selected artifact reference and display the requested scope before execution.

Then support a narrow sequence: explicit selected groups/time ranges; shared filters over a complete suitable saved dataset; manual refresh for warehouse-backed analyses. A metric card, chart, table and download must agree on scope. Disallow filtering a coarse aggregate when it cannot answer the requested finer population. Chart display samples must never define the analytical population.

For file sources, a refresh remains a new upload under the existing policy. Multi-file joins or warehouse/file enrichment require an explicit product-policy change. They must not appear as an invisible relaxation of source isolation.

### D. Forecasts need an inspectable evaluation view

The analyst can generate holdout predictions and derived datasets, and intervals have declared meaning. The missing piece is a coherent display of training/test boundaries, baseline and candidate scores, requested horizon, observed versus predicted values, forecast start, and interval methodology/coverage evidence.

Use saved evaluation tables plus a small descriptor and the existing renderer. Add the chart fields needed for actual/forecast series and a forecast-start marker. Keep the analyst free to use appropriate libraries. Do not build a forecasting platform or an algorithm registry.

The same pattern later supports classification/regression evaluation. Common business analyses—cohorts, retention, funnels, segmentation, reconciliation and driver decomposition—can be supported through focused skills/examples and outcome tests. They are possible with current SQL/Python, but not yet independently established as reliable workflows. Driver decomposition explains observed arithmetic or associations; it must not be sold as causal discovery.

### E. Portable work is a coding capability

Users can inspect exact Python and download tables, but cannot receive one self-contained analytical package that reproduces the result. Add a **Download analysis** action containing code, explicitly bound input snapshots, outputs, dependency versions and scope/method notes. This makes the current coding capability useful outside the application.

A selected successful analysis is the default export; earlier failed steps can be included in an optional execution history. Do not silently select every saved artifact or concatenate unrelated assignments. Replay must preserve fresh-process semantics and explicit bindings, rather than accidentally inherit variables from preceding notebook cells.

### F. The analyst cannot visually inspect its diagnostic figures

`AnalysisOutput.model_facing` replaces an image path with `rendered=true`. It does not deliver image pixels to the analyst. Thus generating a residual plot is not the same as examining it visually. Numerical diagnostics remain useful, but the product should not imply image-based inspection that does not occur.

When a concrete visual task warrants it, add bounded inspection of a registered diagnostic image through a model that supports image input. Reuse saved figure IDs and limit image size/count. This need does not justify another chart agent or arbitrary filesystem/browser access. Keep shared published charts in the existing validated chart path.

## 4. Python, Bash and notebooks

### Python: already real, but the execution environment needs improvement

The tool accepts actual code; the worker executes compiled Python with `datasets`, `pd`, `np` and `output_datasets`. It imports installed libraries, returns compact values/tables/Matplotlib figures, saves derived DataFrames and exposes failures for repair. Multiple steps and multiple inputs are supported. It is a real analytics coding agent within this constrained workflow.

Its limitations are specific:

- Each execution rereads all bound datasets into pandas. There is no persistent function/model/object state and no projection-first/lazy input loading interface.
- At least one saved dataset is required, even for a purely synthetic simulation or small calculation.
- Statements use ordinary Python, not IPython cell semantics: no automatic final-expression display or notebook magics.
- Durable outputs are DataFrames and bounded diagnostic PNGs; there is no general registered output-file interface for scripts, workbooks, notebooks or model files.
- There are execution time/output/data limits, but no application-enforced OS filesystem/network boundary or hard working-memory/process quota.

Keep fresh executions initially. They make state and recovery simpler. Measure import/reload/refit overhead before introducing sessions. If repeated refitting or large model objects become a demonstrated obstacle, use short-lived per-assignment state inside an isolated runtime, with durable outputs saved outside that state. Do not adopt an indefinitely running per-conversation kernel as the default.

A small code workspace with editable scripts and an explicit rerun action can reuse the executor and exact-input bindings. It is more valuable than granting host filesystem editing. Fitted-model persistence is demand-led; avoid introducing arbitrary pickle interchange just to preserve objects.

### Execution isolation: a real capability gap

The current subprocess sanitizes environment variables and uses a temporary working directory. Those are useful operational measures, not a security sandbox. The review-created sentinel and child-process probe demonstrate this distinction. Agent filesystem permissions govern framework filesystem tools; they do not contain Python's `open`, imports or subprocess calls.

Before expanding autonomous coding or hosting, replace host execution with one established isolated execution environment: only selected input files mounted read-only, one writable output directory, no service credentials, network disabled by default, and enforced resource/time limits. Keep the current tool and durable artifact contract. For local operation, a single prebuilt container-based executor is a reasonable candidate; select and verify one implementation rather than building a sandbox framework, remote worker fleet, or several fallback runtimes. Consider a hosted interpreter only if its data-location/provider tradeoffs match the product. OpenAI's documented sandboxed interpreter is one design reference, not a recommendation to migrate providers. [Code Interpreter](https://developers.openai.com/api/docs/guides/tools-code-interpreter)

Do not use an import allowlist or AST blacklist as the claimed security boundary. Read-only warehouse tooling and code approval do not substitute for OS isolation.

### Bash: not required for the next product increment

Python, DuckDB and installed analytical libraries cover the core business analyses and Excel ingestion/export. No separate Bash tool is needed for these.

The absence of a Bash tool currently does not imply absence of shell/process access: Python can launch subprocesses. Adding a shell tool would mainly make that ability explicit, not supply a missing mathematical capability.

Add a sandboxed shell only when observed workflows require command-line converters, existing project scripts, tests, or environment diagnostics. It must use the same isolated workspace/resource controls. Host shell access, warehouse credentials and unrestricted package installation are unnecessary. A fixed analytical runtime with declared dependencies is the simpler default; add packages through ordinary product releases when demand is clear.

### Notebook: useful artifact first, optional runtime later

Distinguish four separate features:

| Feature | Value | Recommendation |
|---|---|---|
| `.ipynb` export | Inspectable, portable narrative + code + results | Add after script/bundle export; modest incremental work |
| Fresh-kernel notebook replay | Verifies a notebook can reproduce stored evidence | Add when exported notebooks become a supported deliverable |
| Notebook/cell editor | Lets analysts manually extend and rerun work | Demand-led second-stage analyst interface |
| Persistent interactive IPython kernel | Preserves live variables/models and supports rich cell execution | Defer until measured workflows justify state/lifecycle cost |

Use established Jupyter libraries: `nbformat` creates/validates notebooks; `nbclient` executes them; `ipykernel` provides Python kernels. The existing development environment already includes these capabilities indirectly or explicitly; declare the small subset actually needed in runtime dependencies when adding the feature. [Notebook format](https://nbformat.readthedocs.io/en/latest/), [notebook execution](https://nbclient.readthedocs.io/en/latest/)

An exported notebook must load bundled snapshots using portable paths, retain exact input bindings, explain source SQL as provenance, and reproduce the selected final outputs without API/warehouse credentials. Include seeds where stochastic methods require them and disclose nondeterminism/tolerances. For replay, use a clean kernel in the same isolated environment and preserve the worker's independent step semantics. Failed exploration can remain separate from the successful reproducible analysis.

This makes the product meaningfully more useful as a coding analyst without embedding JupyterLab in Streamlit or supporting two competing execution systems. Hex and Databricks demonstrate the value of notebook collaboration, but copying their entire workspace is not necessary to serve this product's current audience.

## 5. Excel and broader file support

### Excel belongs near the top of the roadmap

Many ordinary business questions arrive as workbooks. CSV-only intake requires users to convert and potentially lose sheet context, identifiers, formulas and units before asking a question. This gap is more directly relevant than Bash.

Build an `.xlsx` path using pandas plus `openpyxl`, rather than a custom parser. `openpyxl` is appropriate for a narrow first release that also needs workbook/sheet/formula inspection. If actual demand later includes `.xls`, `.xlsb`, or `.ods`, evaluate `python-calamine` as one broader reader rather than accumulating separate readers by format. Neither engine is installed here today. [pandas Excel support](https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html)

The smallest complete workflow:

1. Upload one workbook and retain its original bytes/hash.
2. Show available sheets and require the user to select a sheet/table range and header row when unclear. Never silently analyze the first sheet.
3. Show the selected table preview, types and material warnings; let the user confirm the existing schema/grain/key review.
4. Normalize the reviewed table into the existing immutable Parquet path. Reuse SQL, Python, chart and report capabilities.
5. Record workbook, sheet, range/header choices and any explicit transformation in provenance.

One selected worksheet table per conversation is a valid enduring product capability. Later, multiple reviewed sheets from the same workbook can remain one file source while supplying separate named datasets. That extension needs explicit join keys/cardinalities and workbook-level aggregate limits; it should not silently become arbitrary multi-source access.

Correctness details matter more than a file-extension switch:

- Preserve identifier strings and distinguish stored numeric values from Excel display formatting; an integer formatted as `00000` requires a visible interpretation choice.
- Preserve actual dates and workbook date-system handling through the library; clarify textual ambiguous dates.
- Detect formulas and state whether cached values are used. `openpyxl` does not calculate formulas; missing caches must not silently become analytically missing values. Cached values may be stale even when present. Request a recalculated/values-only workbook when this affects the answer. [Formula behavior](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html)
- Do not execute macros, recalculate formulas through a hidden office application, or fetch external workbook links.
- Expose selected ranges, merged headers, subtotal/footer rows and hidden-sheet/row choices. Do not silently fill, deduplicate or remove observations.
- Bound compressed upload size, decoded contents, rows, columns and parsing time. Reject an oversized population rather than analyze a prefix.

Improve review usability without removing explicit confirmation: accept safe suggestions in one action, foreground risky columns, and keep the full schema available. Wide files should not force users to manually choose every safe type. After import, expose declared units/meaning when relevant rather than equating an inferred type with a metric definition.

Next file priorities: `.tsv`/delimited text if requested; flat JSON/JSONL with explicit schema review; additional workbook formats based on demand. Nested JSON needs an explicit flattening choice. PDFs, images and documents require extraction-quality/row-provenance handling and constitute a document-analysis capability, not merely another table loader. Defer that scope until spreadsheet work is reliable. Excel output should follow intake and reuse the registered-artifact/export path.

## 6. Simplification and ablation recommendations

No new live ablation was run, and the available smoke tests are not paired ablations. Therefore there is no evidence-based claim here that an entire specialist or persistence component can already be removed without loss.

### Cleanup justified directly from the code

| Candidate | Evidence | Recommended action |
|---|---|---|
| Debug-details setting and parameter | `agent_debug_details` is passed into `RunManager(debug_details=...)`, but the parameter is unused | Remove the no-op parameter/environment setting and corresponding documentation; do not invent a behavior for it |
| Inactive full-input output guard | `_normalize_outputs` accepts `input_frame`, but its only production call passes `None`; identity/equality rejection cannot run | Remove the dead parameter/branch; keep enforced output bounds and saved full-dataset path |
| Incorrect `df` contract wording | Worker exposes `datasets`, not `df`; Python approval UI and runner docstring still describe `df` | Replace obsolete wording. Show all alias-to-input bindings in review rather than only the first dataset |
| Missing verification references | Current roadmap/review index links to absent live evidence files | Restore the receipts or qualify claims and repair links; do not count missing evidence as passed evaluation |

These are cleanup/contract corrections, not speculative architecture changes. This review recommends them but does not modify application code.

### Behavior changes that need paired experiments

| Experiment | Hypothesis | Adoption criterion |
|---|---|---|
| Consolidate repeated prompt policy | One clear owner per instruction reduces context and contradictions | Same/better correct scope, routing, clarification, recovery and report agreement; fewer calls/repairs |
| Merge SQL and analysis reasoning for file-only tasks | One analyst with saved-data SQL/Python could reduce handoff latency on uploads | Same correct population/business assumptions and report quality; lower end-to-end time/cost. Preserve warehouse execution ownership |
| Serial versus bounded parallel analysis | Parallelism may add little for the actual task mix | Compare complex independent questions, interruptions, costs and time. Default to serial if gains are negligible; do not parallelize simple work |
| Remove unnecessary feature-disable switches | Core analysis/charts may not need multiple runtime product variants | Establish supported deployment requirements first; remove unsupported variants and their branches if no usage depends on them |
| Shorter presentation instructions/spec defaults | Repeated report composition overhead may be reduced without sacrificing agent-authored reports | Preserve required HTML, numerical bindings, narrative quality, chart agreement and recovery while reducing latency/tokens |
| Lexical versus hybrid retrieval | Embeddings may help concepts absent from synonyms | Final SQL/result and clarification improve at equal context budgets; meaningful gain outweighs operations/cost |

Use the existing evaluation runner: identical frozen inputs/configuration, several independent runs per case, paired prompts, and documented model/version. A practical initial batch is 20–30 mixed cases with 3–5 runs per variant; treat those sizes as a diagnostic starting point, not statistical proof. Predeclare what counts as meaningful cost/latency improvement and an acceptable correctness difference. Use paired uncertainty estimates where feasible, retain failures, and make no reduction that breaks hard scope/isolation/report requirements.

Do not add a universal critic agent, several method-specialist agents, a vector database, a generic workflow engine, automatic cross-chat learning, or a distributed executor by default. Start with checks and skills at the existing ownership boundaries. Automatic cross-conversation learning remains outside current scope; a reviewed definition/example can later be saved deliberately and versioned, rather than silently learned from unverified results.

## 7. Sequenced improvement plan

| Increment | Deliverable users can use | Boundaries and completion gate |
|---|---|---|
| 1. Trust and contract cleanup | Accurate review UI, all Python inputs visible, inspectable evidence records, broader outcome corpus | Remove no-op/dead paths; restore/qualify missing evidence. Independent arithmetic/method/scope grades, not completion-only success |
| 2. Isolated execution | Current iterative analysis running in one contained environment | Selected read-only inputs, registered outputs, no service credentials, enforced resource limits; tests prove host/file/network boundaries and Stop/Resume behavior |
| 3. Excel intake | End-to-end `.xlsx` upload → sheet/range review → analysis → report | One selected reviewed table, formula-cache warnings, preserved identifiers/dates, full-population checks and provenance; no macros or workbook recalculation |
| 4. Portable analysis | Downloadable script/data/manifest bundle, then `.ipynb` | Clean-environment replay reproduces selected results within declared tolerance; no warehouse/API credentials required |
| 5. Scope and evaluation workspace | Explicit dataset follow-ups, then shared filters; inspectable forecasts and baselines | Table/chart/metrics/download agree; saved complete evidence reused; splits/errors/interval assumptions are recomputable |
| 6. Measured simplification | Adopt successful prompt/handoff/parallelism ablations | Paired evidence shows lower work/cost/latency without sacrificing hard correctness or usability requirements |
| 7. Demand-led extensions | Same-workbook sheets, Excel export, manual warehouse refresh; optional code editing or image inspection | Each builds on completed contracts. Shell, live kernels, document research, mixed sources and hosted collaboration need a demonstrated use case |

Evaluation work runs alongside each increment. Isolated execution and Excel can be designed independently, but each should land as a working vertical slice. Do not delay all user-facing value behind a large platform rewrite. Existing users can continue the current trusted local workflow while the next slice is tested.

For the next release, commit to increments 1–3 and the first portable script bundle. A reasonable follow-on release adds notebook export/replay and one explicit dataset follow-up action. Full selected-scope filters, forecast workspace and successful ablations follow as independently usable increments. Exact calendar estimates require an agreed team size and implementation scope; this sequence expresses dependencies and value, not an invented delivery promise.

Measure whether nontechnical users can upload/review a workbook, ask a useful question, identify the analyzed population, find a limitation, refine a result, and download usable work. Measure analyst users' ability to trace and reproduce calculations. Time to those outcomes is a better usability target than the number of available tools.

## 8. Implementation touchpoints

| Recommendation | Existing ownership boundary |
|---|---|
| Python isolation and resource controls | [`runner.py`](../../data_analytics_agent/agents/data_analysis/runner.py:171), [`worker.py`](../../data_analytics_agent/agents/data_analysis/worker.py:226) |
| Exact named input review | [`approvals.py`](../../data_analytics_agent/approvals.py:137), [`ui/components.py`](../../data_analytics_agent/ui/components.py:1772) |
| Excel normalization and provenance | [`uploads.py`](../../data_analytics_agent/uploads.py:169), [`ui/uploads.py`](../../data_analytics_agent/ui/uploads.py:39), existing upload API |
| Notebook/script export | Stored `PythonExecutionResult`, selected `DataAnalysisResult`, result store and artifact/download API |
| Outcome evaluations | [`test_live_evaluations.py`](../../tests/test_live_evaluations.py:118), documented/held-out fixtures, existing evaluation runner and [`grader`](../../scripts/grade_documented_examples.py:23) |
| Typed meaning/scope and comparison limits | [`PeriodComparison`](../../data_analytics_agent/reporting/comparisons.py:13), result/upload metadata and evidence resolver |
| Visual diagnostic inspection | [`AnalysisOutput.model_facing`](../../data_analytics_agent/agents/data_analysis/schemas.py:38) and registered figures |
| Shared follow-up scope | Existing dataset inspector, chart rendering, presentation edits and run-creation API |
| Prompt/handoff ablation | [`coordinator.py`](../../data_analytics_agent/coordinator.py:116), specialist prompts/skills and delegation middleware |

One small correction to documentation of profiling: stored counts/distinct values/ranges are computed over full saved rows, while temporal/role inference reads at most 100 non-null observations per column. Those sampled role suggestions should remain labeled as inference rather than certified full-population semantics. Wider-source performance should be measured before optimization; profiling performs per-column aggregate work.

Long conversations rebuild earlier answer/result references in `RunManager.start`. Monitor context size and follow-up accuracy before adding another memory architecture. Existing artifact discovery and durable investigation context are the first tools to use; add bounded summaries only if measured long-conversation failures require them.

The recommended end state retains Streamlit, FastAPI, the coordinator/two specialist boundaries, typed evidence, and one execution implementation. It adds a usable workbook workflow and a portable coding deliverable, with clear scope and better outcome evidence. That is a substantial capability gain without turning this local analyst into a general software platform.
