# Data Analytics Agent: ten highest-value next improvements

Reviewed 15 September 2026 against the current working tree. Subject: this repository’s custom Data Analytics Agent. The installed Codex Data plugin is an architectural reference, not the implementation being assessed.

## Executive assessment

**Observed:** This is already a persistent analytical application: a coordinator assigns retrieval and descriptive work to SQL and statistical work to Python. Saved Parquet datasets, exact execution records, parent lineage, chart/report revisions, clarification, stop/resume, staged findings, and report retry are implemented. Numeric report cards read saved values. These are substantial foundations, not missing features. See [coordinator.py](../data_analytics_agent/coordinator.py:125), [SavedResult](../data_analytics_agent/schemas.py:164), [report generation](../data_analytics_agent/reporting/tools.py:22), and [metric rendering](../data_analytics_agent/reporting/renderer.py:185).

**Inference:** The next product step is to make a supported answer become a reusable analytical asset: people should understand its definition, inspect its basis, explore its scope, refresh it, and know what changed. New model algorithms or a larger roster of agents would not address those needs on their own.

**Recommendation:** Keep the current coordinator/SQL/Python responsibilities and declarative report renderer. Extend their contracts in small working increments. Codex Data’s most relevant lessons are evidence attached to visible components, explicit analytical responsibilities, stable logical identities, and separation of evidence from presentation. Its custom compiler and hosted infrastructure are not prerequisites here.

## Ranking assumptions

The ranking assumes the near-term customer is an individual analyst or a small internal team using repeatable business metrics. It favors benefits across many questions, analytical trust, reuse of existing code, and achievable increments. Priority and effort are judgments, not measured ROI or delivery estimates. File uploads move into the first three if the primary audience works from spreadsheets; hosted collaboration moves up if team sharing is the immediate commercial objective.

| Rank | Improvement | Primary benefit | Relative scope |
|---|---|---|---|
| 1 | Metric definitions and evidence inspection | Understand exactly what a number means | Medium |
| 2 | Recorded validation before publishing findings | Catch plausible but unsupported answers | Medium–large |
| 3 | Structured metric-driver investigations | Better answers to “why did this change?” | Medium |
| 4 | Reusable reports with refresh and change review | Return to the same analytical product | Large |
| 5 | Interactive dashboards and saved views | Explore without another model call per filter | Large |
| 6 | Forecast and prediction evaluation records | Judge whether a model is useful | Medium |
| 7 | File uploads with controlled enrichment | Answer questions involving user-supplied data | Medium–large |
| 8 | User-approved reusable business context | Reduce repeated explanation and inconsistent assumptions | Medium |
| 9 | Scheduled KPI monitoring | Turn occasional analysis into an ongoing workflow | Large; depends on refresh |
| 10 | Faithful exports and explicit sharing scope | Put findings into the reader’s daily workflow | Medium locally; large for hosting |

### 1. Make metric meaning and evidence inspectable from every important number

**Observed:** The semantic catalog already has metric expressions, descriptions, instructions, and a content hash. Saved results already record SQL, timestamps, lineage, and profiles. Report metrics bind to a result column and row, but there is no corresponding typed metric-definition reference in `ReportMetric`. SemanticMetric has no dedicated numerator, denominator, unit, fiscal-calendar, or validity fields. Some meaning can already live in descriptions/instructions; the gap is consistent structured binding and reader access. [SemanticMetric](../data_analytics_agent/semantic.py:58), [SavedResult](../data_analytics_agent/schemas.py:164), [ReportMetric](../data_analytics_agent/reporting/schemas.py:105).

**Recommendation:** Add a compact metric/evidence contract: definition ID and version, semantic catalog hash, unit, population, grain, numerator/denominator when applicable, effective date window, filters, source-read time, and known limitations. Preserve truthful unknowns. Add “How was this calculated?” to metric cards and charts, opening the definition, relevant rows, transformations, and exact source query.

**Example:** A loan-problem rate should tell the reader which repayment statuses count, whether the denominator includes active or completed contracts, which date defines the period, and whether accounts or loans are counted.

**First useful slice:** Bind one existing catalog metric through SQL output to one report card. Extend the current semantic catalog instead of creating a competing metric registry.

**Acceptance:** Rephrased requests resolve to the same approved definition; every displayed KPI exposes its population, period, unit, and source; a definition change is visible even if the numeric result happens to stay the same.

**Risk:** Forcing speculative metadata creates false confidence. Label unknown source freshness separately from the known query-execution time.

### 2. Add a validation record for the evidence and claims being published

