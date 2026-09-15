# Presenter script — Inside Codex Data

This is a read-aloud script for [Inside Codex Data](index.html). It follows the HTML scenes in order and is written for ordinary spoken language. The bold cue tells you what to do on screen; the indented text is what to say.

Allow about **30–35 minutes** for the main spoken script and on-screen actions, plus questions or live Codex demos. The guide’s **27-minute** schedule is for a selective talk, not for reading every word here. These are planning estimates; rehearse once with a timer. If the audience asks a question, use the short answer in the “If asked” line, then return to the next bold cue. The advisor-engagement request and the 18.4% / 17.1% values are teaching examples only. Say that out loud the first time they appear.

## Before you begin

**Open:** [index.html](index.html) and leave the page at the first scene. Reload before rehearsal to reset the simulations. Put this script in a separate window beside the browser; share only the presentation window. Read blockquotes aloud. Bold cues are actions for you, not spoken lines. Keep the browser window at the size you will use for screen sharing.

**Choose:** Use normal scrolling for a discussion. Use Presentation mode when you want the scene controls and arrow-key navigation. Keep “Under the Hood” closed until a question calls for more detail.

**Remember:** The four colors have a job. Blue is Agent, violet is Skills, amber is Evidence, and mint is Artifact. The colors support the words; they do not replace them.

**Opening line:**

> Today we’re looking at OpenAI’s official Data plugin for Codex, version 1.0.8. These presentation files are saved in our repository, but the subject is the installed plugin, not our custom Deep Agents application.
>
> I want to show you how Codex Data is put together. I’m going to explain the ideas first, then the implementation behind them, and finally which ideas are useful for our own agent systems.

---

## 1. Why this exists

