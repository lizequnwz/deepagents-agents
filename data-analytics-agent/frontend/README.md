# Analytics workspace

This React client uses the same FastAPI application and saved evidence as the
Streamlit workbench. It has no warehouse credentials or separate agent runtime.

Build the production client:

```bash
npm ci
npm run build
```

FastAPI serves `dist/` at `/workspace/`. The repository launcher builds this
client before starting the application. For UI development, run `npm run dev`;
Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

The client expects API contract 24. An incompatible service displays a restart
message instead of allowing mutations.

## Browser tests

From the repository root:

```bash
node tests/ui/run.mjs
node tests/ui/deployment.mjs
```

The tests start isolated local services with real saved evidence and a scripted
agent. They do not need a provider key or query a production source. Their report
and screenshots are saved under `frontend/test-results/`, which Git ignores.

Data-changing actions use governed runs. Established saved-data filters can execute
without a model through SQL-owned definitions. Refresh and new analysis retain the
specialists. Dashboard layout edits use immutable revisions. Direct chart edits
on completed findings save a matching chart/report pair. The client
retains the previous dashboard while a new run prepares its evidence and report.
Metric Number format edits also save a matching dashboard/report revision over
unchanged evidence. Saved dashboards open with the canvas in focus. Required
reviews and clarifications open the conversation automatically.

The dashboard uses an editorial reading order: saved title and scope, compact
metrics, lead chart, supporting data, then collapsed evidence. The design record
is `design-system/analytics-workspace/MASTER.md`. Table display rounding retains
exact saved values through pointer and keyboard inspection.

Active runs use the scoped AG-UI event attachment. Browser reconnect observes saved
state and cannot start another execution. Typed chart selections and multi-value
filters retain exact saved scalar identities. The A2UI server export is available;
the local renderer remains the trusted dashboard UI because the current maintained
A2UI browser package has an unresolved dependency advisory.

Dashboard types come from the Python response schema:

```bash
npm run generate:dashboard
npm run check:dashboard
```

The generator reads models without opening application storage. Commit the generated
file with schema changes. `check:dashboard` detects stale output.

Plotly loads in the application entry. It has no delayed chart module that can
disappear while an older workspace stays open. The deployment regression tests
this behavior in an isolated copy. Default colors and fonts match Streamlit and
reports; all chart surfaces use the shared Python product palette.
