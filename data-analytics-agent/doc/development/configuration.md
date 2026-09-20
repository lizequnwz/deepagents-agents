# Configuration

Start with `.env.example`, add your model credentials, and run
`./scripts/start.sh`. The launcher runs `uv sync --locked`, checks readiness,
and starts the API and Streamlit together. `uv` and `curl` must be installed.
The example file keeps model selection, independent SQL/Python approval, the
source registry, key time budgets and tracing visible. `REQUIRE_SQL_APPROVAL=false`
and `REQUIRE_PYTHON_APPROVAL=false` mean automatic execution; set either to `true`
for manual review. Additional values below are optional overrides; omitting them
uses application defaults. `MODEL_ID` selects the model for either provider.

## Providers

OpenAI is the default provider. Set `OPENAI_API_KEY` and optionally `MODEL_ID`.
For Bedrock, set `MODEL_PROVIDER=bedrock_converse`, choose a Bedrock model or
inference profile in `MODEL_ID`, and configure the normal AWS credential chain
and region. Bedrock does not require an OpenAI key. Credentials belong in your
local environment or `.env`, never in the source registry.

## Advanced environment overrides

The following reference retains the supported defaults. Copy only the settings
you want to change into `.env`. Approval switches and resource limits remain
available independently. Feature switches are retained pending the roadmap's
ablation evaluation.

```dotenv
DATA_SOURCES_CONFIG=data_sources.yaml
API_BASE_URL=http://127.0.0.1:8000
APP_BASE_URL=http://127.0.0.1:8501
# Durable single-user workspace; defaults to .analytics in this repository.
ANALYTICS_STORAGE_DIR=.analytics
SQL_TIMEOUT_SECONDS=10
SQL_MAX_RESULT_ROWS=1000000
MAX_DATASET_BYTES=268435456
UPLOAD_MAX_BYTES=33554432
MODEL_SAMPLE_ROWS=10
REQUIRE_SQL_APPROVAL=false
REQUIRE_PYTHON_APPROVAL=false
ENABLE_DATA_VISUALIZATION=true
ENABLE_DATA_ANALYSIS=true

ANALYSIS_PARALLEL_WORKERS=2
ANALYSIS_BUDGET_SECONDS=900
ANALYSIS_PYTHON_TIMEOUT_SECONDS=120
PRESENTATION_BUDGET_SECONDS=120
ANALYSIS_MAX_STDOUT_CHARS=10000
ANALYSIS_MAX_OUTPUT_ITEMS=10
ANALYSIS_MAX_OUTPUT_ROWS=50
ANALYSIS_MAX_OUTPUT_COLUMNS=20
ANALYSIS_MAX_OUTPUT_CHARS=50000
ANALYSIS_MAX_FIGURES=4
ANALYSIS_MAX_FIGURE_BYTES=1048576
ANALYSIS_MAX_TOTAL_FIGURE_BYTES=3145728
ANALYSIS_MAX_FIGURE_WIDTH=1600
ANALYSIS_MAX_FIGURE_HEIGHT=1200

# Emergency framework limits, separate from active analysis time.
COORDINATOR_MODEL_CALL_LIMIT=96
COORDINATOR_TOOL_CALL_LIMIT=120
SQL_AGENT_MODEL_CALL_LIMIT=48
SQL_AGENT_TOOL_CALL_LIMIT=64
ANALYSIS_AGENT_MODEL_CALL_LIMIT=64
ANALYSIS_AGENT_TOOL_CALL_LIMIT=80
AGENT_DEBUG_DETAILS=false
# PGEOCODE_DATA_DIR=/tmp/pgeocode_data

LANGSMITH_TRACING=false
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=data-analytics-agent

```

`DATA_SOURCES_CONFIG` is resolved relative to the repository unless absolute.
`ANALYTICS_STORAGE_DIR` defaults to the repository's `.analytics` directory.
The launcher exports local service URLs from its host/port settings; set those
in the shell when using custom ports. Source definitions, their semantic models,
and optional source-specific limits live in `data_sources.yaml`; follow
[adding data sources](adding-data-sources.md).

Warehouse configuration is optional for uploaded-file conversations. Source
configuration errors are shown in the app; model configuration still gates runs.
`UPLOAD_MAX_BYTES` bounds original bytes; existing row and decoded dataset-byte
limits also apply. Uploads never silently save a truncated population.

Tracing is optional and disabled unless explicitly enabled. To enable it, set
`LANGSMITH_TRACING=true` and provide your own LangSmith key and project.

## Controlling a run

The starter `.env.example` includes the main controls; additional runtime limits
remain enforced. Defaults still apply; put overrides in `.env` and restart both services to change them.

| Control | Behavior |
|---|---|
| Stop / Resume | Stop requests cancellation and waits for active execution to exit. Saved evidence and checkpoints remain. Resume continues from saved state; an uncommitted interrupted step may execute again. |
| Corrections and clarification | The composer accepts corrections during work. They take effect at the next safe model/tool boundary; already executing work may finish. Business clarification pauses for an answer. |
| SQL / Python review | `REQUIRE_SQL_APPROVAL=true` and `REQUIRE_PYTHON_APPROVAL=true` independently pause before proposed execution. Approve, edit or reject; saved-data SQL is covered too. |
| Parallel saved-data analysis | `ANALYSIS_PARALLEL_WORKERS=2` bounds simultaneous analysis assignments per source graph. Set `1` for sequential execution. Source retrieval remains sequential. Workers share the run’s active-time budget and cancellation; each keeps separate execution evidence and approvals. |
| Active analysis budget | `ANALYSIS_BUDGET_SECONDS=900` counts active analysis, not user wait time. Exhaustion ends computation and attempts a supported partial answer/report with unresolved questions. Resume does not reset accumulated analysis time. |
| Execution timeouts | `SQL_TIMEOUT_SECONDS=10` is the source-query default (sources can override it); `ANALYSIS_PYTHON_TIMEOUT_SECONDS=120` bounds each Python step. Saved-data SQL has its own 120-second timeout. |
| Presentation budget | `PRESENTATION_BUDGET_SECONDS=120` bounds report completion separately. Saved findings can be used by Retry report without repeating analysis. |
| Emergency call limits | Coordinator: 96 model / 120 tool calls; SQL specialist: 48 / 64; analysis specialist: 64 / 80. These framework limits remain independent of elapsed-time budgets. |
| Data/output limits | Row, decoded-byte, preview, Python-output and figure caps bound extraction and presentation. Incomplete extraction is explicit; Python requires complete inputs. |

These are execution and resource controls, not a guaranteed provider-spend cap.
There is currently no per-run dollar or token budget. Activity exposes measured
model/tool usage; do not interpret a call limit as an exact spending limit.

## Development startup

Normal startup disables automatic reload. Restart after code changes, or opt in
with `API_AUTO_RELOAD=true ./scripts/start.sh` for API-only reload restricted to
application Python. Streamlit reruns on user interaction; normal startup does
not rerun an analysis merely because a file was saved.

Shell options: `API_HOST` (127.0.0.1), `API_PORT` (8000), `STREAMLIT_HOST`
(127.0.0.1), `STREAMLIT_PORT` (8501), and `API_AUTO_RELOAD` (false).
Keep a single API process for the local storage and run lifecycle.
