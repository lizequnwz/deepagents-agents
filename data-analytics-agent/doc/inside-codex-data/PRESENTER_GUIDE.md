# Presenter guide — Inside Codex Data

## Run of show

Open index.html directly in a browser. Use normal scrolling for preparation and exploration. For screen sharing, choose Presentation mode. Left/Right, Up/Down, PageUp/PageDown, or Space advance major scenes when focus is outside an interactive control; Escape exits. Use visible Previous/Next controls at any time. Focus on a button, select, or source drawer keeps that control’s normal keyboard behavior. The page remains scrollable in presentation mode; no content is clipped into a fixed slide canvas.

The scene budgets total **27 minutes** for a selective talk using these notes. Allow **30–35 minutes** for the fuller word-by-word script and its interactions, before audience questions or live Codex demos. These are planning estimates, not a timed rehearsal. Demonstrations are optional: replace discussion time or add 4–8 minutes. All numbers and advisor examples are visibly labelled teaching fixtures. Never present them as plugin test output or business findings.

The subject is OpenAI’s installed Data plugin 1.0.8. This repository only holds the presentation files; the subject is not the custom Deep Agents application.

Use [PRESENTER_SCRIPT.md](PRESENTER_SCRIPT.md) for exact spoken words. The guide is the shorter run of show. Reload the HTML before rehearsing to reset its simulations.

Start at scene 1. Keep Under the Hood closed during the main narrative; open only the detail that answers the audience’s question. The four colors stay consistent: blue Agent, violet Skills, amber Evidence, mint Artifact. The original review remains available after the final scene.

## 1. Why this exists — 1.5 minutes

