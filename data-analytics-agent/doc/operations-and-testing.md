# Operations and verification

Install with `uv sync`, configure `.env`, and run `./scripts/start.sh`. Use one
API worker. The workspace directory defaults to `.analytics`; back up its SQLite
files and artifacts together while the API is stopped. Existing in-memory state
from old releases has no migration. Credentials stay in the local environment.

| Setting | Default |
|---|---:|
| REQUIRE_SQL_APPROVAL / REQUIRE_PYTHON_APPROVAL | false / false |
| SQL_MAX_RESULT_ROWS | 1,000,000 |
| MAX_DATASET_BYTES | 268,435,456 |
| MODEL_SAMPLE_ROWS | 10 |
| ANALYSIS_BUDGET_SECONDS | 900 |
| ANALYSIS_PYTHON_TIMEOUT_SECONDS | 120 |
| PRESENTATION_BUDGET_SECONDS | 120 |

Source-specific retrieval limits in `data_sources.yaml` can narrow extraction.
A capped dataset is explicitly incomplete. Request an aggregate or narrower
complete population before modeling. Report tables are bounded independently;
CSV/Parquet downloads contain the complete saved artifact, including a clearly
identified capped artifact when source extraction was incomplete.

After a restart, open Saved conversations. Unfinished work displays Resume;
approval-required work retains its proposed code and bindings. Stopping an
execution may take time if its provider cannot cancel immediately; status stays
Stopping until the worker exits. A worker interrupted before output commit may
run again on resume. Committed tool outputs are reused.

Run `uv run pytest` for local deterministic regression/integration tests and
`uv run ruff check data_analytics_agent streamlit_app.py tests --select F` for
undefined/unused names. Local tests do not require model invocation. Browser
checks use an isolated fixture API with synthetic findings and saved reports.
Do not use an actual business source to test UI controls that can start work.

Opt-in live evaluations must be explicitly enabled and need the configured
provider's credentials. They should use synthetic fixtures, assert numerical
correctness with tolerances, and assess holdouts, baselines, uncertainty,
seasonality suitability and evidence reuse. Exact generated SQL text is not a
grading criterion. Live outcomes depend on provider/model availability.

If the report fails, inspect its rendering error, correct the specification,
and use Retry report. Do not repeat SQL/Python just to regenerate presentation.
If the API/UI contract mismatch appears, restart both processes from the same
checkout; saved artifacts remain available.

History deletion is available through `DELETE /api/conversations/{thread_id}` and
`DELETE /api/conversations`. Both return the deleted conversation count. Active
computations return HTTP 409; stop them and wait for pause before retrying. Deleted
work is removed from metadata, tool execution records, owned artifact files, and
LangGraph checkpoints. The Streamlit controls require confirmation. API contract
version 10 requires restarting both services after upgrading.


## Semantic versions and steering

Restart both services to load OSI edits. Graphs and semantic packages are keyed by
source identity, catalog content hash and dialect; business/physical projections
and request selections are separate cache keys. A run records the loaded content
hash. Resuming with a different hash fails explicitly, retaining saved evidence.
This prevents an investigation from silently changing business definitions. Older
unversioned checkpoints cannot resume safely; start a new turn using their saved
evidence. No checkpoint migration or live catalog reload is provided.

`POST /api/runs/{run_id}/corrections` accepts `{ "message": "..." }` and returns
`run_id`, durable `message_id`, `disposition` (`pending` or `follow_up`) and an
acknowledgement. Pending corrections appear in run/history records with their
ordered original text and `delivered_to` agents. Published findings are immutable;
post-publication input gets a new run and waits for the current owner to finish.

`request_clarification` uses LangGraph interrupts. The run status becomes
`clarification_required`, separate from `approval_required`, with question,
choices and interrupt ID. `POST /api/runs/{run_id}/clarification` accepts free text
in `message` and resumes that interrupt. Corrections during a code review reject
the previous proposal; they do not approve it.

The test bootstrap overrides inherited storage before importing the application.
An autouse fixture assigns fresh storage to every test. Live model calls remain
opt-in. See `agent-efficiency-and-progress.md` for verification and timing limits.
