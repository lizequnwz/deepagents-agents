# Clarity review — Inside Codex Data

Reviewed 15 September 2026. Scope: the educational presentation and its companion files, with particular attention to `index.html`, `PRESENTER_GUIDE.md`, and `PRESENTER_SCRIPT.md`.

## Assessment

**Inference:** The 14-scene sequence is a sound teaching structure. It introduces a need, gives the audience four roles to remember, follows one request, and then explains the mechanisms behind it. The best improvements are clearer definitions and tighter coordination between the screen and the speaker. A visual redesign would not address the main problems found here.

**Observed:** The opening, script, and guide previously left several important distinctions implicit. The script also contained concrete mismatches with the screen. These have been corrected in the source and regenerated deliverables.

## Findings and refinements

| Priority | Observed issue | Change made | Why it helps — inference |
|---|---|---|---|
| P1 | The hero described an analytics agent without naming the developer, installed version, or the plugin/host distinction. The script’s Q&A said Data combined an agent, UI framework, and skill library. | The opening now identifies OpenAI’s Data plugin 1.0.8. The spoken opening distinguishes the reviewed plugin from the custom application in the repository. Q&A locates the agent in the host. | Readers can identify the subject before interpreting its architecture. |
| P1 | “Contract,” “snapshot,” “provenance,” and “runtime” needed explanation before technical relationships could be understood. | Added definitions at the relevant scenes and spoken explanations. The contract now includes a concrete component-to-query relationship. | The audience can connect a technical term to an object or action. |
| P1 | The four-box model and five skill groups could imply separate executing agents. The teaching taxonomy was not identified in the main view. | Added visible explanations that these are roles and teaching groups. The same host agent follows skills and calls tools throughout. | Avoids mistaking an explanatory diagram for an implementation topology. |
| P1 | The script called the request walkthrough Live Demo 1, although the HTML labels it 2. It placed the routing demo on the skill scene, which has no demo panel. | Matched the script to routing on scene 2, workflow on scene 3, identity on scene 6, and surface comparison on scene 9. | The presenter can follow the script without searching for missing controls. |
| P1 | Scene 7 instructed the presenter to hide the metric card immediately before demonstrating its refreshed value. The automated test already restored the card, so its successful result did not establish that the script was correct. | Both documents now say Reset → Change title → Move card → Hide card → Show card → Refresh. | The audience sees the new value and stale sentence together. |
| P1 | The stale-prose caveat lived in a technical disclosure while the warning itself could look like a plugin capability. Refresh descriptions could also sound automatic. | The visible warning and spoken script identify the simulation. The lifecycle states that refresh needs an agent workflow and source access; scheduling is separate. | Keeps teaching behavior separate from verified plugin behavior. |
| P2 | Scene 6 promised a timestamp change but displayed periods. Its percentages were less explicit than the state exercise’s counts. | It now says period and displays 184 / 1,000 and 171 / 1,000. The script explains that these invented snapshots do not establish a cause. | Readers can follow the calculation and separate a refresh example from a driver analysis. |
| P2 | The full script was presented as the same 27-minute duration as the selective guide, while the original storyboard also mentioned 25. | The build calculates the selective guide total. The script estimates 30–35 minutes for the fuller spoken route and interactions, excluding questions/live demos. | Avoids treating a short run of show as a measured read-aloud duration. |
| P2 | Script section names did not always match the large heading visible in the HTML. | Added scene numbers, exact screen headings, links, and a one-sentence teaching objective to every script section. The generated guide also has headings and links. | A presenter who loses their place has several clear ways to recover. |
| P2 | Local preview used “bound snapshot sidecar” without explaining why this teaching HTML can open directly. | It now describes a built app plus a separate saved data file served locally, and distinguishes this self-contained lesson. | Avoids confusing the educational file with a generated Data app. |
| P2 | Companion-file and printing limits were documented mostly in the README. The script link navigated away from the lesson. | Guide/script links open separate tabs; the appendix states that they require companion files and that printing includes selected interactive views. | Delivery behavior is visible where the reader chooses it. |
| P3 | Several guide takeaways used abstract language: “externalize execution,” “cognitive job,” and “state domains.” | Replaced key takeaways with concrete actions; kept necessary technical vocabulary with explanations. | The audience has a short sentence it can remember and repeat. |

Priority here concerns the presentation, not the plugin’s own engineering backlog.

## What was reviewed

**Observed:** Read the scene data, all skill summaries, browser interaction code, styles, build script, presenter guide, presenter script, README, storyboard, design review, and QA scripts/receipts. Inspected the generated presentation’s structure and rendered scenes. The source and embedded payload explain the generated HTML; the original research appendix remains preserved in full.

**Observed:** Rechecked the installed manifest for plugin identity. This is not a new full audit of the plugin or a fresh execution of its source connectors, publication services, or analytics tests. Existing plugin-integrity evidence describes the earlier review run, not a new full directory comparison.

**Observed:** Applied ui-ux-pro-max’s web review guidance for hierarchy, disclosure, readable controls, mobile containment, and keyboard behavior. Two local searches for comprehension guidance returned unrelated matches; those results were not used as evidence. The teaching recommendations above are editorial judgment, not findings from the skill’s search dataset or an audience study.

## Remaining opportunities

1. **Recommendation — P1: rehearse with one engineer unfamiliar with Data.** Ask them to explain skill versus tool, snapshot versus live query, and title edit versus refresh without reopening the slides. Record misunderstandings and revise the affected scene. Acceptance: each distinction is explained accurately in the participant’s own words. No retention claim is made before that test.
2. **Recommendation — P2: time the actual speaking route.** The script contains optional prompts and Q&A that should not all be read. Use a timer and the intended interactions; cut examples if a firm 30-minute slot is required. Acceptance: finish the planned narrative with time left for the intended questions.
3. **Recommendation — P2: test the actual presentation environment.** Browser checks use local Chromium. Safari/iOS, screen-reader use, projector contrast, and text enlargement need separate observation before claiming those environments are supported. Acceptance: navigate, inspect sources, read diagrams, and complete the state exercise in the target environment.
4. **Recommendation — P3: choose three borrowing patterns for a specific audience.** The complete explorer is useful as reference, but reading all nine adds repetition. Acceptance: the presenter can connect each selected pattern to one concrete problem the audience recognizes.

## Validation

**Observed:** The browser suite passed 121/121 checks across nine viewport sizes, including interaction states, keyboard and source-drawer behavior, offline operation, original-review preservation, and print generation. An additional consistency check verified all 14 script/guide headings and scene links, the 27-minute guide total, and all four live-demo locations. The initial sandboxed browser launch failed because macOS denied a browser process capability; the authorized run outside that sandbox completed.

**Observed:** Reviewed the regenerated scene contact sheet, phone hero, and print contact sheet. Print pagination includes continuation pages for dense scenes and only the selected explorer states. A decorative background rendered poorly in the PDF inspection tool; print now uses a plain background for that exercise. Current execution results are recorded in `qa/validation.json`; print geometry is recorded separately in `qa/print-validation.json`. Screenshots support visual review, not a claim of measured usability.

The build generates `index.html` and `PRESENTER_GUIDE.md`; edits to the guide therefore belong in `build.mjs` or `src/content.mjs`. The word-by-word script is maintained separately and still needs editorial comparison when scenes change.