**Observed:** Read-only SQL validation checks structure and forbidden operations. Python refuses truncated inputs and display-only datasets. Reports resolve references and bind metric values. However, narrative bodies and metric change labels are strings, and `publish_findings` does not require a recorded semantic or claim-validation result. [SQL validation](../data_analytics_agent/backends/validation.py:45), [Python input checks](../data_analytics_agent/agents/data_analysis/tools.py:40), [report fields](../data_analytics_agent/reporting/schemas.py:105), [publication](../data_analytics_agent/presentation.py:73).

**Recommendation:** Record scoped checks before publishing: expected grain, key uniqueness, join multiplication, denominator reconciliation, comparable date windows, completeness, and claim support. Bind computable changes to baseline/current evidence instead of accepting a free-text percentage. Mark checks as pass, fail, or unknown with evidence references; a single generic confidence score would hide too much.

**Example:** Joining transactions to account permissions may multiply transaction amounts when an account has several authorized users. The query can be syntactically valid and read-only while the total is wrong.

**First useful slice:** Check duplicate keys and totals before/after a declared join, then validate a KPI delta against its stored baseline. Let SQL perform source-dependent checks; let trusted code enforce arithmetic and reference checks. Narrative support may need analytical judgment, so retain uncertainty rather than claiming a complete automatic truth checker.

**Acceptance:** Synthetic duplicate-join, wrong-denominator, mismatched-window, and incorrect-change-label cases are caught. Block dependent claims or publish explicitly partial findings; unaffected answers can proceed. A successful code execution alone never supplies a “validated” badge.

**Risk:** Overly broad gates can reject legitimate exploratory work. Scope checks to the claim and allow explicit unknowns.

### 3. Give “why did this metric change?” a structured investigation workflow

**Observed:** The Python skill already asks for competing hypotheses, seasonal/segment comparisons, uncertainty, and caution about causation. The saved investigation is a compact list of findings and artifacts, rather than a typed driver analysis. [Analysis guidance](../skills/analysis/data-analysis/SKILL.md:23), [investigation record](../data_analytics_agent/presentation.py:114).

**Recommendation:** Add a focused metric-diagnostics workflow inside the existing agents: establish the movement, check quality, separate changes within groups from changes in group mix, test volume/rate effects, compare plausible explanations, and preserve an unexplained remainder where appropriate. Store each hypothesis with its test, evidence, status, and limitations. Add a reusable driver-summary report composition.

**Example:** “Did outflows rise because more accounts transacted, because each account transacted more often, or because each transaction was larger?” These explanations require different evidence and lead to different actions.

**First useful slice:** One additive measure and one rate, with explicit comparison windows and segment definitions. Use existing bar/table charts before adding a specialized waterfall renderer.

**Acceptance:** A synthetic case with only a group-mix shift is distinguished from a decline within groups. Contributions reconcile when the selected decomposition permits it; interaction terms or order dependence are stated. “Largest segment” is not automatically reported as the cause.

**Risk:** Mechanical decomposition can sound causal. Distinguish accounting contributions, associations, and supported causal evidence.

### 4. Turn report revisions into reusable reports with deliberate refresh

**Observed:** Report revisions already have a predecessor and version. Each saved revision gets a new report ID, and `ReportSpec` has no stable block IDs or refresh recipe. Fresh data can be requested conversationally, but this is different from refreshing a named report while preserving its identity and presentation. [ReportStore](../data_analytics_agent/stores.py:137), [ReportSpec](../data_analytics_agent/reporting/schemas.py:190), [saved-query execution](../data_analytics_agent/agents/text_to_sql/tools.py:125).

**Recommendation:** Add a stable report-series identity and stable block identities, while retaining immutable revision IDs. Store a refresh recipe covering source queries, parameters, fixed versus rolling dates, derived transformations, and metric versions. Build a candidate revision, validate it, show the changes, then advance the current-report pointer. Preserve titles and layout where still applicable; flag narrative that needs reevaluation.

**Example:** “Refresh my monthly loan portfolio review” should update the intended month and show changes without asking the agent to rediscover the report’s purpose.

**First useful slice:** Manual refresh of one report with one source query and a parameterized date window. Add Python transformation replay only after that works end to end.

**Acceptance:** Refresh preserves the report-series link and unchanged block identities; old revisions remain inspectable; failure leaves the last successful version current; changing a fixed period to a rolling period is explicit; narrative is rechecked against new values.

**Risk:** Blindly rerunning old SQL with literal dates returns stale scope. Reusing old prose can preserve an invalid conclusion.

### 5. Add interactive dashboards with shared filters and saved views

**Observed:** There are nine declared chart types and interactive Plotly figures. The report contract contains narrative, metrics, tables, charts, analysis, callout, and infographic blocks, but no shared dashboard-filter or saved-view model. Existing chart interactivity should not be described as missing. [ChartSpec](../data_analytics_agent/visualization/schemas.py:21), [ReportBlock](../data_analytics_agent/reporting/schemas.py:178), [renderer](../data_analytics_agent/reporting/renderer.py:527).

