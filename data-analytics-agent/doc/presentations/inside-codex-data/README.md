# Inside Codex Data

An interactive architecture lesson for AI engineers, organized around **Agent → Skills → Evidence → Artifact**.

## Open

Open `index.html` directly in a browser. No server, network connection, package installation, external font, analytics, or CDN is required. Companion Markdown links require the folder’s Markdown files; share the folder if the presenter needs them. The HTML itself contains all styles, scripts, diagrams, source excerpts, and the complete original review. The research iframe is created only when requested.

Use the scene selector or scroll normally. **Presentation mode** provides Previous/Next controls and keyboard scene navigation. Arrow keys, PageUp/PageDown, and Space navigate when focus is outside an interactive control. Escape closes the source drawer first or exits presentation mode. On a shorter screen, scroll within the current scene before advancing. The presentation does not require browser fullscreen.

See [PRESENTER_GUIDE.md](PRESENTER_GUIDE.md) for a 27-minute selective run of show, optional live demos, technical guardrails, and audience questions. See [PRESENTER_SCRIPT.md](PRESENTER_SCRIPT.md) for a fuller 30–35-minute spoken script, linked scene cues, transitions, and optional answers to likely questions. Timing is an estimate, not a measured rehearsal. See [STORYBOARD.md](STORYBOARD.md) for the teaching and interaction plan created before coding.

## Interactions

- Four-box mental model, progressively expanded into the report/dashboard path.
- Nine-step request walkthrough with active responsibilities, inputs, and outputs.
- Five skill families containing all 20 installed skills, with ownership boundaries and summarized rules.
- Evidence → component → artifact tracing and inspectable evidence fields.
- Stable-ID refresh and independent evidence/presentation state simulations.
- Lifecycle and delivery-mode exploration; host capability switches.
- Nine borrowing patterns and six architectural trade-offs.
- Keyboard-accessible source drawer with exact paths, line ranges, excerpts, and copy controls.
- Full original review embedded byte-for-byte and downloadable as HTML or Markdown.

The advisor example and numbers are teaching fixtures, not an executed analytics task. The artifact is an educational model of Data, not an embedded Data runtime. It does not invoke connectors, run queries, modify the installed plugin, publish a Site, or schedule work.

## Source organization

```text
build.mjs             Dependency-free Node build and source verification
src/content.mjs       Scene narrative and structured lesson data
src/skills.mjs        Skill explorer summaries and family taxonomy
src/app.js            Browser interactions and presentation navigation
src/styles.css        Responsive, reduced-motion, and print styles
index.html            Generated standalone deliverable
PRESENTER_GUIDE.md    Generated scene-by-scene guidance
PRESENTER_SCRIPT.md   Hand-authored spoken script and exact scene cues
CLARITY_REVIEW.md     Findings, changes, and remaining validation limits
qa/                   Build and validation evidence
```

Rebuild with Node:

```sh
node doc/presentations/inside-codex-data/build.mjs
```

The build reads the original review and evidence ledger from `doc/reviews/`, plus the installed plugin at the absolute path declared near the top of `build.mjs`. It verifies the source hashes from the original ledger and stops if cited files have changed. This local-source requirement applies to rebuilding, not opening the generated file. The original review files are not modified.

No framework or runtime package is required. Validation uses the already available local Playwright/Chromium tooling; see `qa/validation.json` for the checks and their limits. Print styles support the visible learning state and implementation notes. Use the embedded original review’s print controls for its complete technical-review PDF; the learning layer does not pretend that every unselected interactive state is included in a browser printout.
