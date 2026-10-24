# GenBI product patterns: research notes

Research date: 21 October 2026. These notes support an architecture decision. They are not a product procurement assessment or a tested comparison.

## Main finding

Established products connect conversation to governed analytical objects. Those objects retain their normal save, edit, filter, permission and refresh behavior. A conversational answer, a generated report and a persistent dashboard are different capabilities.

For this repository, the strongest pattern is to add a governed dashboard feature to the existing analytics system. Keep the current semantic and query boundaries. Do not create another agent that owns warehouse access, metric definitions or analytical truth.

## Product evidence

| Product | Verified capability | Decision implication | Status or limit |
|---|---|---|---|
| Power BI Copilot | Creates and edits report pages from natural language. Users can add, change and delete visuals, then save an ordinary report. | Generate standard dashboard objects which users can edit and save. | Copilot report authoring does not support custom visuals or styling changes. Some semantic model types are excluded. |
| ThoughtSpot Spotter and SpotterViz | Spotter answers questions. SpotterViz creates multi-visual Liveboards and revises layout, chart form and styling. These are standard Liveboards with normal sharing, scheduling and embedding. | Separate question answering from dashboard composition. Reuse the same semantic and query system for both. | Administrator enablement and edit permissions are required. Insight tiles are explicitly Early Access. Do not infer that all AI features have the same release status. |
| Looker Conversational Analytics | A dashboard agent answers questions about the dashboard and underlying query-linked content. Explore agents use LookML, field values and agent configuration. | Put conversation beside the dashboard. Centralize reusable calculations in the semantic model. | Dashboard agents are Preview. The reviewed documentation is not evidence that the agent can author a complete persistent dashboard. |
| Tableau Agent in Dashboards | Summarizes dashboards, identifies chart insights and answers questions against underlying workbook data. | Dashboard assistance can create value before automatic dashboard creation exists. | The dashboard feature is Beta. The documentation explicitly says it cannot build a dashboard. |
| Databricks Genie Agents | Curated context supports natural-language SQL, saved queries, visualizations, trusted query logic and benchmark evaluation. Published dashboards can include a companion Genie Agent. | Retain query lineage, curated definitions and regression questions. Connect dashboards and conversation through shared analytical objects. | Formerly named Genie Spaces. Inspect is Preview; Flash is Beta. Companion-agent credential behavior requires explicit review. |
| Wren AI | The current OSS documentation describes a context layer which supports governed SQL and deployable GenBI dashboards. | An inspectable semantic contract matters more than generating an attractive UI. Reuse existing semantic definitions. | The previous Docker chat-first GenBI app is now Wren GenBI Classic, marked sunset with no security fixes. Current documentation still contains older product paths. Do not adopt the old architecture without checking the maintained code and release. |

### Power BI sources

Copilot report creation is a natural-language authoring workflow. The result is a normal saved report. The documented limits include custom visuals, styling and formatting changes, real-time streaming models and some other model configurations. This establishes a distinction between creating useful BI content and generating arbitrary UI code.

Source: [Create and edit Power BI reports with Copilot](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-create-reports), updated 9 July 2026.

For semantic-model questions, Copilot uses model schema, linguistic schema and model properties. It can return a visual, summary or clarification request. Its query language includes DAX; GenBI does not always mean direct natural-language-to-SQL.

