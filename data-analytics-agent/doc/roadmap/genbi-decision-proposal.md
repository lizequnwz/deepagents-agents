# Dynamic BI dashboards: decision proposal

**Prepared for Charlie · 21 October 2026**  
**Decision scope:** extend the current data analytics agent.  
**Evidence:** official product documentation and the current repository. Product integrations were not executed.

## 1. Recommended decision

Build dynamic dashboards as a **feature of the current analytics agent**. Add a dashboard design skill and application tools. Keep the current coordinator and its two specialists.

Use **React with the existing Python API** as the target for a persistent, interactive BI workspace. Streamlit remains a sound choice for a bounded internal analytics workbench. Select it if that narrower scope is the intended product.

Use **A2UI as an optional UI delivery protocol**. Keep the dashboard definition and analytical evidence under application control. Prove A2UI with real BI components before making it a release dependency.

Keep **text-to-SQL as the only source execution owner**. The dashboard requests data through that capability. A renderer must never receive warehouse credentials or create its own data access path.

| Decision | Recommendation | Reason |
|---|---|---|
| Product boundary | Dashboard feature in the existing product | Reuses semantic definitions, evidence, reviews and recovery. |
| Agent structure | Coordinator plus design skill | Dashboard composition already fits the coordinator's responsibility. |
| New subagent | Add only after a demonstrated need | Separate presentation context can help later. It does not supply a dashboard runtime. |
| Front end | React for the proposed GenBI workspace | Gives direct control over linked interactions and durable client state. |
| A2UI | Validate now; adopt when interoperability has value | It supplies UI messages and renderers. BI behavior still needs application code. |
| Data execution | Preserve the SQL specialist boundary | Prevents competing query, metric and permission paths. |

## 2. Define the product before choosing the protocol

Here, **GenBI** means that an agent helps users create, change and investigate BI content through conversation.

Four capabilities need separate acceptance criteria:

| Capability | User result | Current position |
|---|---|---|
| Conversational analysis | A supported answer with charts and a report | Implemented. |
| Dashboard generation | A useful arrangement of related metrics, charts and tables | Existing report objects provide a base. A dashboard artifact is missing. |
| Dashboard interaction | Shared filters, drill paths and saved view state | Requires a new state and action contract. |
| Dashboard operation | Reopen, refresh, recover and control access | Persistence exists. Refresh bindings and hosted access controls need work. |

A chart with hover and zoom does not establish linked dashboard behavior. A saved data snapshot does not establish a refreshable query.

The first useful journey should be concrete:

1. Ask for monthly sales by region using a reviewed sales definition.
2. Receive a saved dashboard with metrics, charts, a table and an HTML report.
3. Select a region and a period. See the same population across the affected components.
4. Reopen the dashboard with its saved state.
5. Refresh the data explicitly. Retain the previous evidence and report.
6. Ask why a change occurred. Receive a new investigation with stated limitations.

If the sales definition or reporting period is materially ambiguous, clarify it before execution. Do not assign a currency or completeness status from the UI.

## 3. What established products demonstrate

The reviewed products show different levels of capability. The table records documented behavior, not tested product parity.

