# GenUI protocol evaluation

25 October 2026. This review records the integration boundary and package evidence.

## Decision

Keep `RunManager`, `DashboardSpec`, saved evidence, and published revisions as the
application authorities. Export a small analytical evidence surface in A2UI.
Use AG-UI event types for the public run projection. Keep the local evidence panel
on the canonical dashboard renderer. Do not ship the A2UI runtime dependency tree
until its Zod 3 dependency has a compatible security fix. Do not add CopilotKit's
agent runtime in this increment.

A2UI and AG-UI serve different purposes. A2UI describes UI components. AG-UI
describes agent interaction events. Neither establishes the truth of a value,
authorizes a data request, or replaces the application state model.

## A2UI package and implementation evidence

The npm registry returned version **0.14.0** for both `@a2ui/react` and
`@a2ui/web_core`. The published tarballs were downloaded and their types inspected.
The React package identifies the maintained `a2ui-project/a2ui` repository, uses the
Apache-2.0 license, and supports React 18 and 19. It declares a Zod `^3.25.76` peer.
The integration proof used these exact releases. The runtime packages were then
removed after the dependency review below. The server compiler has no A2UI npm
dependency and remains available as a validated export contract.

The typechecked renderer experiment imported `A2uiSurface` and `createComponentImplementation` from
`@a2ui/react/v0_9`. It imports `Catalog`, `MessageProcessor`, `CommonSchemas`, and
`STRICT_VALIDATION` from `@a2ui/web_core/v0_9`. The published message schemas accept
both `v0.9` and `v0.9.1`. This integration emits only `v0.9.1`.

The server compiles a resolved `DashboardView` into `createSurface` and
`updateComponents`. The trusted catalog contains `EvidencePanel`, `MetricRef`,
`ChartRef`, `TableRef`, and `EvidenceRef`. Messages carry component and dataset
references. They carry no metric values, data rows, chart figures, model-generated
HTML, or executable functions. A future maintained renderer can obtain values from
the canonical dashboard response.

The experiment included revision and reference checks before official processor
validation of component properties and topology. It passed the production build.
Browser interoperability verification was not completed before dependency review
stopped runtime adoption. The retained server contract fixes the inspection action
to the current revision and a saved dataset. It cannot query a warehouse, run an
agent, or commit a view.

This is a bounded compiler and export proof. It does not claim a shipped local
A2UI renderer or support for every A2UI
component, v1.0 RPC, multiple UI platforms, or model-generated layouts. The catalog
is deliberately small. The compiler retains the established dashboard contract.

Official references:

- [Current A2UI protocol](https://a2ui.org/specification/v0.9.1-a2ui/)
- [Maintained renderers and version support](https://a2ui.org/reference/renderers/)
- [Catalog validation and security](https://a2ui.org/guides/defining-your-own-catalog/)
- [Action integrity and data model isolation](https://a2ui.org/concepts/actions/)
- [Published React package](https://www.npmjs.com/package/@a2ui/react/v/0.14.0)
- [Published processor package](https://www.npmjs.com/package/@a2ui/web_core/v/0.14.0)

## Upstream runtime dependency blocker

On 25 October, `npm audit` reported five findings in the newly introduced
production dependency tree. They were not existing development-tool findings.
`@a2ui/markdown-it` 0.2.2 pins DOMPurify 3.4.11. The sanitizer advisories include a
critical issue fixed in 3.4.17. A same-major override could address this dependency.

The more restrictive blocker is Zod. The latest Zod 3 release in the registry is
3.25.76. A high-severity resource exhaustion advisory affects versions below
4.6.6. The maintained A2UI packages require Zod `^3.25.76` and use its APIs. No
patched compatible Zod 3 release was available. Forcing Zod 4 into that peer range,
aliasing its legacy code, or downgrading the renderer would not establish a safe,
supported integration. The runtime adoption is therefore deferred. The app uses
the patched Zod 4 line for AG-UI, which supports that major version.

The critical DOMPurify issue requires non-default template and DOM-returning
configuration plus downstream template evaluation. The custom catalog did not
expose Markdown, HTML, or that path. The bounded server-generated payload also
limited the Zod attack surface. These facts reduce exposure; they do not make the
new dependency tree free of known vulnerabilities.

- [Zod resource exhaustion: fixed in 4.6.6](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)
- [DOMPurify shadow-root template bypass: fixed in 3.4.17](https://github.com/advisories/GHSA-cg2g-xh64-v4q7)

## AG-UI boundary

The run event endpoint attaches to an existing run. It does not use a stock
`LangGraphAgent` to invoke the same graph through a second route. It exposes a
selected public state and safe lifecycle labels. It does not stream raw graph
state, tool arguments, code, or source records.

The application owns attachment and replay. The standard AG-UI HTTP/SSE binding
does **not** provide stream resumption or `Last-Event-ID` handling. The application's
GET attachment is a separate transport that carries AG-UI events. It must not be
described as a complete implementation of AG-UI's POST run binding.

Approval, clarification, and data actions retain the existing admission and
review endpoints. A reconnect must not create a new execution. A published
dashboard replaces the prior revision only after evidence and the HTML report
are ready.

Official references:

- [Lifecycle and cancellation](https://docs.ag-ui.com/spec/1.0/events/lifecycle)
- [State and trust boundaries](https://docs.ag-ui.com/spec/1.0/events/state)
- [Interrupt and resume contract](https://docs.ag-ui.com/spec/1.0/basic/patterns/interrupt-resume)
- [Version declarations](https://docs.ag-ui.com/spec/1.0/basic/versioning)
- [HTTP/SSE binding and absence of stream resumption](https://docs.ag-ui.com/spec/1.0/basic/transports/http-sse)

## CopilotKit runtime decision

CopilotKit supplies useful React hooks, including `useAgent`, `useRenderTool`,
`useFrontendTool`, and `useInterrupt`. Its headless entry can avoid a standard chat
layout. These are candidates if they reduce future interface work.

Do not add its runtime merely to render A2UI. The maintained renderer experiment
typechecked with the existing application, but its dependency blocker remains.
A second execution and persistence layer would
need a defined owner for run identity, interrupts, cancellation, history, and
published revisions.

The current direct-connection documentation places production
`selfManagedAgents` in the Enterprise Intelligence tier.
`agents__unsafe_dev_only` is explicitly for local development. Durable AG-UI
Streams are capabilities of CopilotKit Intelligence, not guarantees of the open
AG-UI protocol. Licensing, deployment, and data handling must be evaluated before
this product path is selected. No paid service or external runtime is enabled.

Official references:

- [Headless agent hook](https://docs.copilotkit.ai/reference/hooks/useAgent)
- [Rendering backend tools](https://docs.copilotkit.ai/reference/hooks/useRenderTool)
- [Interrupt hook](https://docs.copilotkit.ai/reference/hooks/useInterrupt)
- [Production self-managed agent terms](https://docs.copilotkit.ai/deepagents/backend/self-managed-agents)
- [Runtime and persistence ownership](https://docs.copilotkit.ai/deepagents/backend/agent-runner)
- [Durable event delivery](https://docs.copilotkit.ai/deepagents/threads)

## Verification limits

The compiler tests use real saved dataset, chart, report, and dashboard fixtures.
They check reference integrity, empty populations, deterministic output, and
rejection of inline values or unknown components. Any future renderer adoption
must pass dependency review and browser verification of the maintained processor,
renderer, inspection action, revision change, and cleanup. Scripted fixtures do
not establish live-model analytical accuracy.

Deterministic filters currently require finite metric values. A filter can leave
rows whose aggregate is NULL. That result cannot yet replace a numerical metric
card. The action fails and preserves the prior dashboard and report. The system
does not turn an unavailable value into zero. A complete unavailable-value path
for cards, charts and reports remains a separate capability.
