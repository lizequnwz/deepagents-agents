# Analytics workspace design system

22 October 2026. Scope: the React web workspace. Streamlit remains available.

## Direction and evidence

Use a clear, data-dense analytical workspace with progressive disclosure. Show
the result, its scope and the next useful action. Keep controls predictable and
reserve visual emphasis for the current primary action.

The ui-ux-pro-max search returned **Data-Dense Dashboard** as an applicable style
for business intelligence. The generated **Enterprise Gateway** page pattern was
still a marketing layout after one narrower retry; no applicable page pattern was
verified, so that output was rejected. This workspace structure follows the
observed product and the skill's verified accessibility and dashboard guidance.
Its suggested blue palette and code-style headings were not adopted: the existing
green/warm-neutral identity remains authoritative across React, Streamlit and reports.

## Visual rules

- Keep green `#368727`, warm background `#F9F7F5`, neutral secondary surface
  `#F5F3F0`, text `#141414`, muted text `#525150` and border `#D9D8D5` in light mode.
- Pair dark surfaces `#141414`/`#292928` with readable light text and lighter green
  controls. Measure text contrast separately in each theme.
- Use semantic CSS tokens for surfaces, text, feedback, focus and interaction.
- Use the shared humanist sans stack for application headings, controls and data.
  Reserve the existing slab stack for the wordmark and report-document headings.
- Use 15–16px body text, at least 12px supporting text and 16px mobile inputs.
  Data values use tabular figures. Long labels wrap or remain inspectable.
- Use a consistent 4/8px spacing scale, restrained borders, 8–12px corners and
  subtle elevation. Avoid decorative gradients, glass effects and marketing heroes.
- Keep the existing Lucide SVG family; hide decorative icons from assistive technology.

## Workspace structure

- Sidebar: new workspace, search, saved workspaces and local/theme status.
- Header: source context, clear conversation control and a secondary action menu.
- Findings area: Findings/Dashboard, Report and Data tabs; saved view selection.
- Conversation: readable answers, progressive evidence/activity disclosures and
  a visible-label composer. Send and Create dashboard are explicit actions over
  the same question, with no persistent response-format mode.
- Dashboard: title, revision/snapshot context, declared filter scope, draft versus
  applied state, then analytical panels. Respect stored component widths.
- Size the panel grid from the canvas container rather than the entire viewport.
  A narrow canvas should not show an unnecessarily small chart beside empty space.

## Interaction and accessibility

- Use native controls, visible labels, contextual errors and recovery actions.
- Tabs support arrows, Home and End with a roving tab stop. Drawers and dialogs
  support Escape, focus containment and focus return.
- Keep main touch controls at least 44 CSS px on small screens; all authored web
  pointer targets meet 24 CSS px or an applicable spacing exception.
- Provide visible keyboard focus and keep focused controls clear of sticky UI.
- On phones, Findings and Conversation switch between usable panes instead of
  placing the composer below the full dashboard. Retain the draft when switching.
- Show unapplied filter changes explicitly. Apply only declared predicates through
  the existing analytical action API. Layout changes remain independent of data.
- Charts retain interval notes/warnings, text labels, saved-data access and retry.
  Sorting a bounded preview is labeled and does not claim to sort the population.
- Reserve chart space while loading. Respect reduced motion; no animation gates
  access to data or input.
- Retain the static Plotly runtime. A general lazy-loading recommendation must not
  reintroduce the verified missing-module failure for already-open workspaces.

## Verification

Test existing analytical journeys plus search, keyboard tabs, drawer/modal focus,
phone portrait/landscape, tablet, wide desktop, reflow equivalent to 200% zoom,
reduced motion and independent light/dark contrast. Build and test in an isolated
frontend copy before publishing one tested build to the user's running workspace.
