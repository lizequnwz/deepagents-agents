# General Agent

General Agent is a trusted-local assistant built with DeepAgents,
LangChain, FastAPI, and Streamlit. It can plan, delegate to its configured
`general-purpose` subagent, inspect common document formats, manage isolated
chat files and explicitly shared files,
run Python or shell commands, and preserve downloadable versions of every file
changed by a turn.

> [!CAUTION]
> Command execution is intentionally automatic and is **not sandboxed**.
> DeepAgents' built-in file tools are virtual-rooted to `workspace/`, but shell
> commands run with the current local user's host permissions. The services bind
> only to loopback and must not be exposed to a network or untrusted users.

To replace the general-purpose behavior with a domain-specific workflow, see
[Specializing General Agent](docs/SPECIALIZING_GENERAL_AGENT.md).

## Quick start

Requirements: macOS or Linux, Python 3.11+, [`uv`](https://docs.astral.sh/uv/),
Node.js/npm for DOCX and PPTX creation, and credentials for a LangChain chat
model that supports tool calling. LibreOffice and Poppler enable Office/PDF
rendering and formula recalculation. Tesseract is optional for scanned-PDF OCR.

```bash
cd general-agent
cp .env.example .env
# Set MODEL_NAME and the provider credential in .env.
./scripts/start.sh
```

Open <http://127.0.0.1:8502>. The API documentation is available locally at
<http://127.0.0.1:8001/docs>.

The launcher validates `uv`, `.env`, model configuration, loopback binding,
writable data directories, free ports, dependency lock synchronization, API
health, and the single-worker process model. `Ctrl-C` stops both services.

## What it includes

- A named `general-agent` graph built with `init_chat_model` and DeepAgents 0.7.
- An additive harness profile that gives the auto-created `general-purpose`
  subagent General Agent's prompt and description without discarding built-in
  model-specific profile behavior.
- DeepAgents filesystem, execution, planning/todo, and configured subagent tools.
- Explicit model, tool, `task`, and provider-reported token limits.
- Run-scoped process-group cancellation for shell commands.
- Non-streaming model calls (`streaming=False`) observed exclusively through
  `astream_events(version="v3")`, with exact tool inputs and outputs, plans,
  delegation lifecycle, and per-agent token usage. The final answer appears
  after the run completes; reasoning and model text deltas are not exposed.
- Chat and run persistence in a local application SQLite database, with a
  separate LangGraph checkpoint database.
- Collision-safe message attachments, chat-scoped working directories, and an
  explicitly persistent shared workspace.
- Progressive `pdf`, `docx`, `pptx`, and `xlsx` skills for reading, creation,
  editing, and verification, including OOXML validation, presentation rendering,
  spreadsheet recalculation, PDF forms, and bounded PDF extraction. Generic file
  reads reject binary documents; scanned-PDF OCR is used only when a local OCR
  engine is available. DeepAgents discovers skills generically from their
  metadata under `/skills`, so adding a skill does not require a system-prompt
  catalog change.
- Immutable snapshots of created, modified, and deleted files for each turn.
- A wide, single-current-chat Streamlit UI matching the data analytics agent,
  with an event activity panel, visible command/code execution, live todos,
  Stop, compact conversation/run diagnostics, and file downloads. There is no
  conversation picker; **New chat** replaces the one chat shown in the browser.

The v1 application intentionally has no built-in web search, webpage reader,
Microsoft 365, email, calendar, image understanding, audio understanding, or
conversation export. OCR is a local optional dependency, not a hosted tool.

## Storage and file behavior

| Location | Purpose | Visible in workspace browser |
| --- | --- | --- |
| `workspace/users/<opaque-id>/chats/<chat-id>/` | Uploads and generated live files for one user/chat | Current chat |
| `workspace/users/<opaque-id>/shared/` | Files that user retained across their chats | Shared view |
| `workspace/users/<opaque-id>/.packages/` | That user's agent-installed Python packages | No |
| `workspace/users/<opaque-id>/.tmp/` | Bounded extraction and command temporary files | No |
| `workspace/.app/skills/` | Application-managed read-only agent skills | No |
| `.data/application.sqlite3` | Chats, runs, events, usage, and file records | No |
| `.data/checkpoints.sqlite3` | LangGraph checkpoints | No |
| `.data/users/<opaque-id>/attachments/` | Immutable original uploads | No |
| `.data/users/<opaque-id>/artifacts/` | Immutable per-turn file versions | No |

The current chat ID is kept in the local URL so a refresh restores the same
chat. For the agent, `/` is the current chat directory, `/shared` is the
user's cross-chat area, and `/skills` contains application-managed workflows.
There is no shared memory file. Shell commands also start in the current chat
directory. Starting a new chat does not delete earlier database records or
files. Use **Keep in shared** to promote a chat
file, or **Clean up chat files** to remove one chat's live directory after a
confirmation; immutable artifact versions remain available from completed
turns.

On the first v3 startup, existing data is assigned to `A123456` (or
`DEFAULT_CORP_ID`) and moved beneath its opaque storage directory without
changing file bytes. Corp IDs are persisted on conversations, turns, runs,
events, usage, attachments, artifacts, snapshots, and checkpoints. The UI sends
its `st.session_state.corp_id` as `X-Corp-ID` on every request and shows the
current user in the sidebar. This is namespacing, not authentication: the
default is intentionally fixed and hidden from editing while identity setup is
deferred.

When the user explicitly authorizes installing an extra Python dependency, the
agent's prompt requires:

```bash
python -m pip install --target "$GENERAL_AGENT_PACKAGE_DIR" PACKAGE_NAME
```

The application virtual environment should never be modified by agent code.
Authorized missing Node dependencies are similarly isolated per user:

```bash
npm install --prefix "$GENERAL_AGENT_NODE_PACKAGE_DIR" PACKAGE_NAME
```

## Configuration

`MODEL_NAME` is required and passed directly to LangChain's
`init_chat_model`. `MODEL_KWARGS_JSON` must be a JSON object. Provider packages
and credentials must match the configured model. OpenAI models default to the
Responses API so reasoning models can use function tools; an explicit
`use_responses_api` value in `MODEL_KWARGS_JSON` still takes precedence.

Programmatic callers may instead pass a prebuilt LangChain `BaseChatModel` to
`build_agent(model=...)`, including an `AzureChatOpenAI` or, when
`langchain-aws` is installed, `ChatBedrockConverse` instance. Before graph
construction, General Agent derives the same provider/model key DeepAgents uses
and additively registers its harness profile. `harness_profile_key` can select
the model's exact or provider-wide key, but it must be one DeepAgents can derive
from that model. A custom integration therefore needs reliable LangSmith
provider metadata or a provider-qualified model identifier.

| Variable | Default |
| --- | ---: |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8001` |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8502` |
| `COMMAND_TIMEOUT_SECONDS` | `120` |
| `RUN_TIMEOUT_SECONDS` | `900` |
| `MAX_COMMAND_OUTPUT_BYTES` | `100000` |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` / `MAX_TASK_CALLS` | `32` / `64` / `12` |
| `MAX_RUN_TOKENS` | `1000000` |
| `MAX_FILE_READ_CHARS` / `MAX_EVENT_OUTPUT_CHARS` | `20000` / `12000` |
| `MAX_UPLOAD_FILES` / `MAX_UPLOAD_MB` | `10` / `100` |
| `MAX_INSPECT_PAGES` / `MAX_INSPECT_SHEETS` | `20` / `20` |
| `MAX_INSPECT_ROWS` / `MAX_INSPECT_COLUMNS` | `50` / `20` |
| `MAX_INSPECT_CHARS` | `50000` |

Only a deliberately small environment is passed to commands: the application
Python path, `.packages`, workspace temp directory, and locale. API keys,
tokens, passwords, and other application environment variables are not
inherited. Configured secret values are also redacted from persisted tool
output and errors. Prompts, responses, commands, and file contents are not sent
to application logs.

Optional LangSmith variables are shown in `.env.example`. Tracing is a provider
feature and may transmit model/tool data; enable it only when that is intended.

## API

The loopback FastAPI service provides:

- `GET /health`
- create/list/read/rename/delete under `/conversations`
- multipart `POST /conversations/{id}/messages`
- cursor polling at `GET /runs/{id}?after_event_id=N`
- cooperative cancellation at `POST /runs/{id}/stop`
- scoped list/upload/inspect/download/rename/delete under `/workspace`
- `POST /workspace/promote` and `DELETE /workspace/chats/{conversation_id}`
- immutable downloads under `/attachments/{id}/download` and
  `/artifacts/{id}/download`

Every request accepts the lightweight `X-Corp-ID` namespace header, defaulting
to `A123456`. All workspace API paths must be relative. Absolute paths,
traversal, hidden or protected paths, and symlinks are rejected. Only one
top-level run may be active per corp ID; another submission for that user
receives HTTP 409 while a different corp ID can run independently.
After a backend restart, abandoned active runs are marked failed and are never
silently resumed. Only completed user/assistant turns enter later model history.

## Development and tests

```bash
uv sync --locked --all-groups
uv run pytest
```

The deterministic suite uses fake model streams and does not require a provider
credential. It covers agent construction, path and symlink rejection, upload
collisions, chat/shared promotion and cleanup, legacy migration, supported file
previews, scanned-PDF reporting, command environment
stripping, timeout/truncation/cancellation, snapshots, persistence, restart
recovery, per-user run concurrency and isolation, v3 event projection, token
attribution, API flows, and Streamlit event reduction.

The provider-backed smoke test is opt-in because it makes a billable model call:

```bash
GENERAL_AGENT_LIVE_TEST=1 uv run pytest -m live tests/test_live_smoke.py
```

Use a compatible configured model because provider credentials and
tool-streaming behavior vary.
