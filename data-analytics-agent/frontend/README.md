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

The client expects API contract 23. An incompatible service displays a restart
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

Production data-changing filters, refreshes and investigations use ordinary
governed runs. Presentation edits use immutable dashboard revisions. The client
retains the previous dashboard while a new run prepares its evidence and report.

Plotly loads in the application entry. It has no delayed chart module that can
disappear while an older workspace stays open. The deployment regression tests
this behavior in an isolated copy. Default colors and fonts match Streamlit and
reports; all chart surfaces use the shared Python product palette.
