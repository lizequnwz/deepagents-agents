# Coding-agent implementation and release gates

Updated October 4, 2026. The user approved the complete
[reviewed roadmap](CODING_AGENT_REVIEW_AND_PLAN.md) for implementation, step by
step. This implementation run made no commits or remote publication. This ledger distinguishes implemented
contracts from validation that requires optional containers, editors or external services.

**Runtime decision updated October 4, 2026:** The user requested a workbench
without Docker. `CODING_RUNTIME=local` is now the default; explicit `docker`
remains optional. Source copies and reviewed apply protect the editing workflow,
but local execution has the current user's host permissions and is not a sandbox.
Host network access is possible. This supersedes the container-only execution
recommendation in the original review.

## Implemented layers

| Priority | Implemented behavior | Main source and validation |
| --- | --- | --- |
| P0 | Corporation/path/skill boundaries, protected enumeration, shared whole-run call admission, bounded process lifecycle and cancellation | `execution.py`, `workspace.py`, `budgets.py`, `processes.py`; boundary, execution and budget tests |
| P1a | Explicit registered roots, physical identity and overlap checks, dirty source copies, ignore-aware inventory, scoped instruction evidence | `coding/projects.py`, `source.py`, `context.py`; project/source tests |
| P1b | Plan/Review inspection, separate Implement review copy, default trusted-local execution with optional explicit Docker, private locked dependency preparation, baseline/final source-and-environment check evidence | `coding/agent.py`, `backend.py`, `local_runtime.py`, `runtime.py`, `setup.py`, `verification.py`, `evidence.py`; fake-model graph and fixed-controller tests |
| P1c | Immutable versions/diffs, whole-file selection, original-preimage/root checks, journaled apply/revert/reject, accepted baseline advancement | `coding/changes.py`, `service.py`, `app_pages/coding.py`; API, conflict, recovery and Streamlit AppTest workflows |
| P1d | Twelve versioned Python/JavaScript fixtures, private hidden graders, false-verification controls and repeated deterministic trials | `evals/coding/`; contract and grader tests |
| P2 | Bounded public documentation, optional domain-scoped search, Python and compiler-backed JS/TS navigation, private process previews and browser evidence | `coding/documentation.py`, `navigation.py`, `languages.py`, `process_sessions.py`; broker, compiler, process and API tests |
| P3 | Durable SQLite queue, one writer per session, global/corporation resource bounds, kernel scheduler ownership, safe follow-up attempts, version-bound plans and checkpointed questions | `coding/store.py`, `service.py`; persistence, queue, resume, cancellation and source-drift tests |
| P4 | Scoped GitHub reads, immutable exact draft-PR delivery review, single-use publication journal, shared-service ACP editor adapter | `coding/github.py`, `github_service.py`, `acp.py`; mocked remote receipts, native SDK and stdio transport tests |
| P5 | Separate versioned inline suggestions and local VS Code extension, enabled Snowflake schema/table reads, optional Go/Rust/Java image recipe | `coding/inline.py`, `snowflake.py`, `editors/vscode/`, `docker/coding-polyglot/`; buffer, broker and controller contracts |

DeepAgents still owns planning, delegation, progressive skill discovery and
context compaction. The application adds task lifecycle, source ownership,
evidence, runtime control and external-action brokers. General-assistant chat
retains its trusted-host shell and existing document workflows.

## Using the local workflow

1. Start the loopback services as described in [README.md](../README.md).
2. Open a repository in **Coding workbench**. Inspect the included source and
   exclusions, and approve named validation commands and documentation domains.
3. Create a session. Its starting baseline includes eligible existing edits.
4. Run Plan or Review, or select Implement for an already authorized change.
   Approving a plan binds implementation to its immutable source revision.
5. Prepare Python/Node locked dependencies explicitly when needed. Inspect
   preparation logs. Artifacts install into private session dependency folders;
   missing setup is a blocker. Local commands can access the host network.
6. Inspect final checks and source diffs. Answer durable questions as needed;
   Stop captures permitted partial changes and closes owned processes/previews.
