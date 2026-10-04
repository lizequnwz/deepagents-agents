# General Agent

General Agent is a trusted-local assistant built with DeepAgents,
LangChain, FastAPI, and Streamlit. It can plan, delegate to its configured
`general-purpose` subagent, inspect common document formats, manage isolated
chat files and explicitly shared files,
run Python or shell commands, and preserve downloadable versions of every file
changed by a turn.

> [!CAUTION]
> The **General assistant** and default **Coding workbench** execute commands
> automatically with the current local user's host permissions. They are
> **not sandboxed** and commands can access the host network and filesystem.
> Coding uses a separate source copy and reviewed application of changes;
> those controls do not contain arbitrary host shell commands. Docker is an
> optional explicit runtime, with no automatic switch between runtimes.
> DeepAgents' built-in file tools are virtual-rooted to `workspace/`, but shell
> commands run with the current local user's host permissions. The services bind
> only to loopback and must not be exposed to a network or untrusted users.

To replace the general-purpose behavior with a domain-specific workflow, see
[Specializing General Agent](docs/SPECIALIZING_GENERAL_AGENT.md).

## Local repository coding

Select **Coding workbench** in the sidebar. Open an exact absolute repository
folder, approve named check commands, and create a session. The session begins
with a filtered copy of the current source, including allowed dirty/untracked
files. Opening a project does not edit its original or Git index. Credentials,
links, dependency/build caches and this application's physical runtime storage
are excluded. Onboarding reports exclusions and source limits.

**Plan** and **Review** permit inspection only, including delegated work.
**Implement** edits the copy and runs commands in the selected runtime. Local
execution is the default and requires no Docker. Time, output and cancellation
limits apply; container CPU, memory and process limits do not apply to local
commands. `run_check`
records approved check commands, source revisions, runtime identity and output.
Missing, failing or stale checks cannot become verified from an assistant's
answer. Image reads use DeepAgents' model-capability handling and bounded image
inspection; binary documents retain their document-skill workflows.

Navigation provides Python AST inspection and optional JavaScript/TypeScript
symbols, definitions, references and diagnostics through a pinned SDK. The fixed compiler
reads approved snapshots without running repository code or plugins. Its
bounded snapshot does not load project packages or `tsconfig.json`; the results
state these limits. Python navigation is approximate lexical analysis.

Prepare hash-pinned Python or locked public Node packages in **Dependencies**
before checks that need them. Acquisition uses validated manifests in a private,
source-free helper directory or optional Docker helper. Packages are installed
from saved artifacts into session dependency folders, separate from application
and global environments. Local commands retain host network access even when
package-manager offline flags are set. Baseline checks record existing
failures separately. Questions pause durably; answering resumes the same task
with its remaining budget and source revalidation.

Implement tasks can start private preview processes, read incremental logs,
stop them, and capture browser checks with optional Playwright/Chromium setup. Each
preview expires with its attempt and discards source writes. Screenshots bind
to source and dependency identities and cannot replace approved tests. The
browser request broker permits only the preview's owned local origin. Local
servers must explicitly bind `127.0.0.1`; they use host ports and are not
sandboxed. Docker previews keep the server and browser in the same container
without publishing host ports.

Project-approved public documentation websites enable bounded fetches; an
optional Brave key enables search within those domains. Explicitly connected
GitHub repositories permit issue/PR reads and a separate immutable draft-PR
delivery review. Snowflake profiles permit scoped schema and bounded table
reads after the user enables the displayed account/role/warehouse/table scope.
See [connector setup](docs/CODING_CONNECTORS.md),
[ACP editor tasks](docs/ACP_EDITOR.md), and
[inline editor suggestions](docs/INLINE_EDITOR.md).

Review the immutable diff, including deleted, binary and executable files.
**Apply selected files** checks the original preimages before and during each
write. It preserves unrelated changes and journals recovery copies. Keep the
original checkout stable during apply: a separate editor can still race the
last filesystem check. Observed conflicts block apply/revert/compensation rather
than overwrite a newer edit. Applied-repository verification is marked stale
until the merged original is checked. Applying does not commit, push or publish.
**Reject change proposal** restores an unapplied proposal in the review copy.

Sessions, decisions, changes, checks and event cursors are corporation-scoped.
A durable local queue allows separate session writers within
`MAX_CODING_WORKERS`; one writer owns a session. **Continue** creates a linked
new attempt. Executing attempts abandoned by a restart fail; shell side effects
are never replayed automatically. Follow-up instructions queue at the next
writer boundary.

### Optional local navigation and browser tools

Python inspection and the edit/test/review workflow work with the default
`CODING_RUNTIME=local`. Project checks use available local toolchains; missing
tools or locked dependencies are reported as blockers rather than installed
automatically. Standard host toolchains can also run Go, Rust, Java or native
checks, without claiming a prevalidated environment for every project.

To enable the exact TypeScript 5.9.3 navigation SDK, install the app-owned
tooling package explicitly:

```bash
npm ci --prefix tooling/coding --ignore-scripts --no-audit --no-fund
```

The default SDK path is
`tooling/coding/node_modules/typescript/lib/typescript.js`.
`CODING_TYPESCRIPT_SDK` may select another absolute path to that exact SDK.
Navigation does not execute repository code or load repository plugins.

