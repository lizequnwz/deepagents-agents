# Full-browser verification

The runner starts the real FastAPI application and Streamlit interface on isolated
local ports. React uses its production build, served by the same application.
The test source, saved evidence, reports and pending reviews are created inside
the test output directory. The fixture agent exercises the normal run manager
without sending requests to a model provider.

```bash
npm --prefix frontend ci
node tests/ui/stage.mjs --output /tmp/analytics-ui-stage
node tests/ui/run.mjs --frontend-root /tmp/analytics-ui-stage/frontend
node tests/ui/redesign.mjs --frontend-root /tmp/analytics-ui-stage/frontend
node tests/ui/genbi-interactions.mjs --frontend-root /tmp/analytics-ui-stage/frontend
node tests/ui/editorial.mjs --frontend-root /tmp/analytics-ui-stage/frontend
node tests/ui/deployment.mjs
```

Choose a fresh staging directory on each run. Staging copies the source and builds
against the existing locked dependencies. It never replaces assets served by the
user's application. `--frontend-root` selects that build for the functional and
focused redesign runners, including their API restart checks.

The default output is `frontend/test-results/ui/`. It contains browser screenshots,
service logs and a JSON receipt with each scenario's result. The runner stops only
the service processes it started. Set `CHROME_PATH` if Chrome uses another path.
Playwright's installed browser is used when the default macOS Chrome path is absent.

Use `--api-port` and `--streamlit-port` to choose unused ports. Use
`--external-server --base-url URL --manifest PATH` to test an already running
instance created by `tests.ui.server`. `--skip-streamlit` runs React checks alone.

The checks cover source selection, conversation, requested and saved dashboards,
explicit linked filters, empty populations/reset, view drafts, refresh, drill
failure, stale revisions, duplicate actions, follow-up context, queued prose,
Stop/Resume and restart persistence. They also exercise real CSV/Parquet uploads,
Excel table selection and review, document context, clarification, SQL/Python
review, report/data downloads, narrow layouts, keyboard controls and dark theme.
The native Streamlit journey opens the shared dashboard, applies its filter,
refreshes evidence, saves/reopens a view and saves a completed report as a dashboard.

The voice test uses Chrome's fake microphone. It submits a real nonempty mono PCM
WAV recording to the API, whose test-only transcription provider returns a known
sentence. The sentence remains an editable draft until Send. The review tests
verify the exact edited-code submission; numerical execution is covered by the
backend suite. The receipt records the built assets, browser exceptions and error
console messages.

These tests verify product interactions and persistence over deterministic local
evidence. They do not measure model accuracy or warehouse performance.

The deployment check copies frontend source into its output directory and uses the
existing locked dependencies. It builds once, opens the application without a
chart, changes only that temporary copy, and builds again. The second build must
remove the first hashed entry. The original open tab must then render its first
chart without requesting a script, and a reload must use the new build. This
checks the stale-tab failure without rebuilding the user's running application.
It also saves a screenshot and a separate JSON receipt. The regular suite checks
that workspace and report colors and font families use the same default brand.

The focused redesign runner checks history search, keyboard tabs, modal/drawer
Escape and focus restoration, unapplied filter choices, accessible chart data,
preview sorting and chart retry. It captures 375px, 768px, 1440px and 1920px layouts
plus phone landscape. It measures authored control sizes, horizontal reflow,
visible composer focus, light/dark text contrast and reduced-motion transitions.
Small-phone checks also cover automatic CSV schema review, the SQL approval
controls, and Excel selection with modal focus containment and Escape.
The zoom check uses a 720 CSS-pixel viewport at device scale 2, equivalent to the
layout space of a 1440px browser at 200% zoom. This is a focused interaction and
layout check, not a complete accessibility conformance audit.