**Recommendation:** Add a dashboard presentation mode over saved evidence: shared date/segment filters, comparison period, drill-down tables, and a saved view. Keep presentation state separate from underlying results. Controls must clearly indicate whether they filter a complete saved dataset or require a new source request.

**Example:** Select a district and have the portfolio amount, repayment-status chart, and detail table update to the same population immediately.

**First useful slice:** One segment filter driving one metric, one chart, and one table. Reuse the trusted renderer and existing chart library.

**Acceptance:** All three views reconcile after each filter change; clearing filters restores totals; the view can be reopened; export records the selected scope; no model or warehouse call occurs for supported snapshot-only filtering.

**Risk:** Filtering chart samples or adding averages of rates produces misleading totals. Compute from suitable complete evidence or explicitly disable unsupported interactions.

### 6. Make model evaluation a first-class analytical result

**Observed:** Forecasting and predictive analysis already exist, with good instructions about baselines, temporal holdouts, leakage, and intervals. `DataAnalysisResult` records method, assumptions, warnings, and executions, but not a dedicated evaluation contract. The opt-in test rubric largely checks method words in output rather than proving held-out performance or calibrated intervals. [Analysis skill](../skills/analysis/data-analysis/SKILL.md:28), [analysis schema](../data_analytics_agent/agents/data_analysis/schemas.py:70), [evaluation rubric](../tests/test_live_evaluations.py:164).

**Recommendation:** Store task type, target, feature availability time, split boundaries, train/test sizes, baseline/model scores, forecast horizon, interval method, and empirical coverage when measurable. Render a model-comparison card. Add synthetic tests with leakage traps, changing trends, and insufficient seasonal history.

**Example:** A forecast should state “the model did not improve on the seasonal baseline on the selected holdout” when that is what the saved scores show, even if the model curve looks more sophisticated.

**First useful slice:** A temporal holdout and baseline comparison table bound to saved prediction rows, with trusted recomputation of the reported error.

**Acceptance:** The evaluation numbers recompute from saved predictions and observations; split overlap is rejected; no claimed model improvement contradicts the scores; inadequate evidence for interval calibration is stated explicitly.

**Risk:** A single holdout is unstable, and repeated model selection can overfit it. Support rolling evaluation when the data length justifies it. This is an improvement to existing prediction functionality, not a request to add prediction from scratch.

### 7. Support user-uploaded datasets and controlled source enrichment

**Observed:** Sources are configured through a backend, semantic model, dialect, and target. Results and tools are scoped to one conversation/source, and uploads/mixed-source work are explicitly deferred. [SourceDefinition](../data_analytics_agent/data_sources.py:34), [saved-data binding](../data_analytics_agent/agents/text_to_sql/tools.py:154), [deferred work](../HANDOFF.md:1).

**Recommendation:** Start with CSV/Parquet upload as a complete, conversation-scoped dataset. Show inferred types, grain, missing values, file hash, and sheet/range when spreadsheet support is added. Then allow explicitly selected enrichment of a warehouse snapshot with an uploaded mapping or target file, preserving both origins and checking join cardinality.

**Example:** Upload monthly district targets and compare them with actual loan activity from the configured source.

**First useful slice:** Analyze one uploaded CSV in an isolated conversation using the existing saved-data SQL/Python path. Mixed-source joins are a later deliberate policy change, not a bypass of current scoping checks.

**Acceptance:** Numeric identifiers retain leading zeros; ambiguous dates trigger a correction flow; duplicate join keys are visible; original uploads and transformed outputs have distinct IDs; derived evidence records both parents; unrelated conversations cannot access the file.

**Risk:** “Just add upload” can silently weaken source isolation or misinfer types. Keep warehouse execution exclusively in SQL and file content separate from agent instructions.

### 8. Save approved business context and reporting preferences

**Observed:** Business meaning exists in curated semantic YAML and repository instructions, while conversation investigations preserve assumptions for that conversation. The reviewed tools do not expose an approved reusable context workflow for the end user. [SemanticCatalog](../data_analytics_agent/semantic.py:89), [investigation persistence](../data_analytics_agent/presentation.py:114), [coordinator tools](../data_analytics_agent/coordinator.py:125).

**Recommendation:** Let a user explicitly save a fiscal calendar, metric convention, standard exclusion, preferred audience, or reporting style. Show scope, version, and origin. Define precedence: the current explicit request and governed source definitions should resolve conflicts visibly, not through hidden learned behavior.

**Example:** “For our monthly operations report, use fiscal months and exclude test accounts. Remember this for this source.”

**First useful slice:** A user-editable context record scoped to one source, loaded into a compact analysis brief and recorded with the resulting evidence. Propose durable changes for review rather than learning silently from every turn.

