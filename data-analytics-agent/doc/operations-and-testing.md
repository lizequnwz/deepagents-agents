# Operations and testing

## Purpose

This guide covers local configuration, startup, readiness, test strategy,
notebook execution, troubleshooting, and maintenance checks.

## Configuration

Copy:

```bash
cp .env.example .env
```

Required:

```text
OPENAI_API_KEY
```

Application defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Agent model |
| `DATA_SOURCES_CONFIG` | `data_sources.yaml` | Trusted registry path |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Streamlit API target |
| `APP_BASE_URL` | `http://127.0.0.1:8501` | Conversation-link base |
| `SQL_TIMEOUT_SECONDS` | `10` | Global execution deadline |
| `SQL_MAX_RESULT_ROWS` | `500` | Global stored-result cap |
| `MODEL_SAMPLE_ROWS` | `10` | Rows exposed to models |
| `ENABLE_DATA_VISUALIZATION` | `true` | Plug the chart specialist into each source graph |

Execution budgets use positive integer settings and cannot be disabled at
runtime:

| Agent | Model calls | All tool calls | Tool-specific calls |
| --- | ---: | ---: | ---: |
| Coordinator | `COORDINATOR_MODEL_CALL_LIMIT=12` | `COORDINATOR_TOOL_CALL_LIMIT=12` | `COORDINATOR_TASK_CALL_LIMIT=4` |
| Text-to-SQL | `SQL_AGENT_MODEL_CALL_LIMIT=24` | `SQL_AGENT_TOOL_CALL_LIMIT=30` | `SQL_EXECUTE_CALL_LIMIT=3` |
| Visualization | `VISUALIZATION_AGENT_MODEL_CALL_LIMIT=12` | `VISUALIZATION_AGENT_TOOL_CALL_LIMIT=16` | — |

Each new user message starts a fresh budget. The same budget continues across
approve, edit, and reject resumptions for that run. Exceeding a limit fails the
run with `execution_budget_exceeded` rather than relying on a very high graph
recursion limit.

Failed runs always expose safe diagnostics: agent, budget type, limit,
attempted count, run ID, and the specific tool when applicable. Set
Set `AGENT_DEBUG_DETAILS=true` only for trusted local debugging. It enables:

- bounded, recursively secret-key-redacted raw inputs on activity tool calls;
- a rolling window of the last five tool payloads on execution-budget errors;
- the latest bounded `values` state snapshot for the coordinator and each
  observed specialist, retained with the completed turn.

State snapshots retain at most 10 recent messages per agent, bound strings and
collections, replace memory contents with path/size metadata, and are capped at
20,000 serialized characters. Debug payloads can still contain SQL, questions,
model text, sampled business data, and unrecognized secrets; never enable this
mode in an untrusted or shared environment.

`PGEOCODE_DATA_DIR` may optionally set the cache directory for the US postal
dataset used by ZIP and city/state maps. `pgeocode` downloads that generic
dataset on first use and then reads the local cache.

Database paths belong in `data_sources.yaml`, not environment variables.
Secrets never belong in the registry, semantic files, tests, logs, or docs.

Optional LangSmith settings are present in `.env.example`. Treat traces as a
data-governance boundary: do not assume prompts, SQL, or outputs are safe to
send to an external observability service.

## Startup

Preferred:

```bash
./scripts/start.sh
```

The launcher:

1. checks `uv`, `curl`, and `.env`;
2. runs `uv sync --locked`;
3. validates settings and requires at least one ready source;
4. rejects occupied ports;
5. starts FastAPI and waits for `/health`;
6. starts Streamlit and waits for its health endpoint;
7. supervises both child processes.

Separate processes:

```bash
uv run uvicorn data_analytics_agent.api:app \
  --host 127.0.0.1 --port 8000

uv run streamlit run streamlit_app.py \
  --server.address 127.0.0.1 --server.port 8501
```

Registry and readiness summaries are cached. Restart FastAPI after modifying
the registry, semantic models, backend targets, or global limits.

## Readiness

Check global health:

```bash
curl --fail http://127.0.0.1:8000/health
```

Check individual sources:

```bash
curl --fail http://127.0.0.1:8000/api/data-sources
```

Without starting HTTP:

```bash
uv run python -c \
  'from data_analytics_agent.api import Services; print([(s.source_id, s.ready, s.errors, s.warnings) for s in Services().source_summaries()])'
```

Global health can be `not_ready` because the model key is missing even while
database/semantic source checks are useful. A source is selectable only when
its own summary is ready.

## Test suite

Run:

```bash
uv run pytest
```

The normal suite covers:

- registry validation and path resolution;
- both included semantic models;
- live SQLite table/column matching;
- generic backend injection;
- SQL safety and SQLite native controls;
- caps, timeout, and normalization;
- source/thread result isolation;
- approval, edit, rejection, and repeated interrupts;
- per-agent execution budgets, all-or-nothing parallel tool limits, and budget
  continuity across review resumptions;