7. Apply selected files only after reviewing the exact change. Keep the original
   checkout stable during apply. Conflicting external changes block writes.
8. Connect editor or remote capabilities through their separate configuration
   and review flows. No task completion automatically publishes anything.

Every object remains scoped by corporation. The header is a trusted-local
namespace, not authentication. Keep both services loopback-only.

## Default local runtime

The basic workflow uses `CODING_RUNTIME=local` and does not require Docker,
Playwright, Chromium or the TypeScript SDK. Available local toolchains execute
project commands from the separate session copy with an explicit restricted
environment. Commands run with the local user's filesystem and network
permissions. Working-directory selection, environment filtering and source
validation do not form an OS sandbox. The model is instructed to stay within
the review copy; that instruction cannot enforce host confinement.

Time, output and process-group cancellation bounds remain enforced. Source
snapshot/export file and byte caps remain enforced. Docker CPU/memory/PID/tmpfs
limits do not constrain local processes, and source/storage caps are not host
disk quotas. Keep the services loopback-only and use trusted inputs/operators.

Python/Node dependency preparation runs fixed package-manager commands from a
private manifest-only directory. It rejects source distributions, local/git/
editable/private packages, dynamic metadata and install scripts. Downloaded
artifacts are hashed and tied to lockfile and runtime identities; offline
installation targets private session dependency folders. The application and
global environments are not package installation targets. Package-manager
offline flags do not prevent arbitrary local project commands from using the
host network.

Optional JS/TS navigation uses the app-owned TypeScript 5.9.3 package:

```bash
npm ci --prefix tooling/coding --ignore-scripts --no-audit --no-fund
```

The default SDK path is
`tooling/coding/node_modules/typescript/lib/typescript.js`.
`CODING_TYPESCRIPT_SDK` can select an absolute path to the same exact version.
Missing SDK support is reported by the navigation tools and does not block the
basic coding workflow.

Optional local browser checks require the `lsof` system utility (included on
macOS; install through the OS package manager on Linux) and explicit operator setup:

```bash
uv sync --locked --all-groups --extra browser
uv run python -m playwright install chromium
```

The extra pins Playwright 1.63.0. Browser preview servers use private source
copies, must explicitly bind `127.0.0.1`, and expire with the attempt. Browser
HTTP/WebSocket request guards permit only the owned local origin. Host ports
are used; occupied ports are rejected before preview startup, and browser checks
validate listener ownership against the preview process group. The server and
browser processes retain host permissions. Screenshots
remain immutable evidence rather than a substitute for approved project checks.

## Optional Docker runtime images

Select `CODING_RUNTIME=docker` explicitly. An unavailable configured Docker
runtime is a readiness error; it never falls back to local execution.

The base recipe contains Python 3.11, Node 22, uv 0.11.28 and the pinned
TypeScript 5.9.3 JavaScript compiler API. Builds explicitly acquire public image
and SDK packages; runtime readiness never pulls images. Rebuild older images
after controller changes.

```bash
docker build -f docker/coding/Dockerfile -t general-agent-coding:local .
```

Browser and additional-language recipes extend the exact locally built base.
Resolve its immutable image ID before either build:

```bash
docker image inspect general-agent-coding:local --format '{{.Id}}'
docker build -f docker/coding-browser/Dockerfile \
  --build-arg CODING_BASE_IMAGE=sha256:REPLACE_WITH_IMAGE_ID \
  -t general-agent-coding-browser:local .
docker build -f docker/coding-polyglot/Dockerfile \
  --build-arg CODING_BASE_IMAGE=sha256:REPLACE_WITH_IMAGE_ID \
  -t general-agent-coding-polyglot:local .
```

The browser recipe pins Playwright 1.63.0 and Chromium. Its base identity must
match the selected main coding image; build it from the polyglot image instead
if that is `CODING_IMAGE`. The browser and server run in the same private,
network-disabled preview. HTTP/WebSocket access is restricted to its owned
local origin. No host port is published. Screenshots are immutable PNG evidence.

