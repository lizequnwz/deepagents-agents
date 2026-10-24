# React workspace design and verification

22 October 2026. This increment improves the React interface with the requested
ui-ux-pro-max skill. Streamlit remains available. Both interfaces use the same
agents, conversations and saved evidence.

## Delivered design

- Use clearer sans-serif headings, readable labels, consistent spacing and
  restrained borders. Retain the existing green and warm-neutral identity, with
  a paired dark theme.
- Search saved workspaces from the sidebar. Show the current workspace clearly.
  Keep secondary actions in a workspace menu.
- Replace the Answer/Dashboard selector with explicit **Send** and **Create
  dashboard** actions over one question box. These actions use the same analyst.
- Keep findings and conversation beside each other on larger screens. On phones,
  switch between usable panes without losing the question draft. Required file
  review opens automatically.
- Size dashboard columns from the available canvas width. Show the saved version,
  time and panel count. Keep filters compact and distinguish unapplied choices
  from the data currently shown.
- Show investigation actions, chart loading states and an explicit chart retry.
  Provide a keyboard-accessible data preview and download beside each chart.
  Table headings sort only the shown rows; the interface states that limit.
- Support keyboard tabs, visible focus, drawer and modal focus containment,
  Escape, focus return and reduced motion.

The [design master](../../design-system/analytics-workspace/MASTER.md) records the
selected rules. The skill search identified **Data-Dense Dashboard** as a suitable
style. Its marketing-page pattern remained unsuitable after a narrower retry and
was rejected. The implementation retains the established product identity and
existing dependencies. It adds no remote fonts or UI library.

Plotly still loads with the main application entry. The redesign preserves the
previous repair for charts in already-open tabs. Saved evidence, filter action
contracts, required reports and configured code review are unchanged. This
increment changes no Streamlit product code or agent instructions.

## Verification method

Build and browser checks use an isolated copy of the final frontend source. The
running application's assets stay intact during testing. The final tested assets
are then published together; obsolete assets are removed.

The browser runners use Chrome and the actual FastAPI application with isolated,
deterministic evidence. A scripted agent exercises the normal run manager. The
checks make no model-provider or production warehouse requests. Voice checks use
a simulated microphone and transcription response.

Focused design checks cover search, keyboard navigation, chart recovery, saved
data, filter state, dialog focus, upload review and SQL approval. The viewport
matrix covers a 375px phone, tablet, desktop, wide desktop and phone landscape.
It also checks reduced motion, light/dark text contrast and reflow equivalent to
a 1440px browser at 200% zoom. This is a focused accessibility check, not a complete
conformance audit or a human usability study. Other browser engines were not tested.

Early checks exposed a hidden mobile upload review and a focusable closed drawer;
both were corrected. Two later test issues were corrected without product edits:
focus geometry was read before smooth scrolling settled, and a Streamlit form was
incorrectly assumed to expose a keyed CSS class. Failed attempts are not counted
as passes.

## Final results

| Check | Result | Evidence |
|---|---|---|
| Existing browser workflows, including native Streamlit | 22/22 pass | [Browser receipt](react-ui-redesign-2026-10-22/browser-receipt.json) |
| Focused design and interaction groups | 9/9 pass | [Design receipt](react-ui-redesign-2026-10-22/design-receipt.json) |
| Already-open workspace after a rebuild | Pass; first chart needs no new script request | [Deployment receipt](react-ui-redesign-2026-10-22/deployment-receipt.json) |
| Targeted API, launcher and Streamlit regression checks | 15 pass | [Validation record](react-ui-redesign-2026-10-22/validation.json) |
| TypeScript, production build, runner syntax and diff checks | Pass | [Validation record](react-ui-redesign-2026-10-22/validation.json) |
| Read-only check of the user's saved workspaces | Seven charts render across two workspaces | [Saved-workspace receipt](react-ui-redesign-2026-10-22/saved-workspace-receipt.json) |
| Local API, React and retained Streamlit availability | HTTP 200; exact tested assets served | [Service receipt](react-ui-redesign-2026-10-22/live-services.json) |

Final browser suites have zero JavaScript, console or HTTP errors. The published
entry is `index-Di_vRRZm.js` with `index-GjzC33Sx.css`. Source and asset hashes are
saved in the validation record. The earlier full Python regression remains
documented in the [dashboard implementation record](genbi-workspace-2026-10-22.md);
it was not repeated for this frontend-only increment.

Visual review covers the [desktop dashboard](react-ui-redesign-2026-10-22/react-desktop.png),
[phone conversation](react-ui-redesign-2026-10-22/react-phone-conversation.png),
[phone findings](react-ui-redesign-2026-10-22/react-phone.png),
[dark theme](react-ui-redesign-2026-10-22/react-dark.png),
[required file review](react-ui-redesign-2026-10-22/react-phone-schema-review.png),
[SQL approval](react-ui-redesign-2026-10-22/react-phone-sql-review.png),
[Excel selection](react-ui-redesign-2026-10-22/react-phone-excel-dialog.png) and
[retained Streamlit controls](react-ui-redesign-2026-10-22/streamlit-dashboard.png).

The read-only check also found one saved failed agent run with the message
“Agent finished without a structured response.” The same error was present in
the API before the browser loaded. It is retained and recorded separately from
chart rendering; this design increment does not repair that agent-execution error.

The local [React workspace](http://127.0.0.1:8000/workspace/) now serves the tested
design. Reload an existing tab to use it. [Streamlit](http://127.0.0.1:8501) remains
available with its existing controls.
