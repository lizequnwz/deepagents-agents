# Design review and teaching acceptance

This is a self-review of the educational artifact, not a new audit of the Data plugin. It combines source checks, browser tests, and visual inspection. No audience study or timed rehearsal was conducted.

## New AI engineer

The opening creates a concrete need: analysis must survive inspection, editing, publication, and refresh. The four-word model comes before the detailed build/storage path. The same advisor request carries the audience from intent to delivery. Terms such as query ID and presentation state are introduced through examples before infrastructure names appear. Illustrative values are labelled at the point of use.

## Presenter

Fourteen scene anchors support a 27-minute plan. Keyboard navigation, visible scene controls, and optional live prompts support screen sharing. Presentation navigation uses immediate scene movement, so repeated advancement does not depend on scroll-animation timing. Normal scrolling remains available on smaller screens and for longer explorer content. Under the Hood sections are closed on entering presentation mode and restored on exit.

The live prompts occur in narrative order: routing after the mental model, workflow after the request, identity at the contract, and report/dashboard comparison at the surface choice. The skill explorer is intended for selecting two or three examples live, not reading all twenty entries aloud.

## Senior architect

Technical distinctions are kept explicit: skills are instructions rather than guaranteed worker processes; the walkthrough is a plausible route rather than an execution trace; notebooks do not necessarily use the shared React runtime; stable IDs are logical references rather than immutable content hashes; metadata is not proof of correct computation; view state is not access control; and source execution/authentication belong to host capabilities.

The stale-narrative exercise intentionally models a failure of meaning across two valid state domains. Its warning is identified as a teaching mechanism rather than an implemented automatic plugin detector. Under the Hood sections retain source constraints and important caveats after the main concept is understood.

## Curious engineer

Each major scene has a technical explanation and a source action. The drawer exposes exact paths, line ranges, verbatim excerpts, and copy controls. Skill summaries link to their own installed instruction files. The complete original review is embedded byte-for-byte, including its diagrams, evidence downloads, limitations, and test results; its controls work in the embedded viewer. The original Markdown can be downloaded offline.

## UX reviewer

Alternating dark, warm-paper, violet, and clay scenes establish a different rhythm from the original document. Four consistent colors reinforce the mental model. Different sections use different teaching forms: a comparison, a four-node map, a stepper, a family explorer, a provenance chain, a state lab, a runtime flow, a lifecycle, and a two-sided trade-off.

Desktop, laptop, tablet, narrow-phone, and landscape layouts were exercised. Controls work without hover. Reduced motion disables transitions; presentation advancement does not depend on motion. The source drawer uses native modal focus behavior and Escape. Manual clipboard fallback was revised into a selectable-text drawer that remains usable when clipboard access is denied. Focus colors differ between light and dark surfaces.

## Sixteen-question acceptance map

| Audience question | Answer made available | Scene |
|---|---|---|
| What problem is Data solving? | Durable analytical work beyond the immediate answer. | 1 |
| Agent, UI framework, skill library, or artifact system? | A plugin combining workflows and an artifact platform on a host agent; the model separates the roles. | 2, 8, 11 |
| What does the Codex host do? | Supplies agent execution, source tools, identity, and environment capabilities. | 3, 11 |
| What is a skill? | An instruction package defining an analytical responsibility. | 2, 4 |
| Why specialized skills? | Different cognitive jobs require different inputs, judgments, and stopping boundaries. | 4 |
| How does a question become a dashboard? | Intent → context → workflow → retrieval → analysis → evidence → authoring → validation → delivery. | 3 |
| What is reviewed evidence? | Saved rows with meaning, source requests, transformations, definitions, and limits. | 5 |
| Why preserve provenance? | Inspection and reproduction should not depend on hidden conversational state. | 5 |
| What is the artifact contract? | Structured relationships between artifact identity, query evidence, components, definitions, and presentation. | 6 |
| Why stable IDs? | Refresh, edits, source inspection, and references retain continuity. | 6 |
| Why two state domains? | Presentation edits should not silently rewrite analytical evidence. | 7 |
| Why a shared runtime/compiler? | Constrain variation and reuse common inspection/editing/delivery behavior across generated artifacts. | 8 |
| How do reports and dashboards differ? | A report guides an argument; a dashboard supports exploration and monitoring. | 9 |
| What happens on refresh? | Rerun original authorized requests, update evidence and affected narrative, preserve identity/presentation, revalidate and deliver. | 7, 10 |
| What patterns should we adopt? | Responsibility boundaries, evidence-first state, stable IDs, shared UX, layered validation, explicit host contracts. | 12 |
| What could be too much for a simpler agent? | Instruction sprawl, multiple build/storage paths, a custom compiler/runtime, and excessive evidence/UI machinery. | 13 |

## Validation limits

The automated results and tested viewports are in `qa/validation.json`. Checks establish local Chromium behavior and source/archive preservation. They do not establish Safari/iOS support, screen-reader conformance, an audience’s retention, live host behavior, or measured performance improvement. The learning-layer print stylesheet prints the current selected interactive states; the complete research review has its own print behavior.