The polyglot recipe adds Go 1.27.1, Rust 1.98.1 and Java 21.0.12.1 with offline
toolchain/cache settings. Set `CODING_IMAGE=general-agent-coding-polyglot:local`
to select it. Go/Rust/Java dependency acquisition is not implemented: checks can
use standard-library or project-local dependencies supported by the source
policy. The Docker recipe does not provide Maven, Gradle or native macOS/GUI
runners, and toolchains are not downloaded automatically. Local mode can use
available host toolchains. Project-appropriate checks are approved explicitly.

Container construction fixes nonroot ownership, read-only root, no privileges,
no host mounts, no network for commands, and CPU/memory/PID/output/tmpfs bounds.
In Docker mode, preparation alone uses a separate network-enabled helper with validated
manifests and fixed package-controller commands, never project source scripts.
Python accepts exact hash-pinned wheels or eligible `uv.lock` metadata; Node
accepts a public `package-lock.json`. Private registries, local/workspace
packages, lifecycle scripts and online source builds are rejected.

## Navigation limits

Python navigation uses AST and lexical scope analysis; imports, dynamic
dispatch and attribute resolution are approximate or unresolved. It needs
neither Docker nor an optional SDK. JS/TS uses the pinned compiler's LanguageService over at most 200
UTF-8 source files, 256 KiB per file and 2 MiB total. Definitions and references
cover those approved files and fixed SDK libraries. Tools never load project
plugins, run source, install packages, or interpret project configuration.
`tsconfig.json` aliases and package dependency types are therefore unresolved.
Results include resource omissions and a source revision; drift marks them stale.
Plan/Review may invoke the fixed compiler helper in the selected runtime, but
cannot run repository commands or export helper writes. The local helper has
host permissions; Docker containment applies only when Docker is selected.

The snapshot backend deliberately uses the stable TypeScript 5.9.3 JavaScript
API; it does not claim to follow the newest native compiler's API. Lexical and
compiler discovery are the implemented retrieval layers. Semantic/vector
retrieval remains conditional on measured discovery benefit, as specified in
the roadmap; no new embedding service was introduced.

## Evidence and lifecycle

Passing checks certify only the exact source and installed environment they
observed. Source-writing tests, later edits, dependency changes, partial apply
and unrelated original edits invalidate that match. Browser failures also
prevent a verified outcome; a passing screenshot cannot fill a missing check.
Local environment evidence covers the selected Python/uv/Node/npm executables,
operator tool path, application controllers and SDK, private Python imports,
and prepared session dependencies. It does not freeze every host program,
native library or network service that a project command can use.
Baseline failures remain distinct from final checks. Provider-reported tokens
are recorded honestly; missing usage is counted and in-flight provider work can
overshoot the observed token ceiling.

Pending questions persist and resume the same LangGraph checkpoint with
remaining budgets and elapsed active time. Failed/stopped work continues as a
new linked attempt after revalidation. A restart fails abandoned execution and
cleans application-owned runtime resources; it never silently repeats shell work.
Cleanup failures persist and block new runtime work until cleanup succeeds.
Repeated cancellation cannot interrupt final cleanup and immutable history.

GitHub delivery retains intent before each remote mutation and receipts after
it. An uncertain outcome or restart during publication requires review of the
journal and remote state; there is no automatic retry. Snowflake records query
intent and known statement handles before polling, with finite timeout and
best-effort cancellation. Restarted queries are marked interrupted without replay.

Apply uses an application-owned writer lock and no-follow file operations with
root/preimage revalidation. A separate editor does not participate in that lock;
the remaining external-writer filesystem race requires a stable original during
apply. Revert and compensation refuse to overwrite observed newer user changes.

## Validation and remaining release gates

Deterministic tests exercise actual fake-model graphs, temporary repositories,
fixed controller protocols, mocked GitHub/Snowflake HTTP receipts, official ACP
SDK framing and Streamlit AppTest interactions. The TypeScript contract script
also runs against the real pinned SDK. These establish software contracts and
do not establish autonomous task quality or live service compatibility.