**Acceptance:** A saved convention is available in a new conversation; a one-off override is not persisted accidentally; conflicting calendars are surfaced; users can inspect and revoke stored preferences.

**Risk:** Stale or overbroad preferences can change every future answer. Keep business definitions and visual preferences distinct and auditable.

### 9. Build scheduled KPI monitoring on top of validated refresh

**Observed:** Scheduling and proactive monitoring are deferred. The application exposes manual run, stop, resume, and retry-report operations and is documented as a local single-user, single-API-process deployment. [Deferred work](../HANDOFF.md:1), [run endpoints](../data_analytics_agent/api.py:623), [README](../README.md:43).

**Recommendation:** After manual refresh works, add a saved monitor with report identity, metric version, cadence, timezone, comparison baseline, freshness requirement, and alert policy. Begin with an in-app status/history view. External notification destinations and message scope require explicit user configuration.

**Example:** “Each Monday, refresh the portfolio review and flag a material change in the approved problem-loan metric, only if the source period is complete.”

**First useful slice:** One manually configured scheduled refresh with last-success/next-run/status information. Show clearly that a local scheduler only runs while its host is available.

**Acceptance:** Restart does not duplicate schedules; runs do not overlap for one monitor; stale inputs create a data-quality status rather than a business alert; repeated failures do not flood notifications; users can pause the monitor and inspect the evidence behind an alert.

**Risk:** Automating unreliable analysis multiplies its mistakes. This ranks below manual refresh and validation because it depends on both.

### 10. Deliver faithful exports with explicit sharing scope

**Observed:** Dataset CSV/Parquet and HTML report downloads are implemented. The report includes exact source SQL; it is not just a screenshot of the visible answer. The reviewed API has no report PDF/PPTX/DOCX export or hosted sharing workflow. [Downloads](../data_analytics_agent/api.py:662), [report download](../data_analytics_agent/api.py:724), [SQL appendix](../data_analytics_agent/reporting/renderer.py:483).

**Recommendation:** Start with reliable PDF export of the selected report revision and view. Then add a concise executive summary and presentation export if users need them. Offer an explicit audience-ready export versus a full audit package, showing what data and code each contains. Derive both from the same approved evidence. Hosted collaboration requires a separate authentication/authorization design before exposing this local API.

**Example:** An analyst keeps the full methods package but exports an executive PDF containing the approved metrics, charts, definitions, and essential limitations.

**First useful slice:** Deterministic PDF conversion with the report ID, revision, period, selected filters, and export time in the document.

**Acceptance:** Exported numbers match the saved revision; chart labels and caveats survive pagination; no SQL or unselected detail leaks into the audience-ready payload; export makes no model/source call; a full audit package retains reproducible code and evidence references.

**Risk:** Hiding a panel is not removing data from an exported file. Inspect the export payload, and keep essential caveats in every audience version.

## Recommended delivery sequence

**Recommendation:** Ship one vertical slice first: an existing KPI with an inspectable definition, a bound baseline/delta, a recorded reconciliation check, and a report card. That combines a narrow portion of items 1 and 2 into an immediately useful product.

Next, use it for one metric-driver investigation (3). Then add manual refresh with stable report/block identities (4), followed by shared filters over complete saved data (5). Build structured model evaluation (6) around one existing forecasting workflow. Add uploads (7) and reusable context (8) as user demand justifies them. Schedule only a proven refresh (9). Local PDF export (10) can be a small independent delivery increment; hosted collaboration is larger.

Scenario modeling, executable notebook export, additional chart types, and web/document evidence are worthwhile later candidates. They do not displace the ten above under the stated customer assumptions. In particular, unrestricted cross-source analysis and more autonomous agents should not precede clear scope and validation contracts.

## Review method and verification

**Observed:** Inspected the current source for coordinator routing, SQL and Python tool boundaries, semantic catalog, saved evidence schemas, report schemas/generation/rendering, chart contracts, stores, API routes, UI workflow references, analytical/reporting skills, README, deferred work, and relevant tests. Recommendations describe gaps in these reviewed contracts and workflows; arbitrary generated Python may already perform some proposed analyses ad hoc.

**Observed:** Ran:

```sh
.venv/bin/pytest tests/test_reporting.py tests/test_persistent_analyst.py tests/test_semantic_discovery.py tests/test_data_analysis.py tests/test_storage_isolation.py -q
```

All **38 selected tests passed**. Two deprecation warnings appeared: Starlette’s current TestClient/httpx integration and DuckDB `fetch_record_batch`. These are maintenance observations, not the top functionality priorities. This was a targeted regression run, not the full suite, live model evaluation, warehouse query, browser usability study, or security certification.

**Limit:** No user study, measured ROI, delivery estimate, or performance benchmark was conducted. No live data, model provider, publication, or notification was invoked for this review. Application source was reviewed, not modified; this document records a proposed roadmap.
