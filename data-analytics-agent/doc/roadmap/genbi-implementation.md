# GenBI implementation

The implementation extends the existing local, single-user product. Both clients use the same source-bound coordinator, SQL and Python specialists, evidence, reviews and reports. React is the main workspace; Streamlit retains native analytical controls and a shared dashboard panel.

## Steps

1. **Implemented — Dashboard domain.** Typed dashboard specifications, immutable revisions, scoped evidence bindings, saved views and validation. Domain tests pass.
2. **Implemented and verified — Application integration.** Dashboard tools, report completion, action runs, manual refresh and scoped APIs. SQL ownership and configured reviews remain intact.
3. **Implemented and verified — React workspace.** Conversations, source/file intake, reviews, chat, dashboards, reports, evidence and activity. Production build and typecheck pass.
4. **Implemented and verified — Streamlit integration and launch.** Shared dashboard panel and same-origin React hosting. Both interfaces and reports share visual conventions and chart palettes.
5. **Completed — Verification.** 659 backend passes, six optional provider skips, 22 browser scenarios and an open-tab rebuild regression. Desktop, narrow and dark layouts were visually checked. The user's five saved sample charts render after the fix.

See the [delivery record and receipts](../reviews/genbi-workspace-2026-10-22.md) for exact checks, corrections and limits. The updated local application is running with existing storage. Refresh old browser tabs once to load the chart runtime fix.

## Product boundaries

- Data-changing filters, refresh and drill requests create normal governed runs. The previous dashboard remains visible until its replacement evidence and report succeed.
- Dashboard layout changes use saved evidence and do not call a model or data source.
- A2UI remains optional under the accepted proposal. The canonical BI contract is independent of a transport protocol. Hosted sharing, scheduled refresh and additional presentation agents are outside the local product scope.
- Browser fixtures never become a product demo mode. Provider-backed analytics continue to use the configured provider and existing tools.