To enable local browser checks, provide the `lsof` system utility (included on
macOS; install through the OS package manager on Linux), then explicitly install
the optional application extra and its Chromium browser:

```bash
uv sync --locked --all-groups --extra browser
uv run python -m playwright install chromium
```

These operator setup commands download packages/browser files. The workbench
does not run them automatically. Browser requests remain limited to the owned
preview origin and validate that its loopback listener belongs to the task's
process group. An already occupied port or unrelated server is rejected. Local
project commands and browser processes still have host permissions.

### Optional Docker runtime

Set `CODING_RUNTIME=docker` to require Docker and a locally built image:

```bash
docker build -f docker/coding/Dockerfile -t general-agent-coding:local .
```

This explicit build downloads the image's Python/Node/uv dependencies. Docker
readiness never pulls an image, installs Docker or falls back to local execution.
The optional runtime uses an immutable
image ID, nonroot execution, a read-only root filesystem, disabled networking,
dropped capabilities, CPU/memory/PID bounds and finite tmpfs storage. It transfers
only bounded, validated session source; it mounts no original checkout, home,
application secrets or Docker socket into the container. Docker engine logs are
disabled and command output is bounded by the controller.

Docker is unavailable in the development environment used for this
implementation. Deterministic runtime/controller tests and fixture-backed API
checks pass; an actual image build, resource/egress checks and daemon recovery
still need validation before claiming Docker-supported execution here. The
implementation and remaining release gates are tracked in
[the implementation ledger](docs/CODING_AGENT_IMPLEMENTATION.md), alongside
[the reviewed roadmap](docs/CODING_AGENT_REVIEW_AND_PLAN.md).

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

The general-assistant workflow has no built-in web search, webpage reader,
Microsoft 365, email, calendar, audio understanding, or
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
| `.data/coding.sqlite3` | Projects, sessions, coding attempts, decisions and events | No |
| `.data/coding/<opaque-id>/<session-id>/` | Review source, private dependencies, immutable versions and apply/reject journals | Coding workbench |
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
| `CODING_RUNTIME` | `local`; optional explicit `docker` |
| `CODING_TYPESCRIPT_SDK` | empty; app-owned `tooling/coding` SDK when installed |
| `CODING_IMAGE` | `general-agent-coding:local`; Docker mode only |
| `CODING_BROWSER_IMAGE` | `general-agent-coding-browser:local` |
| `CODING_MEMORY_MB` / `CODING_PIDS` | `1024` / `128`; container limits in Docker mode |
| `CODING_STORAGE_MB` | `512`; bounded package artifacts/dependency inventories; also Docker tmpfs size |
| `MAX_REPOSITORY_MB` / `MAX_REPOSITORY_FILES` | `50` / `5000` |
| `MAX_CODING_WORKERS` | `2` |
| `BRAVE_SEARCH_API_KEY` | empty; documentation search disabled |
| `GITHUB_TOKENS_JSON` / `SNOWFLAKE_CONNECTIONS_JSON` | `{}`; connectors disabled |
| `INLINE_MODEL_NAME` / `INLINE_MODEL_KWARGS_JSON` | empty / `{}`; suggestions disabled |

Only a deliberately small environment is passed to commands: the application
Python path, `.packages`, workspace temp directory, and locale. API keys,
tokens, passwords, and other application environment variables are not
inherited. Configured secret values are also redacted from persisted tool
output and errors. Prompts, responses, commands, and file contents are not sent
to application logs. This environment filtering does not prevent local commands
from reading host files or opening network connections. Repository inclusion
and artifact caps apply in both runtimes; local disk, CPU, memory and process
usage have no container-enforced quota.

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
- coding readiness at `GET /coding/readiness`
- registered source projects at `/projects` and sessions at `/sessions`
- tasks at `POST /sessions/{id}/tasks` with `plan`, `implement` or `review` mode
- bounded coding status/events at `GET /coding/runs/{id}?after=N&limit=200`
  and stop/follow-up actions at `/coding/runs/{id}/stop` and `/steer`
- immutable changes/checks at `/runs/{id}/changes` and `/runs/{id}/checks`
- diff/version downloads and explicit apply/revert/reject at `/changes/{id}`
- version-bound plan responses at `POST /decisions/{id}/respond`
- durable questions at `/decisions/{id}` and `POST /decisions/{id}/input`
- reviewed dependency setup at `GET/POST /sessions/{id}/setup`
- process/log/stop routes under `/coding/runs/{id}/processes`
- immutable screenshots at `/coding/runs/{id}/browser/{check_id}/image`
- GitHub connection/reads under `/projects/{id}/github`, delivery review at
  `POST /changes/{id}/deliveries`, and explicit `POST /deliveries/{id}/publish`
- Snowflake profile/read routes under `/projects/{id}/snowflake`
- editor context at `/sessions/{id}/editor`, versioned inline documents under
  `/sessions/{id}/documents`, and `/coding/inline/status` statistics

Every request accepts the lightweight `X-Corp-ID` namespace header, defaulting
to `A123456`. This header selects a trusted-local namespace; it is not user
authentication. All workspace API paths must be relative. Absolute paths,
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