| Product | Verified pattern | Limit that affects this decision |
|---|---|---|
| Power BI Copilot | Creates and edits report pages that users can save as normal reports. | Report authoring excludes custom visuals and styling changes. [Source](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-create-reports) |
| ThoughtSpot SpotterViz | Creates and revises multi-chart Liveboards, including layout and styling. Standard Liveboard operations remain available. | Requires enablement and edit permissions. Insight tiles are Early Access. [Source](https://docs.thoughtspot.com/cloud/26.9.0.cl/spotter-viz) |
| Looker Conversational Analytics | Adds conversation to dashboards and their query-linked content. | Dashboard agents are Preview. This documentation does not establish full dashboard authoring. [Source](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data-agents-dashboards) |
| Tableau Agent in Dashboards | Explains dashboards and answers questions about underlying workbook data. | The feature is Beta. The documentation says it cannot build dashboards. [Source](https://help.tableau.com/current/pro/desktop/en-us/dashboard_narratives_overview.htm) |
| Databricks Genie Agents | Connects curated context, SQL, evaluation and dashboard conversation. | Refreshing prior SQL and regenerating an answer are separate operations. Dashboard credential settings affect access. [Concepts](https://docs.databricks.com/aws/en/genie-agents/concepts), [monitoring](https://docs.databricks.com/aws/en/genie-agents/monitor) |
| Wren AI | Its current OSS direction emphasizes inspectable context and governed SQL. | The former Docker GenBI application is sunset. Old dashboard guides do not establish maintained support. [Source](https://docs.getwren.ai/oss/introduction) |

Three patterns matter most.

**Generate normal product objects.** Users must be able to save, inspect and revise a dashboard after the initial conversation. A generated screen alone is insufficient.

**Keep business meaning in one place.** Looker recommends curated fields and centralized calculations. Your reviewed OSI catalog already provides that direction. [Looker configuration guidance](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-best-practices)

**Separate refresh from reinterpretation.** A refresh should preserve the approved question. A new metric, join or grain requires new semantic work.

These are design conclusions from the sources. They do not imply that one vendor supplies every proposed capability.

## 4. What A2UI supplies

A2UI describes an interface with JSON messages. Trusted client components render that description. UI structure and application data remain separate. The protocol supports incremental updates. [A2UI concepts](https://a2ui.org/concepts/overview/)

As checked on 21 October 2026, **v0.9.1 is current** and **v1.0 is a candidate**. The project still describes its overall status as early-stage public preview. Use the current protocol for a production evaluation. Do not depend on candidate-only behavior. [Version status](https://a2ui.org/), [project status](https://github.com/a2ui-project/a2ui)

The current protocol creates surfaces, updates components, updates data and removes surfaces. The application supplies transport, durable storage and action processing. [Protocol specification](https://a2ui.org/specification/v0.9.1-a2ui/)

Maintained React, Lit and Angular renderers list stable v0.9.1 support. Flutter also appears in that matrix. However, Flutter's own GenUI documentation still calls its SDK alpha. Protocol support and SDK maturity are separate facts. [Renderer matrix](https://a2ui.org/reference/renderers/), [Flutter status](https://docs.flutter.dev/ai/genui)

### BI components still need implementation

The basic A2UI catalog does not supply a complete BI component set. Charts, analytical tables and metric cards need a trusted custom catalog. The application must define their behavior. [Basic catalog](https://a2ui.org/specification/v0.9.1-a2ui/#basic-component-catalog), [catalog guide](https://a2ui.org/guides/defining-your-own-catalog/)

Start with a small catalog: dashboard grid, metric card, saved chart, table, text, filter bar, evidence link and status message.

A custom BI catalog needs compatible components on every target renderer. Protocol support alone does not make a chart portable across clients.

Bind components to verified evidence IDs. Application code supplies numerical values. Reuse the current Plotly chart contracts. Keep model-authored JavaScript and arbitrary query text outside component properties.

Use the maintained message processor and renderer. Do not implement another A2UI engine. Pin the tested protocol, catalog and package versions. Reject unsupported versions explicitly. [Renderer development](https://a2ui.org/guides/renderer-development/)

### Related protocols have different jobs

| Item | Main job | Need for this project |
|---|---|---|
| A2UI | Describes the agent-generated interface | Optional presentation delivery contract. |
| AG-UI | Connects an agent runtime with application events and state | Optional. Consider it if its event contract reduces integration work. |
| MCP | Connects agents with tools and external systems | Optional connector boundary. It does not define BI meaning. |
| MCP Apps | Displays an interactive app inside a compatible assistant host | Useful if assistant-host distribution becomes a requirement. |
| A2A | Connects distributed agents | No current need for an in-process dashboard feature. |

A2UI can use a direct event stream. AG-UI is not a prerequisite. MCP Apps uses a host sandbox with a different rendering model. [A2UI transports](https://a2ui.org/concepts/transports/), [AG-UI](https://docs.ag-ui.com/introduction), [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview)

**Adoption rule:** use A2UI when shared component catalogs, multiple clients or external agent interfaces create a clear benefit. One web client can use the same validated dashboard definition directly.

## 5. Fit with the current analytics agent

The current system already separates presentation, source execution and statistical work. That separation should remain.

| Existing asset | Reuse | Required addition |
|---|---|---|
| FastAPI and persistent conversations | Keep the application boundary | Dashboard and action endpoints. |
| Coordinator | Keep ownership of the user answer and published evidence | Dashboard composition tools and design skill. |
| Text-to-SQL | Keep semantic grounding and all source execution | Reviewed, parameterized dashboard query bindings. |
| Data-analysis | Keep statistical work over saved datasets | Invoke for analytical questions that require it. |
| Strict chart and report definitions | Reuse chart rendering and evidence-bound metrics | A separate dashboard definition with actions and filters. |
| Saved datasets and scoped evidence resolver | Keep lineage and immutable evidence | Bind each dashboard revision to exact evidence. |
| Direct presentation edits | Reuse validation, stale-edit rejection and atomic commit patterns | Dashboard revisions and affected-component updates. |

Implementation evidence: [architecture](../development/architecture.md), [coordinator](../../data_analytics_agent/coordinator.py), [chart contracts](../../data_analytics_agent/visualization/schemas.py), [report contracts](../../data_analytics_agent/reporting/schemas.py), [evidence resolver](../../data_analytics_agent/evidence.py), [presentation edits](../../data_analytics_agent/presentation_edits.py).

The main gap is a **dashboard runtime**. This is application code that stores dashboard state, validates actions, obtains data and commits consistent revisions.

The current HTML report is a published document. Keep it as the evidence record. The dashboard is a working view with explicit state. Give each new data-backed answer its required report.

### Feature, skill, subagent or independent agent?

| Option | Decision |
|---|---|
| Skill only | Insufficient. Instructions cannot provide storage, rendering, permissions or action validation. |
| Feature plus coordinator skill | Recommended. Add the missing runtime while reusing analytical ownership. |
| Presentation subagent plus skill | Consider when composition needs substantial separate context or repeated design iteration. |
| Independent GenBI agent | Consider only for a separately owned product or security and deployment boundary. |

A future presentation specialist should receive saved evidence IDs, the dashboard objective and the approved component catalog. It should return a candidate dashboard definition. It should have no warehouse tools.

Adding that specialist is not just a configuration change. The current delegation middleware treats non-analysis assignments as source work. Its roles and concurrency rules need an explicit update. [Delegation policy](../../data_analytics_agent/delegation.py)

Use a skill to teach dashboard purpose, layout, chart choice, filter scope, evidence use and revision rules. Keep authorization and numerical validation in code.

## 6. Proposed architecture and behavior

[Open the interactive architecture diagram](genbi-architecture.html).

Keep one canonical **DashboardSpec**. It should contain:

| Part | Required information |
|---|---|
| Identity | Dashboard ID, revision, conversation and source scope. |
| Components | Stable IDs, layout, approved component type and evidence bindings. |
| Filters | Business field, type, operator, defaults and affected components. |
| Data bindings | Saved evidence IDs and optional server-owned query binding IDs. |
| State | Applied selections, current revision and action status. |
| Provenance | Semantic version, source query time, declared cutoff and completeness status. |

Query execution records should retain parameters, approved SQL, result IDs and review decisions. Do not store warehouse credentials in dashboard state.

Use the existing SQLite and artifact stores for the local product. Add storage infrastructure only when deployment requirements justify it.

If A2UI is selected, compile the validated DashboardSpec into its BI catalog messages. Keep that adapter small. Do not create a general multi-protocol framework.

### Apply a filter as a controlled action

1. The client submits the dashboard revision, component, action, typed values and request ID.
2. The server validates scope, fields, allowed values and the expected revision.
3. The server identifies the affected components and their required populations.
4. The SQL capability obtains complete saved or source-backed results.
5. The system validates results, saves evidence, publishes selected findings and renders the required report.
6. The system commits the new dashboard revision after its required artifacts succeed.

Keep source assignments sequential under the current policy. Independent rendering can occur after the evidence is ready.

Data-changing filters are asynchronous governed actions under the current report policy. Use an **Apply** control to batch selections. Show progress while retaining the last committed population. Immediate chart highlighting remains a separate visual operation.

Reject duplicate or stale actions. A late response must not overwrite a newer selection. On failure, retain the last valid view and show its prior selections and failure status.

Bind every affected metric, chart and table to the same declared filter meaning. Reuse one suitable result across components where possible. If several queries are required, do not claim a common source snapshot without source support.

For initial agent-generated dashboards, prepare the dashboard after evidence publication and before report completion. The completion checks must require the requested dashboard artifact. A data-changing action starts a new run. It must not reopen computation inside an already published turn.

This extends the current publication lifecycle explicitly. A skill alone cannot change that lifecycle. [Current completion behavior](../development/architecture.md#findings-reports-and-recovery)

## 7. Where text-to-SQL fits

Text-to-SQL supplies governed retrieval. GenBI adds a persistent interface, interaction handling and publication around that retrieval.

| User operation | Execution path | Model or source work |
|---|---|---|
| Rename a title, move a panel or change an allowed color | Presentation service | Neither. |
| Zoom a chart or highlight visible points | Client rendering | Neither. No new business total. |
| Apply a declared filter to a complete saved population | SQL-owned saved-data execution | No new source query. A validated binding can avoid a model call. |
| Refresh the same question | SQL-owned execution of an approved query binding | New source query. No reinterpretation is needed. |
| Add a metric, grain, join or missing detail | Coordinator to text-to-SQL | Semantic grounding, query planning and applicable review. |
| Forecast or test a statistical explanation | SQL obtains inputs; data-analysis investigates | Python analysis over complete saved evidence. |

The deterministic query-binding path is a proposed addition. The current specialist tools do not yet provide that dashboard API. Keep it within the SQL owner's validation and execution module.

For an action without a model call, application code must publish evidence-bound findings and render its report through the existing services. Fixed explanatory text can describe the declared filter or refresh. This needs an application service change; direct SQL execution alone does not complete the lifecycle.

Do not ask an LLM to invent SQL for every click. Use typed parameters for actions with established meaning. A changed business question still requires the specialist.

Bind parameter values through the database driver. Do not substitute UI text into SQL. Approval of one query does not approve every parameter or population. Preserve configured execution reviews unless the reviewed binding explicitly covers that scope.

Preserve these rules:

- Warehouse conversations use their reviewed semantic catalog. File conversations use only explicitly reviewed, named datasets.
- Matching field names do not establish join keys or a shared filter dimension.
- Apply population filters before the relevant aggregation. Validate the meaning of ratios, averages and distinct counts.
- Never compute business totals from a chart sample. Reuse complete analytical datasets at a suitable grain.
- Preserve declared units. Source query time does not establish data completeness.
- Revalidate SQL, semantics and permissions on refresh. Reviewed edits remain authoritative.

Some established systems compile metric requests into SQL through a semantic engine. Therefore, natural-language SQL generation is not mandatory for every BI operation. Retain the current specialist now. Consider another semantic engine only for a concrete need. [MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow?version=2)

## 8. Is Streamlit still a good choice?

**Yes, for a deliberately scoped analytics workbench. React is the preferred target for the proposed interactive BI product.**

Streamlit supports hosted deployment. The distinction here is interaction scope and application complexity. This repository's current local deployment is a separate constraint. [Streamlit deployment](https://docs.streamlit.io/deploy/concepts)

Modern Streamlit supports partial reruns, stateful custom components and packaged JavaScript interfaces. Components v2 can host React or Lit inside the page. An A2UI renderer can therefore be integrated through a trusted component. [Components overview](https://docs.streamlit.io/develop/concepts/custom-components/overview), [state and triggers](https://docs.streamlit.io/develop/concepts/custom-components/components-v2/state-and-triggers), [fragments](https://docs.streamlit.io/develop/concepts/architecture/fragments)

Do not base the decision on outdated iframe or full-rerun assumptions. Recent Streamlit releases add further interaction options. The repository's minimum version does not establish which later features are installed. [Release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026)

| Option | Best fit | Main engineering cost |
|---|---|---|
| Native Streamlit with a fixed dashboard schema | Internal users, Python ownership and a bounded interaction set | More custom coordination as client interactions grow. |
| Streamlit with an A2UI component | A bounded dashboard panel inside a useful Python shell | Synchronizing component state and Python state. |
| React with FastAPI | Persistent canvas, linked controls, saved views and detailed design control | Front-end implementation, deployment and browser tests. |
| Next.js with FastAPI | A React product with a concrete routing, hosting or server-rendering requirement | Another server boundary if its features are unnecessary. |
| Lit or Angular | A team already using those frameworks | New-stack cost if the team lacks experience. |

React provides direct control over shared client state. Next.js still needs client components for interactive browser behavior. Keep source credentials in Python. [React state](https://react.dev/learn/managing-state), [Next.js boundaries](https://nextjs.org/docs/app/getting-started/server-and-client-components)

Reuse Plotly first. A2UI does not require a new chart library. Avoid adopting a grid engine, state framework and chart engine before the first complete workflow requires them.

Do not build a temporary Streamlit bridge with a planned replacement. If Streamlit is selected, define its supported product scope. If React is selected, build the intended dashboard there.

Keep the current working interface while the new client reaches acceptance. Once it covers the required workflow, remove the replaced paths. Do not maintain indefinite compatibility layers.

### Resolve the front-end uncertainty with one bounded experiment

Use one dashboard contract, one backend and the same complete saved evidence. Compare thin Streamlit and React interaction surfaces only if scope remains uncertain.

Test two metrics, two charts, a table and two linked filters. Include save/reopen, a drill action, refresh, an error and a stale response.

Accept a client only if it preserves evidence bindings, survives repeated interactions and restores saved state. Check keyboard use, focus and narrow layouts. Measure interaction latency on a declared device and dataset.

This experiment is proposed work. No renderer performance or integration result is claimed in this proposal.

## 9. Delivery plan and release gates

| Stage | Working product at the end | Release gate |
|---|---|---|
| 1. Saved dashboard | One saved dashboard per conversation, built from existing evidence. Metrics, charts, table, save/reopen and HTML report work end to end. | All values resolve to saved evidence. Restart preserves the view. Presentation edits require no model or source query. |
| 2. Declared interactions | Category/date filters and a supported drill path create consistent revisions. | Metrics, charts and tables reconcile. Samples cannot become inputs. Stale actions and failed updates preserve the last valid view. |
| 3. Explicit refresh | Reviewed parameterized query bindings refresh warehouse data through the SQL owner. | Reviews and limits remain effective. Refresh creates new evidence and a report. Old published evidence stays reproducible. |
| 4. Distribution, when required | A2UI delivery and/or a hosted shared product | Real catalog conformance passes. Hosted delivery also requires identity, artifact authorization and permission-aware data access. |

A2UI can be tested during Stage 1. Make it a required renderer only if that test proves a product benefit. Protocol adoption and multiuser hosting are separate decisions.

For file workspaces, refresh can recompute saved data. New file content still requires explicit import and schema review.

Defer scheduled refresh, alerts, shared editing and unrestricted layout generation until the core dashboard works. Each later capability needs its own operational and permission rules.

The largest work items are the action runtime, consistent evidence updates and front-end interaction tests. A protocol adapter does not remove those costs. Estimate calendar time after the thin slice; staffing and deployment requirements are not yet defined.

## 10. Material risks and controls

| Risk | Required control |
|---|---|
| Attractive screen with incorrect business meaning | Reviewed metrics, visible filter scope and evidence-bound values. |
| Inconsistent populations across widgets | Shared action plan, correct aggregation and atomic revision commit. |
| Repeated model calls and query cost on clicks | Deterministic declared actions, affected-component updates and bounded execution. |
| Stale or incomplete data appears current | Show query time and declared cutoff separately. Preserve unknown completeness. |
| Renderer or protocol changes | Pin tested versions. Keep one small adapter and explicit catalog validation. |
| Hosted user receives another user's artifact | Enforce server-side authorization on every artifact, export and action. |

The current API targets one local user. Conversation/source scoping is not user authorization. Some result and report endpoints use unscoped reads. Hosted sharing therefore requires backend work beyond a front-end replacement. [API implementation](../../data_analytics_agent/api.py)

Enforce data access before retrieval and before delivery. Scope caches by user permissions, source, semantics, parameters and evidence version. A dashboard permission must not grant access to all underlying rows.

Databricks documents a useful caution: a dashboard companion agent can access fields outside the visible charts, depending on its dataset and credentials. Review that boundary in any embedded product. [Dashboard companion agents](https://docs.databricks.com/aws/en/dashboards/genie-spaces)

A2UI catalog validation does not authorize actions. Streamlit Components v2 also uses style isolation, not a security sandbox. Ship trusted renderer code and validate all agent output. [Component security model](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.component)

## 11. Build or embed

Build the feature when your reviewed file workspaces, OSI semantics and saved analytical evidence are central product assets.

Prefer an embedded BI product when one platform already owns the organization's metric definitions, identity and dashboards. Confirm the exact embedded capabilities through its API or SDK.

Do not assume that features in a vendor's full application are available in its embedded surface. Do not maintain competing definitions of the same business metric.

For this repository, the build option has the stronger fit. Existing evidence and review behavior are useful foundations. No selected vendor currently supplies the authoritative product boundary in the inspected application.

## 12. Decisions to make

The recommended decision package is:

1. Extend the existing analytics product with a dashboard feature and design skill.
2. Target React and FastAPI for a persistent GenBI workspace.
3. Keep Streamlit if the intended product remains a bounded internal analytics workbench.
4. Keep text-to-SQL as the source execution authority.
5. Test A2UI with the actual BI catalog before committing the renderer contract.
6. Deliver saved dashboards, then interactions, then refresh.
7. Treat hosted sharing as an explicit backend and product scope decision.

The main assumption is that persistent dashboard interaction is the desired direction. If the goal is only richer analytical answers, extend the existing report and Streamlit experience.

## Evidence and writing method

This proposal uses official documentation checked on 21 October 2026 and direct repository inspection. It distinguishes documented capabilities from engineering recommendations. It makes no claim of vendor accuracy, measured latency or a completed integration.

The writing follows ASD-STE100 principles: short sentences, direct verbs, consistent terms and limited noun clusters. Technical names remain where needed. This is STE-informed writing, not certified standard compliance. [Official ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf)

The supporting notes retain additional sources and implementation anchors:

- [Protocol and front-end research](genbi-protocol-frontend-research.md)
- [Product patterns and build-versus-embed research](genbi-product-patterns-research.md)
- [Repository assessment](genbi-repository-assessment.md)
- [Document and diagram validation receipt](genbi-delivery-validation.json)

No application code was changed. No business data was queried. Existing application tests were inspected where relevant; they were not run for this research task.
