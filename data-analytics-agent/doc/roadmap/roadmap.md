# Data Analytics Agent: next-release recommendations

Delivery updates are tracked separately in the
[implementation log](implementation-progress.md); the review below records the
baseline and intended sequence.

Reviewed **19 September 2026** against repository revision `f7e5610` and current primary-source product documentation. This replaces the 15 September prioritization. Dated [reviews](../reviews/README.md) remain historical evidence; the [architecture](../development/architecture.md) describes implemented behavior.

**Recommended next release:** make one business metric easy to understand, verify, and adjust. Deliver an inspectable KPI and checked comparison in a compact results workspace, with direct presentation edits and outcome-based evaluations. Then extend that foundation to scoped exploration, repeatable refresh, and monitoring.

Assumption: the primary user is an individual analyst or a small internal team doing recurring business analysis. Priorities are product judgments, not measured ROI or delivery estimates. Spreadsheet-first users would move isolated file uploads earlier; a forecasting-first audience would move forecast quality into the first release.

Follow-up direction: evaluate simplification alongside new capabilities. The
[simplification and ablation plan](simplification-and-ablation.md) prioritizes
minimal setup, consolidated instructions, and direct edits. Report composition
remains agent-driven; deterministic standard reports are excluded. The plan also
places isolated tabular uploads in the early delivery
sequence, reusing the evidence pipeline before document research or warehouse
enrichment.

## What the application already does

Preserve the coordinator / SQL / Python separation, single-source conversations, immutable saved evidence, and trusted declarative chart/report rendering. Persistence, iterative statistical analysis, clarification, corrections during execution, Stop/Resume, and report retry are implemented. Every data-backed answer still requires an HTML report; improving the UI does not remove that requirement.

| Existing capability | Remaining gap confirmed in current code |
|---|---|
| Dataset inspector with Data/Source views, parent lineage, full downloads | KPI meaning and validation are not bound to the number being inspected. [UI](../../data_analytics_agent/ui/components.py), [semantic catalog](../../data_analytics_agent/semantic.py) |
| Saved numeric values supply report metric cards | `ReportMetric.change` and narrative claims remain authored strings; publication resolves artifacts but does not require claim checks. [Report schemas](../../data_analytics_agent/reporting/schemas.py), [publication](../../data_analytics_agent/presentation.py) |
| Interactive Plotly charts and immutable chart revisions | The UI does not consume selection events or offer direct title/type controls; report preview opens expanded. [UI](../../data_analytics_agent/ui/components.py) |
| Forecast bounds and analytical execution records | Bounds are labeled “Uncertainty interval” regardless of meaning and require one line series; model evaluation lacks a dedicated persisted contract. [Charts](../../data_analytics_agent/visualization/schemas.py), [renderer](../../data_analytics_agent/visualization/renderer.py), [analysis schemas](../../data_analytics_agent/agents/data_analysis/schemas.py) |
| Deterministic workflow tests and opt-in live evaluations | Statistical live checks largely test method vocabulary and execution presence, not held-out accuracy or final-answer consistency. [Evaluations](../../tests/test_live_evaluations.py) |
| Versioned reports and conversational requests for fresh values | No stable report-series/block identities, shared filter state, or typed refresh recipe. [Report schemas](../../data_analytics_agent/reporting/schemas.py) |

## Recent developments that change the emphasis

These are documented product capabilities, not independent evidence of vendor accuracy. Release dates below are event dates; undated documentation was checked on 19 September 2026.