- same-thread resume;
- exact SQL provenance;
- API rehydration and concurrent-run rejection;
- Streamlit helper behavior;
- constrained chart schema and presentation limits;
- automatic chart execution, safe progress arguments, and result provenance;
- Plotly rendering, partial map resolution, and saved-turn reconstruction.

The live OpenAI smoke test is opt-in:

```bash
RUN_LIVE_SMOKE=1 uv run pytest -m live
```

Do not make normal CI depend on cloud credentials, network availability, model
latency, or nondeterministic SQL.

## Tutorial notebook

Open:

```bash
uv run jupyter lab agent_internals_tutorial.ipynb
```

Execute headlessly with live model calls disabled:

```bash
uv run jupyter nbconvert \
  --to notebook \
  --execute agent_internals_tutorial.ipynb \
  --output agent_internals_tutorial.executed.ipynb \
  --output-dir /tmp \
  --ExecutePreprocessor.timeout=180
```

`RUN_LIVE_AGENT` is false by default. Enable it only when intentionally testing
OpenAI calls and HITL cells interactively.

## Documentation and diagram validation

From the project directory:

```bash
ARCHIFY="$HOME/.codex/skills/archify"

node "$ARCHIFY/bin/archify.mjs" validate architecture \
  doc/diagrams/system-architecture.architecture.json --json
node "$ARCHIFY/bin/archify.mjs" validate sequence \
  doc/diagrams/query-approval.sequence.json --json
node "$ARCHIFY/bin/archify.mjs" validate workflow \
  doc/diagrams/data-source-onboarding.workflow.json --json

node "$ARCHIFY/bin/archify.mjs" check \
  doc/diagrams/system-architecture.html
node "$ARCHIFY/bin/archify.mjs" check \
  doc/diagrams/query-approval.html
node "$ARCHIFY/bin/archify.mjs" check \
  doc/diagrams/data-source-onboarding.html
```

After changing diagram JSON, regenerate HTML and SVG using the commands in
[`doc/README.md`](README.md#canonical-diagrams).

Documentation maintenance checks:

- every relative link resolves;
- commands are run from the directory stated;
- test counts and readiness claims are current;
- conceptual future components are labeled as such;
- no secrets, local absolute paths, or database data are included;
- README stays concise and routes details here;
- `HANDOFF.md` describes current state rather than tutorial content.

## Troubleshooting

| Failure | Diagnosis | Resolution |
| --- | --- | --- |
| `.env is missing` | Launcher prerequisite | Copy `.env.example`, set API key |
| Locked sync fails | Lock/project mismatch | Reconcile `pyproject.toml` and `uv.lock`; do not bypass `--locked` |
| Startup says no source ready | Backend or OSI readiness failed | Run the source-summary command and fix reported source |
| SQLite database not found | Registry target path is wrong/missing | Restore the local file or update trusted target |
| OSI table/column missing | Schema drift or model typo | Compare live schema and OSI physical expressions |
| Port occupied | Another process owns 8000/8501 | Stop it or choose explicit host/port |
| Conversation URL returns new thread | API process memory was reset | Expected POC behavior; use durable stores in production |
| Run stays in review | Human decision required | Approve, edit, or reject in Streamlit/API |
| Run fails after edit | Edited SQL violated dialect/safety or provider failed | Inspect sanitized error and submit valid read-only SQL |
| Run fails with `execution_budget_exceeded` | An agent exhausted its model or tool-call allowance | Use the diagnostics expander, then start a narrower or clearer request |
| Chart review repeats | Spec was rejected or failed validation | Review feedback, columns, and chart-ready SQL shape |
| ZIP/city map download fails | First-use `pgeocode` cache is unavailable | Restore network for initial cache or prepopulate `PGEOCODE_DATA_DIR` |
| Live smoke skipped | Opt-in flag absent | Expected in normal suite |
| Archify validation fails | Layout/schema issue | Apply validator’s exact suggested coordinate/label fix |

## Safe maintenance method

1. Identify the authoritative contract and affected trust boundary.
2. Add or update focused tests.
3. Make the smallest implementation change.
4. Run focused tests, then full suite.
5. Execute notebook if learning-path claims changed.
6. Validate source readiness.
7. Exercise source switching and SQL review when UI/lifecycle changed.
8. Update README, relevant guide, diagrams, and handoff in the same change.

## Concise production checklist

The local launcher is not a deployment system. Before production, add:

- authenticated/authorized API and result access;
- durable conversation, run, checkpoint, and artifact stores;
- managed secrets and connection lifecycle;
- deployment health/readiness probes;
- structured redacted logs, metrics, and audit trail;
- concurrency controls, cancellation, retries, and rate limits;
- retention, deletion, backup, and recovery;
- least-privilege database roles and network policy.