**SCENE 01 / 14 · [Open this scene](index.html#beginning)**  
**Screen heading:** Inside Codex Data  
**One idea to land:** Why does the answer need to survive the chat?

**On screen:** Stay on the opening scene. Point first to the small three-step path, then to the longer path.

**Say:**

> Let me start with a simple question: what happens when a data agent needs to do more than answer once?
>
> A small data agent can take a question, run SQL or Python, and return an answer. That is useful. But real analytical work usually continues. Someone wants to know where the number came from. Someone changes the title or moves a chart. The result needs to be shared, printed, or published. Next quarter, someone wants the same work refreshed.
>
> So the real job is larger. The system has to understand the question, choose trustworthy evidence, analyze it, make the result readable, preserve how it was made, and keep it usable later.
>
> That is the problem Codex Data is designed to solve. It is built for analysis that needs to become a durable object, not just a reply in a chat window.

**Pause:** Let the longer path sit on screen for a moment.

**Say:**

> The key idea for today is this: the answer is only the beginning of the product.

**If asked whether this is a real analysis:**

> No. This page is a teaching presentation. The advisor example and its numbers are deliberately illustrative. I’ll use them to explain the architecture, not to make a business claim.

**Transition:** Scroll to the four-word model.

> Now that we know why the system needs more than a one-off answer, here is the simplest way to remember it.

---

## 2. Four words

**SCENE 02 / 14 · [Open this scene](index.html#mental-model)**  
**Screen heading:** Agent → Skills → Evidence → Artifact  
**One idea to land:** The host agent uses instructions and tools to make a saved result.

**On screen:** Click the Evidence card, then click the Artifact card. Expand the deeper report/dashboard path once.

**Say:**

> This is the mental model I want you to keep for the rest of the talk: Agent, Skills, Evidence, Artifact.
>
> The Agent understands the request and coordinates the work.
>
> Skills describe the kind of work that needs to happen. There is a skill for diagnosing a metric, a different one for designing a KPI, and another for checking whether a finished analysis is trustworthy.
>
> Evidence is the reviewed basis for the answer. It includes the rows, but also what source produced them, when the source was read, how the rows were transformed, what the metric means, and what the extraction does not cover.
>
> An artifact is simply a saved output that people can use later: a report, a dashboard, a notebook, or a delivered export. It gives that evidence a form that people can read, inspect, edit, and revisit.

**Point to the expanded path.**

> These are four roles, not four separate agents. The same host agent can follow several skills and call several tools.
>
> Under those four words is a longer path. The host receives the request. Data’s skills and shared policies guide the work. Authorized source tools and analysis produce a reviewed snapshot. Authored content is built against that snapshot. A verified build and shared runtime turn it into a report or dashboard, which can then be previewed, exported, or published.

> The host is important here. Codex Data does not need to contain every database client or every identity system. The host provides capabilities. Data defines how the analytical work and the resulting artifact should behave.

**If asked whether skills are separate agents:**

> Not necessarily. In this architecture, a skill is an instruction package with a responsibility and boundaries. The host agent reads and follows it. The source does not establish that every skill is a separate process.

**Optional LIVE DEMO 1 — “Inspect the routing skill” (on this scene):**

> If we want to inspect the instructions, the prompt in this panel asks Codex to read the Data index skill and explain how it chooses an output. We can skip this during the main talk.

**Transition:** Scroll to the request walkthrough.

> Let’s use one question to make that model concrete.

---

## 3. Follow one request

**SCENE 03 / 14 · [Open this scene](index.html#request)**  
**Screen heading:** Follow one request.  
**One idea to land:** Keep the question, scope, and evidence connected.

**On screen:** Read the example request. Click each of the nine numbered steps in order. Do not rush the stepper.

**Say before step 1:**

> Here is our teaching request: “Why did advisor engagement decline last quarter? Build me a dashboard explaining the drivers.” This is a hypothetical route. We are not querying advisor data today.

### Step 1 — Interpret the request

> First, the system identifies two things: the analytical job and the requested surface. This is a movement we want explained, and the requested output is a dashboard. The file format of the input does not decide that. A spreadsheet can still be the source for a dashboard.

### Step 2 — Gather relevant context

> Next, we ask whether the meaning is clear enough to analyze. What counts as an engaged advisor? What calendar defines last quarter? Which source owns the metric? We gather only context that could change the answer.

### Step 3 — Choose the analytical job

> Now the diagnostic responsibility becomes active. Metric diagnosis asks what changed, which comparison proves that it changed, and what evidence could explain the movement. If the user later asks what to do, a product or business analysis can use the validated diagnosis.

### Step 4 — Retrieve evidence

> The host now uses the authorized source tools. Data is guiding the source choice and the scope. It is not pretending that a connector badge, a table name, or a piece of page text is proof that the data was actually read.

### Step 5 — Test possible drivers

> We compare possible explanations. For example, did engagement fall inside each cohort, or did the mix of cohorts change? Are the populations comparable? Does the total reconcile with the parts? A plausible explanation is still a hypothesis until the evidence supports it.

### Step 6 — Preserve reviewed evidence

> Once we have a supported slice, we save it. The saved object has query IDs, rows, source requests, methods, definitions, time windows, and limits. This means the artifact does not depend on a hidden variable in the original conversation.

### Step 7 — Author the dashboard

> The dashboard is authored against those reviewed inputs. Each visible analytical component points back to the query or queries that support it. The agent composes the experience, while the shared runtime supplies common behavior such as source inspection and presentation editing.

### Step 8 — Validate at three levels

> We validate the data, the analytical claims, and the rendered artifact. Does each row represent the right thing, such as one advisor per quarter? Do the calculations support the explanation? Do the visible number, filter, source preview, and export agree? A successful build does not answer all three questions by itself.

### Step 9 — Deliver a durable object

> Finally, we deliver the requested surface. It might stay local, become an offline file, or be published to a Site. Later, refresh can reuse the saved source requests, preserve the artifact identity and user presentation, update the evidence, and recheck the story.

**Say after step 9:**

> Notice that the request did not jump straight from SQL to a chart. Meaning, scope, and evidence stayed attached as the work moved through the system.

**Optional LIVE DEMO 2 — “Trace this workflow”:**

> If we want to see this in Codex, I would ask: “Given this request, identify which Data skills would be invoked and why. Do not query data; inspect the installed skill instructions.”

**If asked whether this is the exact runtime call sequence:**

> No. It is a teaching route grounded in the installed instructions. Real work can skip a context pass when the request is already clear, or return to an earlier step when new evidence exposes a gap.

**Transition:** Scroll to the skill explorer.

> The next question is why this work is split into so many responsibilities.

---

## 4. Skill responsibilities

**SCENE 04 / 14 · [Open this scene](index.html#skills)**  
**Screen heading:** Skills are responsibilities. Tools are capabilities.  
**One idea to land:** Choose the job before the tool.

**On screen:** In the skill explorer, select Analyze, then `metric-diagnostics`. Select Understand, Validate, and Create briefly. Use the distinction selector for two or three examples.

**Say:**

> Codex Data does not divide work only by tool. It divides work by responsibility.

> We have organized the skills into five teaching groups: Understand, Analyze, Validate, Create, and Deliver. These help us read the instructions; they are not five agents that the plugin automatically launches.

> Understand frames the question and its meaning. Analyze chooses the right analytical job. Validate challenges the data and the conclusion. Create builds the report, dashboard, chart, or notebook. Deliver carries an existing artifact into its next use.

**Select `metric-diagnostics`.**

> This skill explains why an existing metric moved. It needs a metric definition, a comparison window, dimensions, and authoritative evidence. It owns the driver investigation. It does not redefine what success means, and it does not get to declare causation from a convenient segment comparison.

**Select `design-kpis` and `kpi-reporting` if convenient.**

> KPI design and KPI reporting sound similar, but they answer different questions. KPI design asks, “What should success mean, and how should we measure it?” KPI reporting asks, “What happened in this period, compared with what?” KPI diagnosis asks, “Why did the existing measure move?” Those boundaries are more useful than memorizing names.

**Use the distinction selector.**

> Data quality and analysis validation are another important pair. Data quality asks whether the underlying population and fields are fit to use. Analysis validation asks whether the calculations, claims, sources, visuals, and conclusions hold up. A clean table does not automatically make a conclusion correct.

> Reports and dashboards are also different jobs. A report guides an argument. A dashboard supports comparison, filtering, and monitoring. Both can use the same evidence foundation.

**If asked why not use one giant prompt:**

> A single prompt can be shorter, but it makes ownership blurry. The specialized skills give the agent clearer inputs, boundaries, handoffs, and stopping rules. The trade-off is that the instruction system itself needs maintenance.

**If you want the routing demo:** It is LIVE DEMO 1 on scene 2. There is no live-demo panel on this skill-explorer scene.

**Transition:** Scroll to the evidence scene.

> Once the responsibility is clear, the next thing we need is an object the responsibility can hand off.

---

## 5. Evidence becomes an object

**SCENE 05 / 14 · [Open this scene](index.html#evidence)**  
**Screen heading:** Preserve the basis of the answer.  
**One idea to land:** Save the number together with its meaning and origin.

**On screen:** Click Evidence, Component, and Artifact in the chain. Click `source`, then `coverage`, then `definitions`.

**Say:**

> A snapshot is a saved copy of results at a particular time. Provenance is the record of where those results came from and how they were produced.
>
> Raw data is not the same as reviewed evidence. “Reviewed” means checked for the analysis we are doing. It is not a guarantee or a separate certification.

> Raw data tells us what values are present. Reviewed evidence also tells us what the values mean, where they came from, when they were read, how they were transformed, and what might be missing.

> In the middle of this scene, the teaching fixture shows 184 engaged advisors out of 1,000 eligible advisors, or 18.4 percent. That number is invented for the lesson. The point is the shape of the object around it.

**Click `source`.**

> Source tells us where the number came from. For a real query, that can be SQL or a successful non-secret tool request with the provider and source identity.

**Click `executedAt` or `methods`.**

> Time and method tell us when the source was read and how the result became the displayed value. Those are different from the period the metric describes.

**Click `definitions`.**

> Definitions answer the question people often skip: what exactly is the numerator, what is the denominator, and who is included?

**Click `coverage`.**

> Coverage tells us whether the extraction was complete, paginated, truncated, or missing an important slice. A saved result is only as complete as the extraction behind it.

**Say:**

> The component points to the evidence with a stable query ID. The artifact can then show the metric while still offering a path back to the rows and the recorded basis.

**If asked whether provenance proves the answer is correct:**

> No. Provenance makes the basis inspectable and reproducible. It does not, by itself, prove that the source was authoritative or that the analysis made the right causal inference. Those still need validation.

**Transition:** Scroll to the identity scene.

> If the evidence and the component can be inspected, they also need to remain recognizable when the artifact changes.

---

## 6. The artifact contract

**SCENE 06 / 14 · [Open this scene](index.html#identity)**  
**Screen heading:** Keep the same IDs when values change.  
**One idea to land:** The same card can display new evidence without losing its identity.

**On screen:** Click “Simulate next snapshot.” Point at Artifact ID, Query ID, and Component ID before and after the change.

**Say:**

> Every important object gets a stable identity: the artifact, the query, and each visible component.

> In this invented example, the first snapshot has 184 engaged advisors out of 1,000 eligible advisors. The next one has 171 out of 1,000. So the value moves from 18.4 percent to 17.1 percent. This explains refresh; it does not tell us why engagement changed. The logical names stay the same. That is what lets a refresh update the evidence without turning the dashboard into a completely different object.

> Stable identities also give editing, source inspection, component links, publication, and saved presentation somewhere reliable to point.

> A contract here means rules that the saved result and the display agree to follow. This card has the ID engagement-rate. It gets its evidence from the saved result called engagement-quarterly. The definition tells us what the number means. Stable IDs are one part of that contract; keeping the right evidence and meaning attached is the larger job.
>
> If we changed the card ID on every refresh, saved edits tied to the old ID could lose their target. Keeping the ID lets the system recognize the same card with new values.

**If asked whether the ID is a hash or a permission token:**

> No. It is a logical reference. It helps the system keep continuity; it is not a secret and it does not grant component-level access.

**Optional LIVE DEMO 3 — “Inspect the artifact contract”:**

> In Codex, I would ask: “Find where query IDs, component IDs, provenance, and presentation state are represented in the installed Data plugin. Explain which identities a refresh preserves, using exact files and lines.”

**Transition:** Scroll to the state lab.

> Stable identity tells us which object we are looking at. Now let’s separate what the object knows from how we choose to show it.

---

## 7. Two kinds of state

**SCENE 07 / 14 · [Open this scene](index.html#state)**  
**Screen heading:** Edit the presentation. Preserve the evidence.  
**One idea to land:** A title edit changes the view; a refresh changes the evidence.

**On screen:** Click Reset first. Then Change title → Move card → Hide card → Show card. Point to the unchanged JSON. Keep the card visible for the simulated refresh.

**Say before clicking:**

> This is one of the most useful patterns in the whole system. Evidence state and presentation state are different things.

> Evidence state contains the reviewed rows, sources, definitions, methods, and query IDs. Presentation state contains the title, layout, hidden blocks, chart choices, filters, and theme.

**Click Change title, Move card, Hide card.**

> I can change the title, move the card, or hide it from this view. The evidence JSON on the left has not changed. Editing the presentation has not silently rewritten the number or its source.

**Click Show card, then “Now simulate a data refresh.”**

> This page is simulating the warning; it is not showing an automatic stale-sentence detector in Data. Now the evidence changes from 18.4 percent to 17.1 percent. The sentence on the right still says 18.4 percent. This is the important caveat: separating the state domains protects the evidence, but it does not automatically keep every sentence true after a refresh.

> That is why refresh has to revisit the narrative, the comparisons, the date labels, and the conclusions—not just replace the rows.

**Point to the note about hidden blocks.**

> Also, hiding a block is a view choice, not access control. A published snapshot can still contain the complete reviewed rows.

**If asked whether every presentation edit is safe:**

> It is safer because the edit path is separate from the evidence path. It is not a substitute for authorization or analytical review. A changed title can still be misleading, and a sensitive filter can still matter to sharing.

**Transition:** Scroll to the runtime scene.

> We now have durable evidence and durable state. The next design question is how generated content can use a common experience without rebuilding that experience every time.

---

## 8. Why a runtime and compiler?

**SCENE 08 / 14 · [Open this scene](index.html#runtime)**  
**Screen heading:** Generate the analysis. Reuse the experience.  
**One idea to land:** The agent writes content; shared browser code supplies common behavior.

**On screen:** Trace the four-stage flow from authored content to shared runtime. Point to the small code example, then to the common features.

**Say:**

> Imagine asking an agent to generate a new React application from scratch for every report and dashboard. You would also be asking it to reinvent source inspection, chart behavior, filters, editing, links, and export every time.

> Two terms help here. The build prepares the authored content for the app. The runtime is the shared code running in the browser when someone opens it. Checking the build does not prove the analysis is correct.
>
> Codex Data takes a different approach. The agent authors content inside a restricted contract. A verified compiler and build turn that content into the supported artifact format. A shared runtime supplies the common experience.

> This gives the agent room to compose the story, while the product maintains the behavior that should be consistent.

**Point to the code example.**

> This small component says, in effect, “Here is a stable component, and here is the reviewed query it uses.” The real implementation is richer, but this is the important relationship.

**Point to the runtime features.**

> The shared runtime can provide source inspection, charts, common transformations, presentation editing, view state, component links, and export behavior. Those capabilities do not need to be re-authored in every analytical response.

> The trade-off is real. More control means more framework and build complexity. The runtime has to maintain supported modules, local assets, source and prebuilt paths, integrity checks, and compatibility tests.

**If asked whether the compiler is a security sandbox:**

> No. It constrains the ordinary authoring surface and checks installed runtime integrity. The source does not establish arbitrary-code isolation or an independent publisher signature.

**If asked whether every new system needs this:**

> No. A small agent might need a typed evidence object and a modest component library. A compiler and shared runtime become worthwhile when many generated artifacts need the same behavior and portability.

**Transition:** Scroll to the report/dashboard scene.

> The shared foundation does not mean every artifact should look or behave like the same kind of document.

---

## 9. Report or dashboard?

**SCENE 09 / 14 · [Open this scene](index.html#surfaces)**  
**Screen heading:** One evidence foundation. Two ways to think.  
**One idea to land:** A report guides; a dashboard lets readers explore.

**On screen:** Point first to the report mockup, then to the dashboard mockup. Click the live-demo panel only if you want to use it.

**Say:**

> Report and dashboard are not just two file formats. They are two reader jobs.

> A report answers, “Tell me what happened and what matters.” It leads with an argument, uses selective visuals, and puts conclusions beside the evidence that supports them.

> A dashboard answers, “Let me compare, filter, and monitor.” It gives the reader controls, repeated exploration, and a saved view that can be revisited.

> Both can use the same reviewed query, the same definitions, the same source inspection, and the same shared runtime. The difference is the experience we choose for the reader.

> The input format does not decide the output. A CSV can support a report. A warehouse query can support a dashboard. We choose the surface from the question and the reader’s job.

**Optional LIVE DEMO 4 — “Compare the surfaces”:**

> A useful Codex prompt is: “Inspect Data’s build-report and build-dashboard skills. Explain the reader jobs and design differences, and identify what both reuse from the Data App Contract.”

**Transition:** Scroll to the lifecycle scene.

> Once we choose the surface, the artifact still has a life after it is authored.

---

## 10. Delivery and refresh

**SCENE 10 / 14 · [Open this scene](index.html#lifecycle)**  
**Screen heading:** The end of one request is the start of a lifecycle.  
**One idea to land:** Refreshing the data also means reviewing the story.

**On screen:** Click the lifecycle steps from Question through Refresh. Then select Local preview, Offline export, and Sites publication.

**Say:**

> This is the artifact lifecycle: question, evidence, artifact, validation, preview, delivery, refresh, and revalidation.

> The main lesson is that analytical artifacts are not disposable responses. They are objects that can move through several states while keeping their identity and evidence relationships.

**Click Local preview.**

> In the ordinary local preview, a local web server serves the built HTML and its separate saved data file. This teaching presentation embeds its data, so we can open it directly. Those are different packaging choices.

**Click Offline export.**

> An offline export carries the reviewed snapshot with the file, so the experience can render without a live source or a host. Offline rendering does not mean that the file can fetch fresh warehouse data or create a new scheduled job.

**Click Sites publication.**

> Publication carries the compiled experience and its reviewed data into a hosted service. The service also stores presentation and revision information, and the workflow reads the result back to check what is live.

> Refresh does not start merely because someone opens a dashboard. The agent needs source access and a request to refresh, or a separately configured host automation. The documented workflow reads the current snapshot and presentation, reruns the saved source requests through their original authorized sources, updates the evidence, preserves the layout and user edits, rebuilds, and rechecks the result.

> The loop matters: refresh is not just “run the query again.” It is “renew the evidence, revisit the story, and deliver the same logical artifact.”

**If asked whether publication is one atomic operation:**

> The documented flow has separate deployment, upload, and readback steps. That makes staging and activation an important operational concern. The lesson is to keep the previously verified version available until the new version is ready.

**Transition:** Scroll to the host boundary.

> The lifecycle makes one dependency especially visible: some parts belong to Data, and some parts belong to the environment around it.

---

## 11. Host versus plugin

**SCENE 11 / 14 · [Open this scene](index.html#boundary)**  
**Screen heading:** The plugin defines the job. The host makes it executable.  
**One idea to land:** Viewing saved data and fetching fresh data need different capabilities.

**On screen:** Point to both ownership columns. Turn off source access, then Sites publication, and read the resulting messages.

**Say:**

> Codex Data owns the workflow and the artifact experience. It provides the routing instructions, analytical skills, evidence representation, shared runtime, authoring rules, validation guidance, and delivery workflows.

> The host owns execution and authority. It provides the source tools, authentication, identity, permissions, browser and computer capabilities, scheduling, and deployment infrastructure.

**Turn off source access.**

> With source access off, an existing snapshot can still render. But the system cannot perform a fresh investigation or refresh the data. Rendering and source execution are different capabilities.

**Turn off Sites.**

> With Sites off, local preview and offline export can still be useful. Hosted publication is unavailable. Again, the artifact can remain useful even when one host capability is missing.

> This boundary is what gives the plugin flexibility across environments. It also means the plugin cannot promise a capability that the host does not expose.

**If asked whether the plugin itself authenticates every source:**

> No. It defines source and authorization expectations, but the actual connector permissions and identity enforcement come from the host and the connected service.

**Transition:** Scroll to engineering patterns.

> Now let’s turn the architecture into ideas we could use ourselves.

---

## 12. Engineering patterns worth borrowing

**SCENE 12 / 14 · [Open this scene](index.html#borrow)**  
**Screen heading:** Which ideas are useful in your own system?  
**One idea to land:** Start with a clear evidence object and responsibility boundaries.

**On screen:** Select three patterns that fit your audience. A good default is Semantic skills, Artifact contract, and Evidence-first authoring.

**Say:**

> I would not copy every file or every service here. I would start by borrowing the boundaries.

**Select Semantic skills.**

> First: split an agent by semantic responsibility. Ask one part of the system to define a metric, another to diagnose a movement, another to validate a conclusion, and another to package the result. The benefit is clearer ownership and clearer handoffs.

**Select Artifact contract.**

> Second: define a durable contract between analysis and presentation. Do not make the UI reconstruct meaning from chat text or an untracked Python variable. Give downstream work a structured object it can inspect and validate.

**Select Evidence-first authoring.**

> Third: build the experience from reviewed evidence. Keep the rows, source request, method, definition, and limits close enough that a reader can follow the number back to its basis.

**Select Stable identities or Separate state domains.**

> Two more ideas are especially portable. Stable identities let refresh and editing refer to the same logical object. Separate evidence state from presentation state so a title change or layout edit does not rewrite the analytical facts.

**Select Progressive validation.**

> Finally, validate in layers. Check whether the data is fit. Check whether the analysis supports the claim. Check whether the rendered artifact shows the same values and scope. Each layer catches a different kind of mistake.

**Say:**

> These patterns are useful because they make the system easier to reason about. They are not valuable because they make the architecture look sophisticated.

**Audience prompt:**

> As you look at these, choose one pattern that would help a system you own. What is the smallest version of it that would be useful?

**Transition:** Scroll to trade-offs.

> The same boundaries can become expensive if we copy the machinery without copying the need.

---

## 13. What not to copy blindly

**SCENE 13 / 14 · [Open this scene](index.html#tradeoffs)**  
**Screen heading:** Learn the principle. Question the machinery.  
**One idea to land:** Add mechanisms when a concrete need justifies them.

**On screen:** Use the trade-off selector. Select Instruction sprawl, Build-path multiplication, and Runtime ownership.

**Say:**

> The lesson is the principle, not the exact implementation.

> A long instruction graph can be powerful, but it can also develop overlap and drift. If two skills disagree about how broadly to search for context, the agent has to reconcile the instructions. The right response for a smaller system may be a short decision table and a few scenario tests.

> Multiple build and storage paths can support real needs, such as portability or large hosted snapshots. They also increase the number of environments and recovery paths we have to test. Add a path because a measured product need demands it, not because a mature system happens to have one.

> A shared runtime can save repeated UX work, but it becomes a product in its own right. If we only have a few generated artifacts, a smaller component library may deliver the same value with less maintenance.

> Rich evidence metadata is valuable, but loose metadata is hard to validate. Start with a small schema that can say “unknown” honestly, then add fields when consumers need them.

> The question to ask is: what guarantee do we need, and what is the smallest mechanism that provides it?

**If asked for the shortest practical starting point:**

> Start with four things: a clear responsibility boundary, a typed evidence object, stable IDs, and one validation path. Add a shared UI runtime or multiple delivery modes only when repeated work or product requirements justify them.

**Transition:** Scroll to the final model.

> Let’s return to the four words and see what they mean now.

---

## 14. The final model

**SCENE 14 / 14 · [Open this scene](index.html#remember)**  
**Screen heading:** Agent → Skills → Evidence → Artifact  
**One idea to land:** Make the work understandable after the original conversation ends.

**On screen:** Let the four cards sit on screen. Ask the audience to answer before opening the self-check.

**Say:**

> We started with four words: Agent, Skills, Evidence, Artifact.

> The Agent coordinates the work and uses the capabilities the host provides.

> Skills encode analytical responsibilities. They tell the agent what kind of problem it is solving and where that responsibility stops.

> Evidence is preserved rather than merely consumed. It carries the rows, meaning, source, method, coverage, and limits that make an answer inspectable.

> The Artifact gives the work a durable identity and a useful form. Its components can point back to evidence. Its presentation can change without silently rewriting the evidence. Its lifecycle can continue through preview, export, publication, refresh, and revalidation.

> The deepest idea is not the compiler, the storage service, or any individual skill name. It is the separation of responsibilities and state that lets an analytical answer remain understandable over time.

**Ask the audience:**

> Before I open the answers, say one sentence about why presentation state should be separate from evidence state.

Pause briefly, then open the self-check.

**Say:**

> The short answer is: a title, layout, or hidden block is a presentation choice. The reviewed rows and their source basis are analytical evidence. Keeping them separate protects the evidence, while refresh still has to recheck the written story.

**Read the final five takeaways:**

> One: skills encode analytical responsibilities.
>
> Two: evidence is preserved, not merely consumed.
>
> Three: artifacts have stable contracts and identities.
>
> Four: presentation is separated from analytical evidence.
>
> Five: the host executes capabilities; Data organizes the analytical workflow and artifact experience.

**Closing line:**

> If you remember only one picture, remember this: Agent, then Skills, then Evidence, then Artifact. That is the path from a question to analytical work that people can inspect, change, and use again.

---

## Optional appendix handoff · 30 seconds

**On screen:** Click “Explore the research appendix.”

**Say:**

> The presentation is the learning layer. The appendix contains the complete technical review: source paths and line ranges, runtime and Worker details, test results, security boundaries, failure modes, and unresolved questions.

> If you want to inspect a claim, open its source drawer or open the full review. The teaching layer keeps the main story readable; the appendix keeps the research available.

**If the session is running long:**

> I’ll stop the walkthrough here and leave the appendix available for follow-up. The three places I would start are the routing skill, the evidence contract, and the presentation-state implementation.

## Short answers for likely questions

**“Is Data a data agent, a UI framework, or a skill library?”**

> It is a plugin that adds analytical instructions and report/dashboard software to the host. The host supplies the agent and execution tools. The plugin supplies skills, shared app behavior, and rules for saving the evidence and result.

**“Does a dashboard query the warehouse from the browser?”**

> The reviewed design stores and loads a snapshot for the artifact. Source execution belongs to authorized host workflows. A dashboard can render saved evidence without being a live warehouse client.

**“Does hiding a chart hide its data?”**

> No. Hiding changes the presentation. Published snapshots can still contain complete reviewed rows, so hiding is not redaction or access control.

**“Does provenance guarantee correctness?”**

> No. Provenance makes the basis inspectable. Data quality, analytical validation, and host authorization remain separate checks.

**“Why preserve stable IDs after refresh?”**

> So the same logical artifact, query, and component can keep its links, edits, definitions, and evidence relationships while its values and timestamps update.

**“Why not just export a PDF?”**

> A PDF is a delivery surface. The artifact contract still matters before export, because the PDF should preserve the selected view and reviewed content. A PDF also cannot refresh itself or replace source authorization.

**“What is the one idea you would adopt first?”**

> Define a small, typed evidence object between analysis and presentation, then make every visible metric point to it with a stable ID.