**Open scene:** [Why this exists](index.html#beginning)

**Screen heading:** Inside Codex Data

**Purpose:** Create a need for durability before naming components.

**Key takeaway:** The product starts where a one-off answer ends.

**Talking points / interaction:** Ask what must survive the chat. Use source inspection, user edits, and next-quarter refresh as examples.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 2. Four words — 2 minutes

**Open scene:** [Four words](index.html#mental-model)

**Screen heading:** Agent → Skills → Evidence → Artifact

**Purpose:** Provide four conceptual anchors for everything that follows.

**Key takeaway:** The host runs the tools. Data defines how the analysis and saved result fit together.

**Talking points / interaction:** Click Evidence. Expand the deeper path once; point out where the host and the authored artifact separate.

**Optional live demo:** Expand the marked Live Demo panel and copy its prompt into Codex. Return to the same scene afterward.

## 3. Follow a request — 3 minutes

**Open scene:** [Follow a request](index.html#request)

**Screen heading:** Follow one request.

**Purpose:** Turn the architecture into an understandable sequence of work.

**Key takeaway:** Meaning and scope survive every handoff.

**Talking points / interaction:** Advance all nine steps. Pause at retrieval to distinguish source tools from skills, and at preservation to introduce stable evidence.

**Optional live demo:** Expand the marked Live Demo panel and copy its prompt into Codex. Return to the same scene afterward.

## 4. Skill responsibilities — 3 minutes

**Open scene:** [Skill responsibilities](index.html#skills)

**Screen heading:** Skills are responsibilities. Tools are capabilities.

**Purpose:** Teach responsibility boundaries without asking the audience to memorize names.

**Key takeaway:** First decide the question to answer; then choose the tool that can help.

**Talking points / interaction:** Start with Analyze → metric-diagnostics. Contrast design-kpis and kpi-reporting; then compare data quality with validation.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 5. Evidence becomes an object — 2 minutes

**Open scene:** [Evidence becomes an object](index.html#evidence)

**Screen heading:** Preserve the basis of the answer.

**Purpose:** Make reviewed evidence concrete and traceable.

**Key takeaway:** Save the results, their meaning, and how they were produced together.

**Talking points / interaction:** Click source and coverage. Follow the component into the artifact. Explain why missing methodology should remain explicitly unknown.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 6. The artifact contract — 1.5 minutes

**Open scene:** [The artifact contract](index.html#identity)

**Screen heading:** Keep the same IDs when values change.

**Purpose:** Explain identity before introducing persistence infrastructure.

**Key takeaway:** Stable references let the artifact evolve without losing user work.

**Talking points / interaction:** Toggle the snapshot and call out what changed versus what stayed stable. Connect this to saved layout and component links.

**Optional live demo:** Expand the marked Live Demo panel and copy its prompt into Codex. Return to the same scene afterward.

## 7. Two kinds of state — 2 minutes

**Open scene:** [Two kinds of state](index.html#state)

**Screen heading:** Edit the presentation. Preserve the evidence.

**Purpose:** Demonstrate separation and its remaining semantic obligation.

**Key takeaway:** Separating state protects evidence, but does not keep every sentence true automatically.

**Talking points / interaction:** Click Reset, Change title, Move card, Hide card, then Show card. Point to unchanged JSON. Refresh with the card visible and read the stale sentence aloud.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 8. Why a runtime? — 2 minutes

**Open scene:** [Why a runtime?](index.html#runtime)

**Screen heading:** Generate the analysis. Reuse the experience.

**Purpose:** Make build complexity a response to a product need.

**Key takeaway:** Let the agent write the content; reuse common browser behavior.

**Talking points / interaction:** Trace a single authored block into shared behavior. Ask whether a smaller system would need a compiler or just a component library.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 9. Report or dashboard? — 1.5 minutes

**Open scene:** [Report or dashboard?](index.html#surfaces)

**Screen heading:** One evidence foundation. Two ways to think.

**Purpose:** Teach output selection as product design.

**Key takeaway:** A report guides; a dashboard supports exploration.

**Talking points / interaction:** Use the same fixture number in both compositions. Emphasize that a report can still be interactive and a dashboard can contain narrative.

**Optional live demo:** Expand the marked Live Demo panel and copy its prompt into Codex. Return to the same scene afterward.

## 10. Delivery & refresh — 2 minutes

**Open scene:** [Delivery & refresh](index.html#lifecycle)

**Screen heading:** The end of one request is the start of a lifecycle.

**Purpose:** Connect durability to concrete delivery choices.

**Key takeaway:** Refresh preserves identity while renewing evidence and conclusions.

**Talking points / interaction:** Select Refresh, then Sites. Explain the storage names only in the deep dive after the lifecycle is understood.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 11. Host vs plugin — 1.5 minutes

**Open scene:** [Host vs plugin](index.html#boundary)

**Screen heading:** The plugin defines the job. The host makes it executable.

**Purpose:** Locate execution and authority accurately.

**Key takeaway:** Saved data can still be viewed when source access or hosting is unavailable.

**Talking points / interaction:** Turn off source access: an existing snapshot can still render but cannot become fresh. Turn off Sites: local/offline delivery still has value.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 12. Patterns worth borrowing — 2 minutes

**Open scene:** [Patterns worth borrowing](index.html#borrow)

**Screen heading:** Which ideas are useful in your own system?

**Purpose:** Turn understanding into reusable design choices.

**Key takeaway:** The most portable ideas are responsibility, state, and evidence boundaries.

**Talking points / interaction:** Choose three patterns most relevant to the team. For each, name a concrete use and the smallest implementation that would deliver value.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 13. What not to copy — 1.5 minutes

**Open scene:** [What not to copy](index.html#tradeoffs)

**Screen heading:** Learn the principle. Question the machinery.

**Purpose:** Help the audience choose mechanisms for a concrete need.

**Key takeaway:** Use the smallest mechanism that preserves the required guarantees.

**Talking points / interaction:** Compare the simple starting point with the durable-product investment. Ask what evidence would justify crossing that boundary.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## 14. The final model — 1.5 minutes

**Open scene:** [The final model](index.html#remember)

**Screen heading:** Agent → Skills → Evidence → Artifact

**Purpose:** Consolidate the architecture and prompt recall.

**Key takeaway:** Agent → Skills → Evidence → Artifact.

**Talking points / interaction:** Ask the audience to expand Evidence or Artifact in their own words before clicking. End with one pattern they would borrow.

**Optional live demo:** No live demo needed; the teaching interaction stands alone.

## Technical guardrails for the presenter

- Skills are instructions and responsibilities, not necessarily separate agents or execution processes.
- The end-to-end walkthrough is an illustrative route. Actual analysis can iterate or omit unnecessary steps.
- Reports and dashboards use the shared React app. Notebooks and document conversions branch to their respective tools.
- Saved provenance supports inspection; it does not authenticate the agent’s claim that a query ran or prove correct causal inference.
- Presentation filters can change the visible population without mutating stored rows. Hiding a component is not access control.
- Stable IDs are logical references, not content hashes or secrets.
- The state exercise’s stale-narrative warning is a teaching mechanism, not an assertion that Data automatically detects stale prose.
- Offline rendering does not imply offline source execution, scheduled refresh, or host-assisted conversion.
- Source/build integrity checks are not arbitrary-code sandboxing or independent publisher signatures.

## Audience self-check / coverage

| Question after the session | Scene |
|---|---|
| What problem is Data solving? | 1 |
| Is it an agent, skill library, framework, or artifact system? | 2, 8, 11 |
| What does the host supply? | 3, 11 |
| What is a skill and why specialize? | 4 |
| How does a request become a dashboard? | 3 |
| What is reviewed evidence and why preserve provenance? | 5 |
| What is the artifact contract and why stable IDs? | 6 |
| Why separate evidence and presentation? | 7 |
| Why a runtime/compiler? | 8 |
| How do report and dashboard jobs differ? | 9 |
| What happens during refresh? | 7, 10 |
| What should we borrow, and what may be too much? | 12, 13 |

For a 20-minute version: demonstrate four request steps (1, 4, 6, 9), inspect two skills, and discuss three borrowing patterns. For the full script, reserve 30–35 minutes plus questions. The script also contains optional Q&A material that should not all be read aloud. This timing is a presenter plan, not a measured learning outcome.
