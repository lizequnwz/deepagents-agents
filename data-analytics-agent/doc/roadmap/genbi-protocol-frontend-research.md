# A2UI and front-end research notes

Research date: 21 October 2026. Scope: official documentation and project sources. These notes support the GenBI decision proposal. They do not claim that a working integration was tested.

## Findings that change the decision

1. A2UI is now beyond its first v0.8 release. The official site names **v0.9.1 as the current production release**, v0.9 as the previous stable release, v0.8 as legacy, and v1.0 as a candidate. The v1.0 candidate adds RPC action responses and other contract changes. Do not base the first release on candidate features. [A2UI home](https://a2ui.org/)
2. The repository still describes the overall project as **early-stage public preview**. Its functional protocol and renderers continue to evolve. Treat protocol stability and product maturity as separate questions. [A2UI repository](https://github.com/a2ui-project/a2ui)
3. The maintained renderer matrix lists **React, Lit, Angular and Flutter as stable for v0.9.1**. It lists v1.0 support as planned. Jetpack Compose is alpha for v0.9.1. Documentation is not fully aligned: client setup still has an older planned-Compose entry, and Flutter's own documentation calls the `genui` package alpha and experimental. Report the claimed protocol support separately from SDK maturity. [Renderer reference](https://a2ui.org/reference/renderers/), [client setup](https://a2ui.org/guides/client-setup/), [Flutter SDK status](https://docs.flutter.dev/ai/genui)
4. Streamlit can host a modern interactive A2UI renderer. Its current component API supports JavaScript/TypeScript bundles, persistent state, event triggers, JSON and Arrow exchange. Components v2 run inside the page rather than in an iframe. A Streamlit A2UI bridge is technically feasible; a native A2UI-to-Streamlit renderer is not listed in the maintained matrix. [Streamlit component overview](https://docs.streamlit.io/develop/concepts/custom-components/overview)
5. **A2UI does not supply a BI product.** Its basic catalog supplies layout, media and input components. It has no built-in chart, data table or KPI component in the current specification. The application must supply these trusted BI components and their data contracts. [A2UI v0.9.1 basic catalog](https://a2ui.org/specification/v0.9.1-a2ui/#basic-component-catalog)

## A2UI contract and application responsibilities

A2UI transmits JSON instructions for a UI. It separates component structure from application data. Its four server messages create a surface, update components, update data, or delete a surface. A surface has a fixed catalog ID. The client sends named actions with the originating surface, component and action context. Capabilities travel in transport metadata. Ordered delivery and explicit message boundaries are required. SSE and WebSocket are possible transports. [A2UI v0.9.1 specification](https://a2ui.org/specification/v0.9.1-a2ui/)

An agent-generated action is a request to the application. It is not authorization to query a warehouse or disclose data. For this repository, server code must resolve every dataset ID, field reference, filter and drill action against the conversation, approved semantics and current user rights. This is a design recommendation, not a feature of the protocol.

Define a small catalog that matches the actual BI components. A useful first catalog contains a dashboard grid, metric card, existing chart, data table, filter bar, evidence link, loading state and error state. Use opaque saved evidence IDs as bindings. Let application code supply values. Do not let the agent invent numbers inside component properties.

The official catalog guide recommends catalogs that directly reflect the application's design system. Register trusted components, validate properties and sanitize text. The official custom component guide shows an interactive chart example, but this is an example to extend, not a complete BI chart catalog. [Catalog guide](https://a2ui.org/guides/defining-your-own-catalog/), [custom component guide](https://a2ui.org/guides/authoring-components/)

Reuse the maintained renderer and its shared `@a2ui/web_core` processor. The shared package owns message processing, surface state, data bindings, component models, schemas and expression evaluation. Avoid a second home-grown protocol engine. Pin the protocol and catalog versions for the first release. [Renderer development guide](https://a2ui.org/guides/renderer-development/)

## A2UI, AG-UI, MCP and MCP Apps

| Item | Role | Decision for this project |
| --- | --- | --- |
| A2UI | Declares a UI using JSON messages and a component catalog. | Use when the agent needs to compose or revise the interface. It is not the source of business meaning. |
| AG-UI | Connects an agent runtime with an interactive application. | Optional transport/event contract. Useful for streamed run status, shared state, cancellation and interactive actions. |
| MCP | Connects an agent with external tools and data systems. | Optional connector boundary. It does not replace semantic grounding, SQL ownership or dataset authorization. |
| MCP Apps | Displays an interactive HTML app inside a compatible MCP host. | Consider for distribution inside another assistant. It does not supply the standalone BI workspace. |
| A2A | Connects distributed agents. | Not required to add an in-process dashboard feature to the current coordinator. |

AG-UI distinguishes its runtime connection from A2UI's UI specification and from MCP's tools/data connection. Its Python SDK includes run lifecycle, text, tool, state snapshot, state delta and custom events. These can carry A2UI updates, but a direct SSE implementation can also meet A2UI's transport contract. [AG-UI overview](https://docs.ag-ui.com/introduction), [AG-UI events](https://docs.ag-ui.com/sdk/python/core/events), [A2UI transports](https://a2ui.org/concepts/transports/)

MCP Apps return interactive HTML resources and use a host-controlled sandboxed iframe. This has a different rendering and security model from A2UI's native trusted components. It also differs from Streamlit Components v2, which are not sandboxed. [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview), [Streamlit component API](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.component)

## Streamlit assessment

### What the current platform can do

The checked repository requires `streamlit>=1.59.2`. The installed package includes Components v2 and `st.App` documentation. These are local code facts, not deployment claims.

Components v2 provides state values that persist across reruns and one-time event triggers. A packaged React or Lit renderer can keep local visual state and send material actions to Python. Use stable dashboard/component IDs. Use state for filter selections and triggers for requests such as refresh or drill. [State versus triggers](https://docs.streamlit.io/develop/concepts/custom-components/components-v2/state-and-triggers), [packaged components](https://docs.streamlit.io/develop/concepts/custom-components/components-v2/package-based)

Fragments rerun only part of a Streamlit application and support independent updates. Forms can batch related changes. These features reduce unnecessary execution. They do not remove the need for a deliberate state model. [Streamlit fragments](https://docs.streamlit.io/develop/concepts/architecture/fragments)

Do not assess Streamlit using old limits. Official 2026 release notes include `st.App` and Starlette/Uvicorn support, later event-scoped fragments, async app code and native ECharts. The latest release page identifies 1.66.0, released 14 October 2026. The project's dependency minimum does not prove that all of those later features are installed. [2026 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026), [latest release notes](https://docs.streamlit.io/develop/quick-reference/release-notes)

### Fit and tradeoffs — engineering judgment

Keep Streamlit when the product is an internal analytics workbench, Python ownership matters, pages have a modest number of linked controls, and the present review workflow is the main user experience. It can be a long-term choice for that scope.

Prefer React for an interaction-heavy product with a persistent canvas, linked filters, drag-and-drop layout, URL state, undo/redo, saved views, embedded delivery and detailed design control. This recommendation reflects the amount of client-side state and interaction required. It is not a claim that Streamlit cannot implement these features.

Embedding a full React dashboard in Streamlit retains the Python shell but creates two state lifecycles. It is reasonable when the dashboard is one bounded panel and the shell remains useful. If the custom panel owns most of the product, a direct React application is simpler to maintain.

Components v2 Shadow DOM provides **style isolation only**. Its JavaScript has normal app-page privileges. Ship trusted renderer code. Send declarative data from the agent. Never treat Shadow DOM as a sandbox for generated scripts. [Streamlit API security note](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.component)

## Front-end options

| Option | Strength | Cost or limitation | Recommendation |
| --- | --- | --- | --- |
| Native Streamlit + fixed dashboard schema | Lowest change to this application. Reuses charts, controls and Python review flow. | Less direct control over a complex interactive canvas. No native A2UI renderer is documented. | Strong option for internal users. |
| Streamlit + packaged A2UI React/Lit component | Reuses the shell and a maintained A2UI renderer. | Must synchronize component and Python state; a large custom panel can duplicate application concerns. | Use for a bounded pilot only when the shell remains part of the target product. |
| React + Python API | Full client state control. Maintained A2UI renderer. Existing analysis services stay in Python. | Requires front-end skills, API authentication, deployment and browser tests. | Preferred target for a durable GenBI workspace. |
| Next.js + Python API | Adds application routing and a server/client boundary to React. | Can create an unnecessary second server if Python already owns all application services. | Use if routing, hosting or server rendering requirements justify it. |
| Angular or Lit | Maintained A2UI choices with custom catalog support. | A new framework without team experience adds cost. | Choose only when it matches the team's existing stack. |
| Flutter | A2UI lists protocol support across mobile, desktop and web. | Flutter's own GenUI SDK remains alpha; adds another stack for a web-first BI product. | Use when native/mobile delivery is a real requirement. |

React's official state guidance covers shared and structured client state. Next.js explicitly uses Client Components for state, event handlers and browser APIs, with Server Components for server data and secrets. A dashboard canvas needs the client side regardless of whether Next.js is selected. Keep SQL credentials and source access in Python. [React state](https://react.dev/learn/managing-state), [Next.js server and client components](https://nextjs.org/docs/app/getting-started/server-and-client-components)

`json-render` is a credible catalog-driven alternative. Its own site describes predefined components and actions. Its A2UI page is explicitly a conceptual integration example and shows older protocol-shaped messages. Do not infer full current A2UI conformance from that page. Compare it only if the application prefers its own UI schema over a maintained A2UI renderer. [json-render](https://json-render.dev/), [A2UI integration example](https://json-render.dev/docs/a2ui)

## Recommended technical boundary

Use one canonical, validated dashboard artifact. Store BI meaning, dataset references, allowed interactions and layout there. Emit the A2UI catalog representation from the validated artifact. A2UI then acts as the delivery contract; it does not become the analytical database or evidence model.

Keep ordinary interactions deterministic. A client may change a selection or zoom a chart without an agent call. A filter that needs new source data must use an approved query contract on the server. A new business question, metric, grain or relationship must return to the coordinator and text-to-SQL specialist. This prevents every click from becoming a new unreviewed query.

Validate protocol conformance, catalog compatibility, evidence binding, action authorization and UI behavior separately. A valid JSON message can still show the wrong metric or expose data to the wrong person.

## A bounded validation experiment

Before selecting a replacement front end, implement the same thin interaction loop in the current Streamlit shell and a minimal React client. Use one tested dashboard artifact and the same Python service. Do not build two full products.

The test dashboard should contain two metrics, two charts, one table and two linked filters. Use existing complete saved results. Test one local filter, one source-backed drill action, a data refresh, a layout edit and a browser reload. The current chart stack should remain the chart renderer in both clients where feasible.

Record these checks. The pass limits below are proposed product gates, not measured results:

- Every displayed value resolves to the same saved evidence in both clients.
- A layout edit, chart zoom or local filter runs no warehouse query and no LLM call.
- A source-backed action calls the same authorized backend service and preserves the review policy.
- Dashboard state survives 20 interaction cycles and a reload. No filter resets or lost actions occur.
- A stale response cannot overwrite a newer filter state. Duplicate actions do not run twice.
- Both clients show loading, empty, error and incomplete-data states clearly.
- Local interactions meet a chosen latency target on a declared dataset and device. Measure actual browser behavior rather than total Python runtime alone.
- Check keyboard use, narrow layouts, focus order and access to chart evidence.
- Count renderer-specific state code and deployment steps. Prefer the option with fewer concerns for the required product scope.

Choose Streamlit if it passes the intended use cases and remains the smallest maintainable implementation. Choose React if the shell, rerun lifecycle or widget model causes material complexity in the tested target workflow. Do not treat a successful A2UI card demo as a completed BI integration.

## Maintained renderer implementation links

- [React renderer linked by the official matrix](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/react)
- [Lit renderer linked by the official matrix](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/lit)
- [Angular renderer linked by the official matrix](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/angular)
- [Flutter GenUI](https://docs.flutter.dev/ai/genui)
- [A2UI renderer status matrix](https://a2ui.org/reference/renderers/)

Package installability, full custom catalog compatibility and performance need the experiment above. This research checked documentation and source descriptions; it did not execute these renderers.