Source: [Use Copilot with semantic models](https://learn.microsoft.com/power-bi/create-reports/copilot-semantic-models).

### ThoughtSpot sources

Spotter supports follow-up questions, editable query tokens, chart/table views and saved Answers. Users can change measures, attributes, filters and drill dimensions. This makes the interpreted question visible and correctable.

Source: [Getting started with Spotter](https://docs.thoughtspot.com/cloud/26.9.0.cl/spotter-getting-started).

SpotterViz selects permitted models, creates related Answers, groups them and builds a Liveboard. It can revise charts, layout and styling. Generated Liveboards use live warehouse connections. They retain standard sharing, scheduling, exporting and embedding. Access follows existing row, column and data controls. The page distinguishes Early Access insight tiles from its other functions. It also warns that new parameter-based formulas are unreliable; create those Answers manually first.

Source: [SpotterViz](https://docs.thoughtspot.com/cloud/26.9.0.cl/spotter-viz).

Liveboards hold saved Answers and support filtering, drilling, value exclusion and exploration. View and edit permissions are distinct. A saved Answer retains a query rather than only a frozen picture.

Source: [Using Liveboards and Answers](https://docs.thoughtspot.com/cloud/26.10.0.cl/liveboards).

### Looker sources

Looker's dashboard conversation uses a data agent connected to the dashboard and its query-linked tiles. Dashboard creators can enable or disable the experience and add instructions. The feature is explicitly Preview.

Source: [Query a user-defined dashboard with a dashboard agent](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data-agents-dashboards).

Looker recommends clear field descriptions, labels, synonyms, curated Explores and centralized calculations. Ambiguous names, inconsistent types, time zones and values can produce incorrect queries. Important dashboard calculations should become reusable model measures or dimensions. Context quality and query performance affect the user experience.

Source: [Best practices for configuring Conversational Analytics](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-best-practices).

### Tableau source

The dashboard agent provides overview, insight and Q&A functions. It follows Tableau permissions and row-level security. Users need the relevant AI and full-query permissions. The reviewed page states that this feature cannot build a dashboard. It is Beta, with platform and edition prerequisites.

Source: [Tableau Agent in Dashboards (Beta)](https://help.tableau.com/current/pro/desktop/en-us/dashboard_narratives_overview.htm).

### Databricks sources

Genie Agents use table metadata and curated context to produce read-only SQL. Authors can provide definitions, relationships, example queries and verified parameterized queries or functions. Benchmarks are evaluation material rather than training context. Chat mode handles simple structured questions; Agent mode investigates across multiple steps. Normal Genie Agent data access uses the viewer's identity and enforces Unity Catalog controls. Inspect remains Preview; Flash remains Beta.

Source: [Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts), updated 12 October 2026.

Published dashboards can automatically create a companion agent, link an existing one or disable it. The selected chart can supply question context. A critical detail: autogenerated agents follow the dashboard credential model, including publisher credentials when embedded credentials are used. The agent can access the full dataset query output, including fields absent from visible charts. Linked agents follow their own credential settings.

Source: [Genie Agents with dashboards](https://docs.databricks.com/aws/en/dashboards/genie-spaces), updated 11 September 2026.

Users can inspect SQL, refresh the prior query or regenerate a response. Those are separate actions. Authors can correct queries and promote useful examples into instructions. Benchmarks compare returned data with reference SQL in chat mode; agent-mode evaluation uses an LLM judge. Realistic question variations and manual review remain necessary.

Source: [Test and monitor a Genie Agent](https://docs.databricks.com/aws/en/genie-agents/monitor), updated 17 September 2026.

### Wren sources

The current OSS introduction separates Generate, Deploy and Know. It describes structural, semantic and business context as shipped, with operational and behavioral context in development. It states that the prior Docker GenBI application is sunset. Old chart and dashboard-cache guides remain discoverable, so their existence does not establish current implementation support.

Source: [Wren AI OSS introduction](https://docs.getwren.ai/oss/introduction).

Wren says its context layer can sit above an existing warehouse, transformation pipeline and semantic layer. It does not replace them. The agent-facing definitions are intended to remain inspectable and version controlled. The page also distinguishes the primitive context layer from a turnkey chat application.

Source: [Where Wren AI sits in the stack](https://docs.getwren.ai/oss/concepts/stack_position).

## Recommended patterns for this project

The following are design conclusions drawn from the sources. They are not claims of product parity.

1. Keep one governed analytical path. The dashboard planner states the business question and needed views. The query specialist resolves definitions and retrieves evidence.
2. Store the dashboard definition as a durable object. Keep layout, metric and chart references, filter definitions, source scope and revision identity.
3. Store data snapshots separately from reusable query definitions. A saved snapshot supports reproducibility. A saved query supports refresh.
4. Make the meaning of each filter explicit. A filter needs an approved field, operator, value type, scope and default. Matching labels do not establish a shared business dimension.
5. Distinguish visual edits, local display operations and new data questions. A title change needs no query. A new period, grain or population can need fresh SQL.
6. Support refresh without asking the model to reinvent the query. Re-run a reviewed query or validated parameterized plan under the current user's permissions. Recheck authorization and source scope each time.
7. Keep dashboard access and data access separate. A user who can view a dashboard must not automatically gain access to all its source rows or saved evidence.
8. Keep published evidence immutable. New data creates a new revision or refresh result. Do not quietly change the facts behind a published answer.
9. Let users inspect and correct the interpreted question. Show metric definitions, time window, filters, grain and last source refresh.
10. Evaluate the whole interaction. Test filter changes, drill requests, follow-up context, denied fields, stale data and cross-user isolation. SQL accuracy alone is insufficient.

## Text-to-SQL position

Text-to-SQL is the governed retrieval capability inside the product. It is not the complete GenBI product. The product also needs metric definitions, query review, saved evidence, dashboard state, rendering, event handling, permissions and publication.

Not every click should invoke an LLM. A chart-format change is a UI operation. A valid saved filter action can execute a reviewed query plan. A new analytical question needs semantic grounding and query planning. Statistical work continues through the data-analysis specialist.

Do not compute new business totals from a displayed sample or pre-aggregated chart without proof that the operation is valid. Averages, ratios and distinct counts often cannot be added across groups. This is a design constraint, not a product claim.

## Build or embed

These are decision criteria, not a vendor ranking.

| Choice | Prefer it when | Main obligation |
|---|---|---|
| Build a dashboard feature above the present agent | Existing OSI definitions, reviewed file workspaces and saved analytical evidence are core product assets. The team needs control of interaction and presentation. | Own dashboard state, rendering, authorization, refresh and interaction tests. |
| Embed an established BI product | A selected vendor already owns the organization's metrics, user permissions and dashboards. The product mainly needs a branded entry point and conversation. | Confirm licensing, identity propagation, embedding permissions, export rules and exact feature availability. |
| Use vendor query capabilities behind a custom UI | A vendor's semantic engine and governed query API are needed, but a custom workspace remains important. | Avoid duplicate business definitions. Establish one query authority per source and verify API coverage. |

Before choosing an embedded product, run the same business scenario through its real embedded surface. A capability in the vendor's full application may be absent from its embed SDK or API. For example, Databricks documents companion Ask Genie support in basic dashboard embedding, while external embedding requires a separate conversation API integration.

Source: [Genie Agents with dashboards](https://docs.databricks.com/aws/en/dashboards/genie-spaces).

For this repository, building the dashboard feature is the default recommendation. Embedding becomes stronger if a chosen BI platform already supplies the authoritative semantic model and authorization system. Avoid keeping two competing definitions of the same metric.

## ASD-STE100 guidance for the proposal

The official standard is ASD-STE100 Issue 9, dated 15 January 2025. It includes writing rules and a controlled dictionary. Use it as a writing guide; do not claim certification or measured 80% compliance without a defined assessment.

Apply short descriptive sentences, one topic per paragraph, consistent terms, direct verbs and limited noun clusters. The standard gives a 25-word limit for descriptive sentences and 20 words for procedural sentences. Keep required technical names, define them once and use them consistently.

Source: [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf).

An operational interpretation of the user's request: use STE principles for at least 80% of explanatory prose. Allow established product names, protocol terms and concise comparison-table fragments. State that the result is STE-informed, not formally compliant. A sentence-length check can support editing, but it cannot establish dictionary or full-standard compliance.
