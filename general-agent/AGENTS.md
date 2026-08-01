# General Agent Repository Guidance

## Purpose and trust model

- This project is a trusted-local DeepAgents application built with LangChain,
  FastAPI, Streamlit, and SQLite.
- The agent's `execute` tool runs directly on the host with the current user's
  permissions. It is not sandboxed and has no approval step.
- Keep both services loopback-only. Do not weaken the `API_HOST` or `APP_HOST`
  readiness checks or present this application as safe for untrusted users.
- Prompt instructions are behavioral guidance, not a security boundary. Enforce
  isolation, authorization, path validation, and resource limits in code.

## Start here

- `general_agent/agent.py`: model construction, harness profile registration,
  system prompt, middleware, and model/tool/task budgets.
- `general_agent/execution.py`: trusted-host shell, restricted subprocess
  environment, cancellation, output bounds, and virtual/physical path routing.
- `general_agent/workspace.py`: per-corporation chat/shared storage, path and
  symlink defenses, uploads, migration, and immutable artifact snapshots.
- `general_agent/run_manager.py`: run lifecycle, v3 event projection, usage
  accounting, cancellation, and snapshot orchestration.
- `general_agent/store.py`: application persistence and recovery.
- `general_agent/api.py`: loopback API and corporation-scoped request handling.
- `streamlit_app.py` and `general_agent/ui/`: the single-current-chat UI.
- `skills/`: source skills copied into application-managed `workspace/.app/skills/`.
- `README.md`: use it for product behavior, storage layout, API routes, and
  operator setup; do not duplicate that general documentation here.

## Non-negotiable invariants

- Preserve corporation isolation end to end. Every conversation, run, event,
  attachment, artifact, checkpoint, and workspace operation must remain scoped
  by `corp_id`.
- Preserve the distinction between virtual agent paths and host shell paths.
  Built-in file tools use `/uploads`, `/shared`, `/chats`, `/skills`, and `/tmp`;
  shell commands use chat-relative host paths or the `GENERAL_AGENT_*` variables.
- Keep `virtual_mode=True`, traversal and symlink rejection, protected hidden
  paths, read-only installed skills, and binary-document read rejection intact.
- Keep `inherit_env=False`. Do not expose application secrets or the ambient
  host environment to agent-run commands. Add environment variables only when
  they are narrowly required and safe for model-generated shell commands.
- Preserve command timeout, output truncation, process-group cancellation, model
  and tool-call limits, and provider-reported token limits.
- Keep abandoned active runs marked failed after restart. Only completed
  user/assistant turns may enter later model history.
- Preserve immutable per-turn versions of created, modified, and deleted files.
- Do not hand-edit `.data/`, `workspace/.app/`, or other derived runtime state.

## Agent prompt and skills

- `SYSTEM_PROMPT` in `general_agent/agent.py` is the canonical application prompt.
  Keep its authority and workspace policies synchronized with the backend.
- DeepAgents `SkillsMiddleware` owns generic skill discovery from `/skills/`.
  Do not hard-code the current skill catalog in `SYSTEM_PROMPT`; put trigger and
  workflow details in each skill's metadata and `SKILL.md`.
- Keep the custom `execute` and `read_file` descriptions synchronized with the
  trusted-host shell, virtual path model, and binary-document rejection.
- Treat prompt changes as behavior changes. Add or update focused assertions in
  `tests/test_agent.py`; use the opt-in live smoke test only when provider-backed
  behavior must be validated.
- The harness-configured `general-purpose` subagent is intentional. Preserve
  additive profile registration so built-in model tuning is not discarded; do
  not change delegation semantics without updating construction tests and
  user-facing documentation.
- Edit source skills under `skills/`, never the installed copy under
  `workspace/.app/skills/`. `Settings.prepare_directories()` replaces the
  installed tree so retired skills cannot linger.
- Keep skill metadata concise and accurate. Put specialized procedures in the
  relevant `SKILL.md` or referenced files instead of expanding this file.
- For document formats, preserve the required inspect/create/edit/render/verify
  workflows rather than reducing them to generic file reads.

## Development workflow

- Preserve existing user changes and avoid unrelated cleanup or broad refactors.
- Prefer the smallest coherent change that maintains the invariants above.
- Search with `rg`/`rg --files` before introducing new code or abstractions.
- Use Python 3.11+ and absolute imports within `general_agent`.
- Keep settings environment-backed and validated in `general_agent/config.py`.
- Do not install packages globally or mutate the application environment from
  agent-executed work. Project dependency changes belong in `pyproject.toml` and
  `uv.lock`; agent runtime installs remain isolated under the user package roots.
- Do not commit secrets, `.env`, runtime databases, generated artifacts, uploads,
  local caches, or virtual environments.
- Do not commit, push, create a pull request, delete data, or run destructive Git
  commands unless the user explicitly requests that action.

## Setup and validation

From the repository root:

```bash
uv sync --locked --all-groups
uv run pytest
```

- Start with the narrowest relevant test file, then run the full deterministic
  suite before finalizing a cross-cutting change.
- Use `GENERAL_AGENT_LIVE_TEST=1 uv run pytest -m live tests/test_live_smoke.py`
  only when a billable configured model call is intended.
- Agent/model construction: `tests/test_agent.py`.
- Path routing, isolation, and artifacts: `tests/test_workspace.py` and
  `tests/test_execution.py`.
- Persistence, recovery, concurrency, and event projection: `tests/test_store.py`
  and `tests/test_run_manager.py`.
- API behavior: `tests/test_api.py`.
- File inspection: `tests/test_file_inspector.py`.
- Skills and document tooling: `tests/test_skills.py` plus the applicable live
  skill test when environment-dependent behavior changes.
- UI state reduction and helpers: `tests/test_ui_helpers.py`.
- Before handoff, inspect the diff, run `git diff --check`, and report exactly
  which checks ran and any that could not run.

## Review priorities

Review changes in this order:

1. Host-execution safety and unintended network or filesystem access.
2. Cross-corporation data leakage or missing `corp_id` scoping.
3. Path traversal, symlink, hidden-path, or immutable-artifact regressions.
4. Run cancellation, recovery, concurrency, and usage-accounting regressions.
5. Prompt/backend drift, skill routing errors, and unsupported capability claims.
6. API or persisted-schema compatibility and missing focused tests.

## Maintaining this file

- Keep this file under 200 lines and limited to durable, non-obvious guidance.
- Add a rule after repeated agent mistakes or recurring review feedback, not for
  one-off tasks.
- Do not restate formatting rules already enforced by tools, paste full workflows
  that belong in skills, or add bare references without saying when to read them.
- Update or remove instructions when architecture and commands change. Treat this
  file as reviewed source, not untouched output from an initialization command.