The final Docker-free implementation passed **528 deterministic tests**, with
**11 live tests deselected**, in 105.42 seconds on macOS. The suite includes real
local subprocesses, parent-exit cleanup, offline Python wheel and Node package
installation, and the default API edit/check/diff/apply workflow. Separately,
**3 real local tool tests passed** in 15.83 seconds: TypeScript definitions and
diagnostics, a Playwright/Chromium preview screenshot with ownership/staleness/
Stop cleanup, and occupied-port rejection. These used temporary fixtures and
made no provider calls.

Editor HTTP/path tests (3) and the real TypeScript 5.9.3 SDK contract passed.
Both JavaScript syntax checks, the offline lockfile check and tracked/new-source
whitespace checks passed. Four warnings came from the installed
frameworks: Starlette/httpx deprecation, two experimental v3 notices and an
unawaited observer coroutine when model admission is denied. The denied model
and observer do not execute. Exact commands are reported at handoff.
Reproduce with:

```bash
uv sync --locked --all-groups
uv run pytest -m 'not live' -p no:cacheprovider
node --test editors/vscode/test.js
node --check editors/vscode/extension.js
node --check general_agent/coding/typescript_controller.cjs
node tests/typescript_navigation.cjs /absolute/path/to/typescript/lib/typescript.js
uv run python -m evals.coding.runner --trials 3 --output /tmp/coding-contract-results.json
git diff --check
```

The SDK script requires the exact TypeScript 5.9.3 package from the optional
setup above. It never installs packages or executes repository code. The ACP
stdio and local preview tests bind temporary loopback services; restricted
test environments may require permission for those sockets.

After installing the optional local SDK/browser tools, reproduce the real
local checks without Docker or a provider call:

```bash
GENERAL_AGENT_LOCAL_TOOLS_TEST=1 \
  uv run pytest -m live tests/test_coding_local_tools.py -p no:cacheprovider
```

Once Docker and the selected images exist, run the opt-in fixed-fixture smoke
tests without a provider call:

```bash
GENERAL_AGENT_DOCKER_TEST=1 uv run pytest -m live tests/test_coding_container_smoke.py
GENERAL_AGENT_DOCKER_TEST=1 GENERAL_AGENT_BROWSER_TEST=1 \
  uv run pytest -m live tests/test_coding_container_smoke.py
GENERAL_AGENT_DOCKER_TEST=1 GENERAL_AGENT_POLYGLOT_TEST=1 \
  CODING_IMAGE=general-agent-coding-polyglot:local \
  uv run pytest -m live tests/test_coding_container_smoke.py
```

These tests cover real command/source transfer, secret environment exclusion,
read-only root/offline execution, the installed compiler, partial source on
Stop, owner cleanup and a local browser screenshot. They use temporary source
and do not pull/build images. The browser opt-in requires the matching browser
image. The polyglot opt-in adds simple standard-library Go/Rust/Java build and
run checks. Resource exhaustion, daemon interruption and representative project
dependency builds need additional operator validation alongside these smoke tests.

Release gates still requiring an appropriate external environment:

- Extend the macOS local validation to Linux and representative project
  dependency/build workflows. Stop, parent-exit cleanup, private offline
  installation and real SDK/browser fixtures passed on this host. Host
  permissions and network access are intentional; these results do not
  establish OS containment.
- Build and run all selected images with real Docker. Check egress, resource
  exhaustion, source export, partial-change capture, Stop, daemon interruption
  and orphan recovery before advertising validated container support.
- Run the ACP adapter in a real editor and the inline extension in VS Code.
  Check reconnect, pending questions, stale buffers, Unicode cursor positions,
  cancellation and permission review.
- Validate configured public documentation/search, GitHub delivery and
  Snowflake reads against explicitly selected test services and credentials.
  Remote publication and warehouse queries require their intended user actions.
- Run provider-backed task evaluations with an approved model budget. The 12
  controlled fixtures measure application contracts, not autonomous solved-task
  rate, latency targets or Copilot parity. Task specs remain draft pending review.

These gates remain open because additional host platforms, Docker, real editor
applications, external test services and provider-backed task evaluations were
not exercised during this implementation.
