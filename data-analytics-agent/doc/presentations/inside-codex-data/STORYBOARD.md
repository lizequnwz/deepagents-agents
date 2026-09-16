# Inside Codex Data — teaching plan

Prepared before implementation, after rereading the existing review, inspecting its HTML, and revisiting the routing, skill, evidence, component, and build contracts.

## The narrative

Start with the extra responsibilities that appear after an agent gives its first answer. Introduce four memorable objects. Follow one illustrative request. Explain each architectural mechanism only after the request creates a need for it. End by selecting reusable principles and returning to the four objects.

The main audience is AI engineers. The original plan below is retained as design context; the current selective scene budgets total 27 minutes, while the fuller script needs an estimated 30–35 minutes before questions or live demos. The example is a hypothetical advisor-engagement investigation, not an executed analysis or a claim about any real organization. The interactions are teaching models, not an embedded Data runtime or connector session.

## Highest-value ideas

1. An analytical product must survive beyond the chat answer.
2. Agent → Skills → Evidence → Artifact separates four responsibilities.
3. Output intent and source authority are separate routing decisions.
4. Skills encode cognitive responsibilities; they are instructions, not separate processes by definition.
5. Context, measurement design, diagnosis, and validation solve different problems.
6. Reviewed evidence includes meaning, scope, and reproducibility, not only rows.
7. Component bindings make provenance inspectable.
8. Stable artifact/query/component IDs preserve continuity.
9. Evidence and presentation are different state domains.
10. Refresh must revisit narrative as well as numbers.
11. Constrained authoring plus a shared runtime reduces repeated UX work.
12. Reports and dashboards serve different reader jobs over common foundations.
13. Delivery is a lifecycle; export, publication, and refresh have different dependencies.
14. The host executes capabilities; the plugin supplies workflow and artifact contracts.
15. Adopt the principle at the scale of the problem; a small agent may not need a compiler or multiple storage modes.

## Scene architecture and interaction sketches

| Scene | Teaching move | Visual / interaction | Minutes |
|---|---|---|---:|
| 1. The answer is only the beginning | Create the need for durable analysis | Dark hero; question → code → answer beside a growing responsibility chain | 1.5 |
| 2. Four words, one system | Give a reusable mental model | Four colored nodes; click to expand one level or the complete report/dashboard path | 2 |
| 3. Follow one request | Ground the abstractions | Nine-step manual walkthrough; active component map; inputs and output change together | 3 |
| 4. Responsibilities, not tools | Teach semantic decomposition | Five skill clusters; complete 20-skill explorer; semantic distinction selector | 3 |
| 5. Rows become evidence | Explain provenance through a concrete component | Evidence → component → artifact chain; inspect the conceptual source record | 2 |
| 6. Give every object an identity | Explain the artifact contract | Identity graph; refresh toggle changes values/time but keeps IDs | 1.5 |
| 7. Two kinds of state | Make separation tangible | Rename/move/hide a synthetic metric; evidence stays fixed; refresh reveals stale narrative | 2 |
| 8. Why a compiler? | Motivate constrained generation | Authored code → contract → verified build → shared runtime; optional actual source | 2 |
| 9. Two reader jobs | Separate story from exploration | Report and dashboard teaching mockups using the same illustrative evidence | 1.5 |
| 10. Keep the artifact alive | Explain delivery and refresh | Clickable lifecycle loop; local/offline/Sites modes; deeper Worker/D1/R2 detail | 2 |
| 11. Draw the ownership boundary | Make external execution explicit | Plugin/host diagram with capability switches and honest availability outcomes | 1.5 |
| 12. Engineering patterns worth borrowing | Transfer learning | Select a pattern: implementation → rationale → application | 2 |
| 13. Learn the principle, not the machinery | Calibrate adoption | Trade-off selector; small-agent vs durable-product guidance | 1.5 |
| 14. Four words, now with depth | Retrieval and closure | Same four nodes expand; five takeaway statements; self-check questions | 1.5 |

Total planned core session: 27 minutes (not a timed rehearsal). Optional live demonstrations replace discussion time or extend the session.

## Visual and behavioral design

- Alternating ink, warm paper, and muted violet scenes; blue Agent, violet Skills, amber Evidence, mint Artifact, neutral Host. Color always accompanies text.
- Large headlines, a dominant visual per scene, short explanatory copy. No automatic carousels or scroll hijacking.
- Normal scrolling works at every width. The request walkthrough uses a sticky diagram on wide screens and a normal stacked layout on phones.
- Presentation mode moves through scene anchors with arrow keys/Space, with explicit previous/next/exit controls. It leaves interactive controls and dialogs their native keyboard behavior. It is not a fixed-height slide canvas.
- Each scene has optional Under the Hood content and a source drawer. The drawer shows claim type, exact paths/line intervals, and source excerpts; it is keyboard dismissible.
- Four optional copyable live-demo prompts; no automatic tool execution or external messages.
- The original review is embedded byte-for-byte as a lazily opened research appendix and available for offline download. Its audit framing stays in the appendix.
- All source files, scripts, styles, diagrams, and appendix data compile into one offline HTML file with no network dependencies. No framework or animation library.

## Accuracy constraints

The report/dashboard path uses the shared React runtime; notebooks and document conversions branch into their own artifact tools. The four-box model is conceptual, not a claim that skills are separate worker processes. Evidence metadata is a contract to populate and inspect, not automatic proof of correct analysis. Presentation filters can change the visible population while preserving stored rows. Hidden blocks are not access control. Hosted authorization and scheduling depend on host capabilities. Interpretations and adoption advice are identified in deep dives without audit labels dominating the lesson.
