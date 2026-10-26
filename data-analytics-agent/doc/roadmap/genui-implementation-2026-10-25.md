# GenUI implementation

Updated 26 October 2026. Implement the reviewed direction in complete, tested increments.
The existing coordinator, SQL owner, Python specialist and evidence stores remain authoritative.

## Work sequence

1. **Complete — Fast, scoped actions.** Added SQL-owned saved-data query definitions and receipts, configured review, typed chart selections, complete filter search, and direct chart/report and metric-format edits. New meaning and source refresh retain the specialists. Required reports remain.
2. **Complete — Live run interface.** Added a public AG-UI event projection with scoped attachment and replay. React now observes events. Reconnection does not start another execution. The GET attachment is an application transport, not AG-UI's POST run binding.
3. **Bounded delivery — Analytical surface.** Added the A2UI v0.9.1 evidence-reference compiler and tests. Tested the maintained renderer package, then removed it because its required dependency tree has an unresolved advisory. The local evidence panel uses canonical React components. See the [protocol decision](../reviews/genui-protocol-evaluation-2026-10-25.md).
4. **Complete — Visual review and integration.** Added an editorial dashboard header, compact metric strip, prominent lead chart, quiet evidence inspection, responsive controls, and exact-value access for rounded table displays. Verified 36 browser scenarios, including native Streamlit, plus the focused visual checks. CopilotKit's runtime remains outside this increment because it would add execution and persistence ownership that this application already supplies.

## Acceptance rules

- UI values bind to scoped saved evidence. Chart samples never become analytical inputs.
- Known actions retain metric meaning, grain, population and declared units.
- New business meaning returns to the existing specialists.
- Source execution remains SQL-owned and sequential. Configured reviews remain effective.
- Network recovery does not rerun a graph or duplicate a source query.
- A new dashboard head requires its evidence and HTML report.
- Unsupported protocols and actions fail explicitly. No compatibility reader or migration is added.
- This local increment does not add hosted identity, paid services or another agent runtime.

## Verification

The latest complete local regression run passed **773 tests**, with **six opt-in
provider tests skipped**. The dependency lock check passed. The current frontend
dependency audit reports **zero known vulnerabilities**. Browser verification passed
**22 full scenarios, nine design scenarios, and five GenBI interaction scenarios**.
Desktop, phone, dark theme, metric/report parity, exact values, and review visibility
also passed focused checks. See the [delivery review](../reviews/genui-delivery-2026-10-26.md).
Do not infer live-model accuracy from scripted fixtures.