| Development | Implication for this application |
|---|---|
| Hex introduced point-and-click chart controls on **27 August**, targeted chart/text editing on **10 September**, and publishing/versioning/scheduling evaluation suites on **15 September 2026**. [Hex releases](https://learn.hex.tech/changelog) | Move direct edits and versioned evaluations into the next release. A prompt should not be necessary for every presentation adjustment. |
| Databricks documents result-based Chat benchmarks, paraphrase coverage, and a separate judge-based approach for Agent responses; its monitoring page was updated **17 September 2026**. [Genie benchmarks](https://docs.databricks.com/aws/en/genie-agents/monitor) | Grade the produced evidence and answer, with different checks for descriptive and inferential work. Avoid one generic “agent passed” score. |
| Snowflake documents human-reviewed suggestions for verified queries, metrics, filters, and semantic instructions. [Semantic suggestions](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-suggestions) | Turn accepted corrections into reviewable context improvements and regression cases, without silently learning new business definitions. |
| Databricks added document citations and version history on **9 July 2026**. [AI/BI release notes](https://docs.databricks.com/gcp/en/ai-bi/release-notes/2026) | Attach evidence to the visible conclusion and preserve revision identity; an appendix of queries alone does not explain a KPI. |
| MCP Apps became an official extension on **26 January 2026**, supporting interactive components inside conversations. [Announcement](https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/), [extension](https://modelcontextprotocol.io/extensions/apps/overview) | Design typed artifact actions that can later serve an embedded client. Do not make adopting MCP or replacing Streamlit a prerequisite. |
| Snowflake's **2 September 2026** change allows runs with some inaccessible tools to continue with warnings. Its **16 September** release adds temporary and secure agent objects. [Partial tool availability](https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2425), [object enhancements](https://docs.snowflake.com/en/release-notes/2026/other/2026-09-16-cortex-agents-object-enhancements-ga) | Keep supported findings usable when optional work fails, while exposing unresolved scope. Managed-agent lifecycle features matter for a future deployment decision, not the next local UI increment. |

A useful limitation in Hex's current documentation: its agent does not automatically know a generative app's visible filters and inputs. This supports making selected scope explicit in our interaction contract, rather than assuming chat understands whatever is on screen. [Chat with App](https://learn.hex.tech/docs/explore-data/chat-with-app)

## Revised order

| Priority | Deliverable | Change from 15 September | Dependency |
|---|---|---|---|
| 1 | Inspectable metric meaning and checked claims | Keep definition and validation work together | Existing semantic catalog and saved results |
| 2 | Outcome-based agent evaluations | Promote to an explicit release requirement | Start with priority 1 fixtures; broaden with each feature |
| 3 | Compact workspace and direct result controls | Promote ahead of a full dashboard or driver workflow | Presentation edits can ship immediately; scope actions need priority 1 |
| 4 | Forecast evaluation and truthful interval displays | Restore the chart-contract issue from the 10 September review | Existing prediction workflow |
| 5 | Shared scope, saved views, and manual refresh | Deliver as successive increments | Priorities 1–3 |
| 6 | Reviewed correction-to-context loop | Move ahead of broad autonomous monitoring | Evaluation cases and semantic versioning |
| 7 | Structured metric-driver investigations | Follow trustworthy comparisons and scope | Priorities 1–2 and explicit comparison scope |
| 8 | Uploads, exports, monitoring, and integrations | Retain, but choose by demonstrated demand | Specific gates below |

### 1. Bind meaning and checks to the answer

Extend the current OSI-backed metric representation; do not create a competing metric registry. Carry the catalog hash, metric reference, business period, population, grain, filters, and units alongside the saved evidence. Add numerator/denominator and calendar rules only where applicable. Distinguish source freshness from the known extraction time; unknown freshness remains unknown.

Bind a comparison to current and baseline result references with its calculation type. Compute deltas in trusted code, including undefined percentage changes from a zero baseline. Remove the free-text numeric-change path when this replaces it. A user should reach definition, scope, checks, and source evidence from **How calculated?** beside the KPI.

Record relevant checks with pass/fail/unknown outcomes and evidence IDs: join cardinality, denominator reconciliation, period comparability, completeness, and arithmetic. SQL owns source-dependent checks. Publication enforces available deterministic checks; narrative claims carry evidence references and qualified language where support is incomplete. A second model's agreement does not establish truth.

**First slice:** one existing metric, one comparison, and one report card. Deliberately test a duplicated join and an incompatible date window. Failed checks suppress the affected claim or produce explicitly partial findings; unrelated supported claims remain usable. Keep simple scalar questions lightweight.

**Done when:** the KPI, delta, chart, and report reconcile; the definition and population are inspectable; a changed definition is visible even if its value is unchanged. No “validated” badge appears merely because SQL executed successfully.

### 2. Evaluate outcomes and interaction sequences

Begin with a small versioned suite covering the first metric end to end, then expand to approximately 30–50 representative question patterns. That range is a proposed starting target, not a reliability claim. Include paraphrases and multi-turn cases, with separate development examples and held-out cases.

Use deterministic expected results and invariants for totals, rates, joins, ties, nulls, and time windows. Evaluate the answer and report as well as saved outputs. For forecasting, recompute scores from saved predictions and observations. Use calibrated human or model rubrics for explanation quality, alongside those checks. Repeated trials expose instability. [Agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [Hex evaluations](https://learn.hex.tech/docs/agent-management/evals)

Add sequences for clarification, corrections received/applied, chart-only edits, selected-scope follow-ups, refresh, restart, cancellation, and report failure/retry. Record model, prompt/skill version, catalog hash, fixture version, outcomes, latency, and usage. Reuse existing diagnostics before adding infrastructure.

**Done when:** known wrong-denominator, duplicated-join, stale-scope, invented-delta, and forecast-leakage cases fail for the right reason. Deterministic critical invariants must pass; repeated live results are reported by capability with sample size and unresolved failures. Live model evaluations remain opt-in under the project's authorization policy.

### 3. Make results the center of the interaction

Use a concise answer and primary metric/chart, followed by a persistent scope row: source, period, filters, unit, extraction time, and check status. Provide a switchable **Findings / Data / Method / Report** workspace. Reuse the existing dataset inspector and lazy disclosures. Keep the HTML report mandatory but its preview collapsed until requested. Group intermediate datasets under lineage instead of presenting every ancestor as an equally important finding.

Put saved conversations and useful example questions ahead of framework information. Show business-oriented status such as “Checking totals” and “Preparing report,” with exact code and diagnostics available on demand. Preserve the stable composer, Activity disclosure, inline clarification, Stop/Resume, and report retry.

| User action | Expected behavior |
|---|---|
| Inspect a KPI | Open its definition, scope, checks, and existing evidence inspector; no model/source execution |
| Change a chart title, label, or allowed style | Deterministically save a chart revision and matching report revision; no model/source execution |
| Change chart type | Validate compatibility with existing evidence; recompute presentation if needed; explain unsupported combinations |
| Select a point or category | Display its explicit scope and offer **Explain selection**, **Compare**, or **Break down**; selection alone starts no analysis |
| Ask about the selection | Send artifact ID, revision, and validated selection/filter state with the follow-up; do not rely on ambiguous “this” |
| Filter a saved view | Update metric/chart/table from complete suitable saved evidence; no model or warehouse call |
| Refresh from source | Start source execution with visible fixed/rolling period semantics and preserve the last successful revision |

Implement the first controls using existing Streamlit and Plotly. The installed Streamlit API supports `on_select`; the current chart call leaves its default of ignoring selection events. Bind selections to domain keys or predicates, not row positions that can change after sorting. [Streamlit selection API](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart)

Keep viewing state separate from committed artifact revisions. Presentation edits must not alter metric definitions. If regenerating a report fails, mark the candidate revision incomplete and retain the prior matching chart/report pair, with retry available. Existing immutable revisions provide the basis for restoring an earlier view.

**Done when:** an analyst can inspect, edit, and return to the same result without losing scope or focus. Title-only edits make zero provider/warehouse calls. Keyboard users can perform the same operations through controls; drag selection is optional. Verify narrow-screen layouts, readable tables, focus retention during polling, and contextual status announcements. “Primary evidence” means selected evidence, not certified correctness; its visual treatment should not imply otherwise.

### 4. Make forecast quality visible

Add interval kind, label, method, and optional nominal coverage. Distinguish prediction intervals, confidence intervals, and scenario/sensitivity ranges. Support actuals, forecast, baseline, bounds, and a forecast-start marker in the shared chart contract. Reuse Plotly trace primitives.

Persist split boundaries, horizon, target, feature availability, baseline/model scores, and saved predictions/observations. Report empirical coverage only when actually evaluated. Add noisy, short-history, structural-break, and leakage fixtures. A model that loses to the baseline must say so.

**Done when:** displayed errors recompute, train/test overlap fails, actuals remain visible, and a planning range is never labeled as calibrated prediction uncertainty. Permit bounded diagnostic-image inspection when useful; numerical diagnostics remain required. Ship the label correction independently before attempting a general chart-layer system.

### 5. Build scope controls, then reliable refresh

First, add one segment filter over a complete saved population, driving one KPI, one chart, and one table. Persist a saved view with source/artifact/revision and validated filters. Disable unsupported scope changes when only a sample or incompatible aggregate exists. Recompute weighted rates from their components; never average displayed percentages. Exports must record the selected scope.

Then introduce a stable report-series ID and stable block IDs, while retaining immutable revision IDs. A refresh recipe records query parameters, fixed versus rolling periods, metric/catalog versions, and dependencies. Start with one parameterized source query; add Python replay only when the simple refresh works end to end.

Build and check a candidate revision before changing the current-report pointer. Show changes to values, scope, definitions, and freshness separately. Reevaluate narrative against new evidence. A source failure retains the last successful report with a stale/failed-refresh status.

**Done when:** controls reconcile all visible components; reopening restores the selected view; refresh preserves report identity; failure leaves the last successful revision intact. A new query timestamp must not imply a newly updated source.

### 6. Convert corrections into reviewed improvements

Add **Report an issue** on an answer, capturing its scope, artifact IDs, and a category such as wrong definition, wrong data, or poor presentation. Reuse the current correction delivery mechanism for the active task. A reusable fix is a separate proposal: inspect, edit, accept, or dismiss.

Store accepted business-context changes by source and version, and run affected evaluation cases before activation. Keep visual preferences separate from metric definitions. One-off user instructions must not silently become source-wide policy; conflicts with governed definitions must be visible.

**Done when:** an accepted fix adds a regression case, its effect is inspectable in future results, and the user can revoke it. Start with a reviewed file/configuration change; a new administration platform is unnecessary.

### 7. Add one defensible driver-analysis workflow

Within the existing agents, establish the metric movement, rule out data-quality changes, compare periods, separate within-group changes from composition changes, and record tested hypotheses plus unresolved explanations. Start with an additive measure and a rate; use existing charts.

**Done when:** a synthetic mix-shift case is distinguished from worsening group performance; contributions reconcile when the decomposition permits it; interaction/order effects are disclosed. Accounting contributions and associations must not be presented as causal proof.

### 8. Expand only with a clear workflow and its prerequisites

| Capability | First useful increment | Gate before broader rollout |
|---|---|---|
| File uploads | One CSV/Parquet as an isolated conversation source, with type/grain preview | Preserve identifiers, clarify ambiguous dates, record hashes/lineage; mixed-source joins require an explicit scope-policy change |
| Exports | PDF of a selected report revision/view | Verify numbers, labels, caveats, and pagination; an audience-ready payload actually excludes unselected code/detail |
| Monitoring | One proven refresh with history and pause | Idempotent scheduling, no overlap, freshness checks, quiet unchanged state, explicit notification destinations; local-host availability is visible |
| Web/document evidence | Cite a document supporting an analytical interpretation | Keep retrieved claims distinct from measured observations and capture source/date |
| MCP Apps | Read-only artifact inspection in a supported host | Validate host capability, authorization, data disclosure, and typed actions; retain one evidence model |
| Hosted collaboration | Share a deliberately scoped report | Tenant identity, artifact authorization, isolated execution, and secret/network boundaries must precede hosting |

The Python subprocess is a local execution boundary, not a security sandbox. Broader untrusted uploads, unattended code, or multi-user deployment require containment appropriate to that expansion. This is a deployment prerequisite, not a reason to delay local inspect/edit improvements.

## Concrete next increment

Use **one existing catalog KPI compared with its previous complete period** as the release story:

1. Define and persist its scope and metric reference; derive its delta from stored values.
2. Add a reconciliation result and enforce the relevant publication checks.
3. Present the KPI with **How calculated?**, a compact report link, and direct chart-title editing.
4. Preserve matching chart/report revisions and recover from report-rendering failure.
5. Evaluate the happy path, paraphrases, incorrect joins, ambiguous periods, correction handling, and presentation-only edits.

Deliver each step over a working end-to-end path. Add selection-to-follow-up next, followed by a shared filter and manual refresh. Forecast labeling can be a small independent fix. Avoid starting dashboard generation, a new agent roster, a frontend rewrite, and scheduling together.

Measure correctness by capability, first-attempt success, repair/clarification frequency, time to usable findings, report-ready time, and cost per successful task. For UI work, measure task completion and the number of prompts needed to inspect/change a result. Establish baselines before claiming improvement; these are proposed measures, not collected results.

## Review scope and limits

Reviewed the existing roadmap, September 10 and 14 reviews, handoff, user/development guides, current semantic/evidence/report/chart contracts, coordinator/publication boundaries, UI rendering, and live-evaluation code. Checked primary-source release notes through 19 September 2026 and the installed Streamlit selection API.

This is a documentation and source review. No warehouse query, live model evaluation, browser usability study, or application test suite was run for this revision. Earlier reviews' test results remain historical and are not evidence that these proposed capabilities exist. Application code is unchanged. Recommendations favor existing dependencies and modular contracts; they do not require compatibility layers, migrations, or new infrastructure before demonstrated need.
