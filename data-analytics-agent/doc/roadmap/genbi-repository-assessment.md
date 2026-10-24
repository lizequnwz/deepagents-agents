# Repository assessment for dynamic BI

Research date: 21 October 2026. Scope: repository inspection only. No source data was queried. No application code was changed. Tests were read, not run, for this assessment.

## Decision

Build dynamic BI as a product feature in the current agent. Add a dashboard design skill and typed dashboard tools. Keep the coordinator responsible for the answer and its evidence. Keep `text-to-sql` as the only owner of warehouse execution. Keep `data-analysis` for statistical and predictive work.

A new presentation subagent is optional later. It should receive saved evidence IDs and return a validated dashboard proposal. It should have no source tools. A separate agent would duplicate the present data, semantics, evidence and recovery paths without solving the main missing capability.

The missing capability is a dashboard runtime: persistent views, declared filter state, component bindings and safe user actions. A new agent alone cannot provide that runtime.

## Current architecture and evidence

| Area | Verified implementation | Implication |
|---|---|---|
| Application shell | Streamlit calls FastAPI. The source-bound coordinator builds the two specialist agents. See [architecture.md](../development/architecture.md#responsibilities-and-persistence), `data_analytics_agent/coordinator.py:118`, `:201`, `:287`. | A new front end can reuse the API and analytical core. There is no need to rebuild analysis to change the renderer. |
| Coordinator | Owns `create_chart`, `publish_findings`, `create_report` and investigation state. It loads reporting and workflow skills. `coordinator.py:146`, `:199`, `:279`, `:293`. | Dashboard composition naturally extends the present presentation responsibility. |
| SQL specialist | Has semantic discovery, value lookup and warehouse execution only for warehouse conversations; saved-result SQL is always available. `agents/text_to_sql/agent.py:34`, `:58`, `:86`, `:129`. | Dashboard data requests must preserve this ownership. Do not give a dashboard specialist direct warehouse credentials. |
| SQL controls | Validates one read-only query, exact declared objects, canonical metrics, declared relationship keys and fan-out risk. `backends/validation.py:51`; `semantic_sql.py:38`, `:65`, `:264`, `:409`, `:498`. | UI controls cannot bypass semantic and execution validation. Read-only syntax is one control, not a complete tenant security boundary. |
| Saved-result SQL | Binds explicit artifact IDs to table aliases in DuckDB. External access is disabled. Presentation datasets are rejected as analytical inputs. `agents/text_to_sql/tools.py:154`, `:173`, `:188`, `:196`, `:203`. | Filtering or regrouping a complete saved dataset can reuse the existing shaping path. Chart samples cannot be used to recompute business totals. |
| Python specialist | Receives named saved datasets; runs isolated Python executions and returns saved outputs. It has an explicit analysis skill and no source tool. `agents/data_analysis/agent.py:24`, `:53`, `:65`. | Use it for forecast, inference and model work. A chart layout or simple filter does not need Python. |
| Charts | Strict declarative `ChartRequest` and stored `ChartSpec`; 11 chart types; explicit interval meaning and forecast boundary. `visualization/schemas.py:18`, `:22`, `:46`, `:90`, `:382`. | Reuse these contracts and Plotly rendering before selecting a new chart engine. A2UI can host a trusted chart component that refers to an existing chart ID. |
| Display limits | A chart can have at most 5,000 display rows and 4 MiB. Sampling creates a separate presentation dataset with parent lineage; unsuitable chart types require prior aggregation. `visualization/tools.py:85`, `:93`, `:113`, `:120`. | A browser chart is a presentation product, not proof of complete analytical coverage. Preserve this distinction in linked filters and drill actions. |
| Reports | `ReportSpec` contains typed narrative, metrics, callouts, infographics, tables, charts and analyses. Numeric metrics bind to saved cells. The agent cannot submit executable markup. `reporting/schemas.py:95`, `:117`, `:176`, `:188`; `reporting/tools.py:201`. | The project already uses a declarative UI pattern. Build on it; do not switch to model-authored arbitrary HTML/JavaScript. |
| Evidence | `EvidenceResolver` scopes results, charts and analyses by conversation and source, and resolves parent lineage. `evidence.py:7`, `:13`, `:21`, `:36`. | Bind dashboard components to application-verified IDs. Do not let the model invent values, table names or evidence relationships. |
| Publication | `publish_findings` resolves references; reporting then requires the published findings. Computation ends at publication, and report completion ends the turn. `presentation.py:99`; `reporting/tools.py:231`; `doc/development/architecture.md:107`. | A dashboard interaction that changes data must start a separate action/run. It must not mutate a previously published analytical turn. |
| Revisions | Direct title, label, palette and compatible chart-type edits need no agent or source. The app creates matching chart/report versions, then atomically changes the view pointer. It rejects stale IDs. `presentation_edits.py:14`, `:53`, `:66`, `:97`, `:118`, `:172`. | Use this pattern for dashboard revisions. Appearance changes should remain deterministic and inexpensive. |
| Persistence | SQLite metadata, a separate graph checkpoint database and file artifacts; tool-call commits support resumption. `persistence.py:15`; `api.py:348`; `doc/development/architecture.md:49`. | A durable dashboard can use the same storage mechanism at current local scale. Do not introduce another persistence framework for the first version. |
| UI updates | An active-run Streamlit fragment polls the API each second with an event cursor. Chart rendering calls `st.plotly_chart` without selection callbacks. Reports display in `st.iframe`. `streamlit_app.py:208`; `ui/components.py:1258`, `:1372`. | The existing product supports plot-level interactions such as hover/zoom, but it has no implemented global filter or linked-chart action contract. Polling is activity transport, not an A2UI stream. |
| Deployment | The documented target is one local user, one API process, one warehouse or isolated file workspace per conversation. `README.md:1`; `doc/development/architecture.md:151`. | A multiuser BI product needs an explicit deployment and identity design in addition to the front-end work. |

All code paths above are relative to the repository root. They are implementation evidence, not external product claims.

## Missing dashboard capabilities

The strict `ReportSpec` has no filter, action, query binding, shared dashboard state, responsive grid or refresh definition. It is a report document, even though its embedded Plotly charts provide local interaction. No saved `DashboardSpec` or dashboard API is present in the inspected application paths.

Add the following in layers:

1. A stored dashboard definition with stable ID, revision, source/conversation scope, layout and component references.
2. A small trusted component catalog: metric, chart, table, text, category filter and date filter.
3. Explicit filter scope. Declare which components a filter controls and which dataset fields it can use.
4. A typed action request with dashboard revision, component ID, action name, values and a request identity. Reject unknown actions, fields and stale revisions.
5. A server-side query binding and execution record for each affected component. Save the resulting data and lineage before updating the dashboard view.
6. A visible freshness and completeness state. Source-query time does not prove source cutoff; imported files remain snapshots until explicitly replaced.
7. Save, reopen and revise. Preserve prior evidence and report versions.

For the local first release, bind components to complete saved evidence and support a small declared filter set. Build a complete usable dashboard before adding automated refresh, scheduled jobs, shared editing or multiple rendering protocols.

## Skill, subagent, feature or independent agent

| Choice | Assessment |
|---|---|
| Skill only | Insufficient. A skill supplies model instructions, not persistent state, validation, rendering or action handling. Use it to teach layout, chart choice, filter semantics and revision rules. |
| Feature plus coordinator skill | Recommended first design. It reuses evidence ownership, publication, storage and the existing analytical specialists. Typed tools create and revise the dashboard. |
| Presentation subagent plus skill | Useful only when composition becomes a distinct multi-step task with substantial context. Restrict it to saved evidence and a presentation catalog. It should return a candidate definition to the coordinator; application code validates it. |
| Independent GenBI agent | Justified only for a separately owned product with a different user journey, security boundary or deployment lifecycle. It should still call the same semantic/data services. Current requirements do not establish this need. |

Deep Agents custom subagents receive their tools and skills explicitly. Adding a third agent also changes the current harness assumption that there are two owned specialists (`coordinator.py:106`) and delegation rules (`delegation.py:20` routes every non-analysis task through the source semaphore). Do not treat a new subagent as a configuration-only change.

## Text-to-SQL in a dynamic dashboard

There are three distinct operations:

| Operation | Correct owner and behavior |
|---|---|
| Change a title, color or compatible chart type | Deterministic presentation service. Reuse the existing data. No SQL and no LLM are needed. |
| Filter or regroup a complete saved population | Saved-data SQL owned by `text-to-sql`, with explicit result bindings and a new saved result. Do not use the 5,000-row display artifact. |
| Add a metric, request missing detail, extend time/population or ask for current warehouse values | Coordinator sends a complete business brief to `text-to-sql`; it grounds definitions and executes source SQL sequentially. Python is used only if additional statistical work is needed. |

For the first version, the present specialist can handle new dashboard requests. To make repeated filter interactions fast, introduce declared parameters over server-owned, validated query definitions in a later layer. Reuse the SQL owner's validation and execution service. Do not create a second path from the browser or renderer to the warehouse. The current `execute_sql(query, purpose, metric_names, relationship_names)` contract does not yet implement parameterized dashboard query bindings.

Do not let the language model regenerate arbitrary SQL for every click. A UI event with already declared meaning should use deterministic application logic. A new business question can invoke the agent.

## Reporting and consistency constraint

The present policy requires a compact HTML report for every data-backed answer. A dynamic dashboard should complement that report. It should not silently replace it.

Opening or changing the appearance of an existing view does not create new evidence. A filter that computes a new population does create new evidence. The implementation must decide whether it is a view-only interaction over a declared complete snapshot or a new analytical action, and keep the distinction visible. When an action publishes a new data-backed answer, create its report from that action's selected evidence. Keep the previous report attached to the previous evidence.

A2UI messages would be a UI delivery format. They should not become the authoritative source of numerical values, semantics, source access rules or durable business query definitions. Use application-owned definitions and saved artifacts for those concerns.

## Front-end implications from repository evidence

Streamlit remains an economical choice for a local Python product. The project already has a useful API boundary, native Plotly charts and persistent evidence. A basic typed dashboard can therefore be added without a full front-end replacement.

A separate React front end becomes more valuable if the product needs persistent multi-panel workspace state, linked charts, responsive layout editing, deep links to saved views, extensive interaction and a reusable component catalog. This is an architectural judgment; actual A2UI renderer and framework support must be checked from current external documentation.

Do not build a temporary A2UI-to-Streamlit bridge and promise to discard it later. Either keep Streamlit with a deliberate supported dashboard scope, or build the intended dashboard experience on the long-term front end. The existing Streamlit application can remain a working analytical interface while the new feature reaches end-to-end acceptance; it need not become a compatibility layer.

## Hosting and access boundary

The existing artifact scoping protects agent operations from cross-conversation/source mistakes. It is not user authorization. FastAPI constructs a local application without an identity layer (`api.py:344`), and result/report endpoints read artifacts with `page_unscoped`, `get_unscoped` or `response_unscoped` (`api.py:953`, `:1146`, `:1184`).

Before hosted sharing, add identity and server-side access checks for every conversation, dataset, chart, report, export and UI action. Source permissions, any row policies and cache isolation must be enforced by trusted services. A2UI and a React front end do not supply these controls. This is a material scope decision for a shared product, not a reason to block a local dashboard proof.

## Existing verification worth extending

The following tests are evidence that the repository has useful test seams. Their presence does not assert a fresh passing test run:

- `tests/test_agent_workflow.py:114`: descriptive question through the real harness produces a report.
- `tests/test_presentation_edits.py:93`: evidence is unchanged; matching revisions survive restart; stale edits fail.
- `tests/test_presentation_edits.py:126`: rendering failure retains the previous pair.
- `tests/test_presentation_edits.py:171`: direct presentation edits need neither source nor model; data bindings cannot change.
- `tests/test_analytical_charts.py:201`: analytical charts reject truncated or sampled inputs.
- `tests/test_semantic_grounding.py:368`: source SQL is checked before execution, including reviewed edits.
- `tests/test_streamlit_workflow.py:106`: activity identity survives publication.

Dashboard acceptance should extend these guarantees: the same declared filter produces matching metric/chart/table populations; stale actions cannot replace newer views; a retry does not duplicate committed execution; incomplete data remains visible; numerical components bind to stored evidence; display samples never become analytical populations; failed refresh retains the last valid view with a clear status.

## Smallest durable implementation path

1. **Saved dashboard feature.** Define typed dashboard state and trusted components. Compose saved metrics/charts/tables through the coordinator plus skill. Save, reopen and export a report. Use the chosen intended front end.
2. **Declared interactions.** Add category/date filters, explicit scope, action validation and saved-data SQL. Verify totals and lineage across components. Add drill only when the required grain is available.
3. **Fresh data.** Add explicit refresh and typed server-side query bindings through the SQL owner. Preserve schema/semantic validation, source limits and one source assignment at a time.
4. **Protocol and shared product.** Prove A2UI rendering with the actual BI component catalog. Add it only where interoperability has value. Add hosted identity, permissions and scheduling when sharing is an approved product requirement.

This order adds each capability to a working product. It does not require obsolete-path fallbacks, duplicate analytical agents, arbitrary code generation or a speculative multi-protocol framework.
