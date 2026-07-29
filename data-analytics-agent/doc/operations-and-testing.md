# Operations and testing

## Purpose

This guide covers local configuration, startup, readiness, test strategy,
notebook execution, troubleshooting, and maintenance checks.

## Configuration

Copy:

```bash
cp .env.example .env
```

Choose one provider:

```text
MODEL_PROVIDER=openai
MODEL_ID=gpt-5.6-luna
OPENAI_API_KEY=...
```

or use Bedrock Converse with the standard AWS credential chain:

```text
MODEL_PROVIDER=bedrock_converse
MODEL_ID=us.anthropic.claude-sonnet-4-6
AWS_REGION=us-east-1
```

Application defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `MODEL_PROVIDER` | `openai` | `openai` or `bedrock_converse` |
| `MODEL_ID` | `gpt-5.6-luna` | Provider-native agent model ID; falls back to legacy `OPENAI_MODEL` |
| `DATA_SOURCES_CONFIG` | `data_sources.yaml` | Trusted registry path |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Streamlit API target |
| `APP_BASE_URL` | `http://127.0.0.1:8501` | Conversation-link base |
| `SQL_TIMEOUT_SECONDS` | `10` | Global execution deadline |
| `SQL_MAX_RESULT_ROWS` | `10000` | Global stored-result cap; truncated results cannot be statistically analyzed |
| `MODEL_SAMPLE_ROWS` | `10` | Rows exposed to models |
| `ENABLE_DATA_VISUALIZATION` | `true` | Plug the chart specialist into each source graph |
| `ENABLE_STATISTICAL_ANALYSIS` | `true` | Plug the reviewed statistical Python specialist into each source graph |
| `ENABLE_REPORTING` | `true` | Add the coordinator report-design skill and trusted HTML renderer |

Statistical Python settings are configurable in `.env`:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `STATISTICAL_PYTHON_TIMEOUT_SECONDS` | `30` | Hard child-process timeout |
| `STATISTICAL_MAX_STDOUT_CHARS` | `10000` | Captured stdout/stderr characters each |
| `STATISTICAL_MAX_OUTPUT_ITEMS` | `10` | Named `analysis_outputs` entries |
| `STATISTICAL_MAX_OUTPUT_ROWS` | `50` | Rows per compact output table |
| `STATISTICAL_MAX_OUTPUT_COLUMNS` | `20` | Columns per compact output table |
| `STATISTICAL_MAX_OUTPUT_CHARS` | `50000` | Combined non-image output characters |
| `STATISTICAL_MAX_FIGURES` | `4` | Figures per execution |
| `STATISTICAL_MAX_FIGURE_BYTES` | `1048576` | PNG bytes per figure |
| `STATISTICAL_MAX_TOTAL_FIGURE_BYTES` | `3145728` | Combined PNG bytes |
| `STATISTICAL_MAX_FIGURE_WIDTH` | `1600` | Maximum rendered width |
| `STATISTICAL_MAX_FIGURE_HEIGHT` | `1200` | Maximum rendered height |
| `STATISTICAL_MAX_EXECUTION_ATTEMPTS` | `3` | Actual runs, excluding review rejections |

Execution budgets use positive integer settings and cannot be disabled at
runtime:

| Agent | Model calls | All tool calls | Tool-specific calls |
| --- | ---: | ---: | ---: |
| Coordinator | `COORDINATOR_MODEL_CALL_LIMIT=32` | `COORDINATOR_TOOL_CALL_LIMIT=24` | `COORDINATOR_TASK_CALL_LIMIT=12` |
| Text-to-SQL | `SQL_AGENT_MODEL_CALL_LIMIT=24` | `SQL_AGENT_TOOL_CALL_LIMIT=30` | `SQL_EXECUTE_CALL_LIMIT=3` |
| Visualization | `VISUALIZATION_AGENT_MODEL_CALL_LIMIT=12` | `VISUALIZATION_AGENT_TOOL_CALL_LIMIT=16` | — |
| Statistical analysis | `STATISTICAL_AGENT_MODEL_CALL_LIMIT=24` | `STATISTICAL_AGENT_TOOL_CALL_LIMIT=24` | Three actual executions enforced separately |

Each new user message starts a fresh coordinator budget. The same coordinator
budget continues across approve, edit, and reject resumptions for that run.
Each specialist assignment has its own budget, which continues across that
assignment's review resumptions. The coordinator model allowance is larger
than its all-tool allowance so it can still produce the final structured answer
after the last permitted tool call. Exceeding a limit fails the run with
`execution_budget_exceeded` rather than relying on a very high graph recursion
limit.

Failed runs always expose safe diagnostics: agent, budget type, limit,
attempted count, run ID, and the specific tool when applicable. Set
`AGENT_DEBUG_DETAILS=true` only for trusted local debugging. It enables:

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

## Operational diagnostics and logs

Diagnostics are collected locally without LangSmith. Each run reports
provider-reported input, output, and total tokens; optional cached-input and
reasoning-output tokens; model/tool call counts and durations; elapsed time;
active execution time; and approval wait time. Agent rows are aggregate only.
Conversation diagnostics sum every run, including active and failed runs.

A token total is marked partial when a model call is still active or its
provider did not return complete usage metadata. The application does not
estimate missing tokens and does not calculate monetary cost. Diagnostics are
process-local and reset with the API process. LangChain models initialized by
the application use `streaming=False` so callback completion and usage
collection follow one predictable path.

The API always writes concise `key=value` logs to stderr and
`logs/api.log`. The file rotates at 10 MiB and retains five backups. It records
API/Uvicorn startup and errors plus run pause/resume/completion/failure,
per-agent summaries, and completed/failed tool durations. Uvicorn access logs
are disabled because Streamlit polls the API frequently. Prompts, responses,
request bodies, tool payloads, SQL, results, and report contents are not logged.
Log initialization is intentionally fail-fast if the directory or file cannot
be created.

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

Development reload is enabled by default. The FastAPI watcher is rooted at
`data_analytics_agent/` and uses Uvicorn's default `*.py` filter. The project
`.venv` is therefore outside the watched tree entirely. Restart FastAPI
manually after changing `.env`, Markdown agent policies/skills, source YAML, or
semantic models. Streamlit also reruns on watched source changes.

FastAPI reload creates a new process and therefore clears the POC's in-memory
`ConversationStore`, `RunStore`, `ResultStore`, `StatisticalAnalysisStore`, and
`ReportStore`, including pending HITL reviews, reusable analyses, and report
versions. Use non-reloading mode for longer manual test sessions:

```bash
API_AUTO_RELOAD=false ./scripts/start.sh
```

Separate processes:

```bash
uv run uvicorn data_analytics_agent.api:app \
  --host 127.0.0.1 --port 8000 --no-access-log

uv run streamlit run streamlit_app.py \
  --server.address 127.0.0.1 --server.port 8501
```

Registry and readiness summaries are cached. Restart FastAPI after modifying
the registry, semantic models, backend targets, or global limits in `.env`.
With auto-reload disabled, also restart it after changing Python source.

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
- exact reviewed statistical Python, result scope, truncation refusal, output
  bounds, figure capture, and repair-attempt limits;
- API rehydration and concurrent-run rejection;
- provider-reported token aggregation, per-agent timing, approval wait, and
  conversation totals with controlled clocks and fake model responses;
- rotating API log initialization and access-log suppression;
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
| Python review returns after a failure | Reviewed code failed or exceeded a bound | Inspect the bounded error, review the repaired proposal, or reject with guidance |
| Statistical analysis requests new SQL | Result was truncated or had the wrong grain/columns | Review the single analysis-ready reshape query |
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
