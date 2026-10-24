# GenBI workspace implementation and verification

22 October 2026. This increment implements the accepted local dashboard direction.
Final verification passed: **659 regression tests**, six optional provider skips,
**22 browser scenarios**, and the open-tab rebuild regression. Lint, type checks,
production build and lock-file checks also passed.

The later [React design increment](react-ui-redesign-2026-10-22.md) replaces the
output selector with explicit actions and retains Streamlit at the user's request.
This record preserves the earlier implementation and verification snapshot.

The [validation receipt](genbi-workspace-2026-10-22/validation.json) identifies the
tested source and assets. Separate receipts record the
[browser journeys](genbi-workspace-2026-10-22/browser-receipt.json),
[rebuild case](genbi-workspace-2026-10-22/deployment-receipt.json), and
[read-only saved-workspace check](genbi-workspace-2026-10-22/saved-workspace-receipt.json).

## Delivered behavior

The React workspace and native Streamlit workbench use one FastAPI application,
one conversation history and the same saved evidence. The coordinator keeps its
SQL and Python specialists. Dashboard composition is a feature with an on-demand
skill. It does not add another autonomous agent.

Dashboards contain typed metric, chart, table and text components. Numerical
components bind to published evidence. Each dashboard has immutable revisions,
explicit filter bindings and a matching saved HTML report. Layout and draft
selection changes use saved data without a model or source call.

Filter, refresh and investigation actions create normal analytical runs. SQL owns
warehouse execution and descriptive data shaping. Configured reviews still apply.
The previous dashboard stays visible until replacement evidence and its report
succeed. Empty populations have explicit no-data bindings. A failed action cannot
relabel old numbers as new observations.

The shared API rejects stale revisions and request IDs reused with different
content. Repeated action requests resolve to their original run. Paused actions
keep their head revision stable for Resume. Ordinary follow-ups carry the displayed
dashboard scope. Prose received during a typed action becomes a separate follow-up.

## Verification scope

The browser runner uses the production React build and actual FastAPI services.
Its source is an isolated SQLite fixture with reviewed semantic definitions.
Uploads, saved-data SQL, evidence, dashboards, reports and persistence use the
application implementations. A scripted agent drives the normal run manager;
there are no provider requests and no product demo mode.

Browser checks cover desktop and narrow layouts, both themes, keyboard focus,
source selection, conversations, required schema review, CSV/Parquet/Excel intake,
documents, SQL/Python review, saved dashboards, explicit filters, refresh,
investigation failure, empty results, draft choices, Stop/Resume, queued prose,
restart persistence, downloads and native Streamlit dashboard controls.
Voice checks use a simulated microphone and an intercepted transcription response.
They verify recording, WAV submission and an editable unsent draft. They do not
verify physical microphone quality or the transcription provider.

## Corrections made during verification

- Fix the real-user chart failure after a rebuild. Plotly now loads with the
  application entry instead of a delayed versioned module. No obsolete assets
  are retained. Existing old tabs require one refresh. The local entry is larger
  (about 5.1 MB before compression); it contains the chart runtime needed by BI.
- Align React with the existing report/Streamlit colors, font stacks, borders
  and corners. One shared chart style controls default palettes across all three
  surfaces. Explicit chart palette choices remain authoritative.
- Restore saved filter drafts separately from applied data. Display all saved
  category values when another interface stored several selections.
- Keep Stop available while code review or clarification is open. Prevent late
  asynchronous responses from changing a different selected workspace.
- Preserve explanatory chart warnings and interval notes in both interfaces.
- Block view mutations during a paused dashboard action while preserving
  idempotent retries and Resume.
- Preserve typed action parameters when a user sends prose during that action.
- Refresh the retained prompt-study patch context so it still applies. The study
  candidate remains an experiment; no provider study was rerun.

Initial browser attempts also exposed selector/timing errors in the new test
harness. They were corrected before the final clean run. Skips and failed attempts
are not counted as passes.

The initial fresh-page tests missed the missing-module failure later reported by
the user. The added regression opens an app without a chart, rebuilds an isolated
copy, verifies that the old entry was deleted, and renders the first chart in the
original tab without another script request. A reload then uses the new entry.
All 22 final browser journeys have zero JavaScript, console or HTTP errors.

After restarting the idle local application with its existing storage, a read-only
browser check rendered all **five charts** in the user's saved sample workspace.
It made no new analytical or provider requests. The local application remains
available at `http://127.0.0.1:8000/workspace/`.

Visual review covered the final [desktop dashboard](genbi-workspace-2026-10-22/react-dashboard.png),
[narrow layout](genbi-workspace-2026-10-22/react-mobile.png), and
[dark theme](genbi-workspace-2026-10-22/react-dark.png). Native
[Streamlit controls](genbi-workspace-2026-10-22/streamlit-controls.png) were visually
checked; native chart rendering and dashboard actions passed the browser assertions.

## Interface recommendation after user feedback

React should be the single main user interface. Questions and dashboards use the
same coordinator, specialists and evidence. The current Answer/Dashboard selector
sets the requested output; it does not select another agent.

Replace that selector with one question box and explicit Create dashboard or
Save dashboard actions. Keep chat, saved dashboards, reports and data in one
workspace. The HTML report remains the portable evidence document.

Keep Streamlit as an internal workbench while deciding which native controls must
move to React. Direct chart edits and report-title edits are concrete remaining
differences. Remove duplicate user-facing entry points after that decision.
This consolidation is a recommendation, not an implemented removal of Streamlit
or the current selector. Exported report theme controls remain independent of
the workspace's light/dark selection.

## Limits

This remains a local, single-user application. No live-model accuracy study,
production warehouse study or human usability study ran. Existing optional
provider tests remain opt-in. A2UI transport, hosted identity/sharing and scheduled
refresh remain separate decisions under the accepted proposal. The implemented
canonical dashboard contract does not require A2UI.

The API contract is 23 and the application version is 0.8.0. Older incompatible
storage requires a fresh directory; no compatibility readers or migrations were
added. Original saved artifacts must be preserved separately when switching
storage directories.
