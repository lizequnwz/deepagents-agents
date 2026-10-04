# General Agent usage guide: source-backed content

This file supplies content for the HTML usage guide. It describes the current application, not planned capabilities.

Use the topic IDs as stable navigation targets. Preserve quoted control names and code strings in the HTML guide.

The writing follows selected ASD-STE100 principles: short sentences, active voice, imperative steps, and consistent terms. No formal compliance claim is made.

## 1. Choose a workspace {#choose-workspace}

The navigation contains **General assistant** and **Coding workbench**. General assistant opens by default.

| Choose | Use it for | File behavior |
| --- | --- | --- |
| **General assistant** | Documents, spreadsheets, files, scripts, and general tasks | The agent changes live chat or shared files directly. |
| **Coding workbench** | Repository planning, source review, implementation, and recorded checks | The agent works in a separate source copy. You select files to apply. |

General commands run automatically with your host permissions. Default coding commands also use your host permissions.

Local execution can access host files and the network. The coding review copy is not a sandbox.

The UI records activity. It does not provide a command approval gate for General assistant or direct workbench implementation.

**Evidence:** [Navigation](/Users/charlie/Repos/deepagents-agents/general-agent/streamlit_app.py:8), [general trust notice](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:411), [coding trust notice](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:23).

## 2. Install and start the application {#first-start}

### Prerequisites

Use macOS or Linux with Python 3.11 or later. Install `uv` before setup.

Use a LangChain-compatible model with tool calling. Obtain that provider's credential.

Node.js and npm support document creation and Node project commands. LibreOffice and Poppler support Office/PDF rendering and spreadsheet recalculation.

Tesseract supports optional scanned-PDF OCR. Basic local coding does not require Docker, Chromium, or the TypeScript navigation SDK.

### First start

1. Open a terminal in the `general-agent` directory.
2. Create the local configuration file.

```bash
cp .env.example .env
```

3. Set `MODEL_NAME` in `.env`.
4. Set the credential required by that model provider.
5. Keep `API_HOST` and `APP_HOST` set to `127.0.0.1`.
6. Keep `CODING_RUNTIME=local` for Docker-free coding.
7. Start the application.

```bash
./scripts/start.sh
```

8. Open `http://127.0.0.1:8502` in your browser.
9. Check the **API ready · {model}** badge in General assistant.

The launcher synchronizes locked dependencies, validates configuration, checks ports, and starts one API worker.

The local API reference is `http://127.0.0.1:8001/docs`.

### Stop and restart

1. Select **Stop** or **Stop task** before an intentional shutdown.
2. Wait for the run to stop.
3. Press `Ctrl-C` in the launcher terminal.
4. Run `./scripts/start.sh` to restart.
5. Refresh the browser page.

`Ctrl-C` stops both services started by the launcher. Browser refresh does not restart the API or reload its configuration.

**Evidence:** [Requirements and launch](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:152), [launcher](/Users/charlie/Repos/deepagents-agents/general-agent/scripts/start.sh:7), [configuration template](/Users/charlie/Repos/deepagents-agents/general-agent/.env.example:1).

## 3. Understand the user namespace {#namespace}

The sidebar displays **User {corp_id}**. The default value is `A123456`.

The UI sends this value as `X-Corp-ID`. It selects a local storage namespace.

This value is not authentication. The application is intended for trusted local use.

There is no user selector or sign-in control. General chats, coding projects, and coding sessions use the same configured namespace.

ACP and inline editor settings must use the same corporation ID as the workbench.

Changing `DEFAULT_CORP_ID` selects a different namespace. It does not transfer existing records.

1. Check **User {corp_id}** before opening stored work.
2. Keep both services bound to loopback addresses.
3. Keep the same corporation ID in connected editors.

**Evidence:** [General identity](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:35), [request header](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/api_client.py:25), [namespace caveat](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:235), [coding request scope](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding_api.py:43).

## 4. Start a General assistant task {#general-first-task}

1. Select **General assistant**.
2. Enter your request in **Message General Agent or attach files**.
3. Attach supported files if the task needs them.
4. Submit the message.
5. Inspect the activity panel while the agent works.
6. Read the final answer after the run finishes.
7. Open **Files from this turn** for generated file versions.

The composer is hidden while a run is active. **New chat** is also disabled during that run.

The activity panel shows plans, tools, commands, outputs, and delegation. The final answer appears after completion.

The UI does not show private model reasoning or live answer text. Activity polling is not a pre-execution permission request.

On an empty chat, example choices fill the composer. They do not submit the task.

The example labels are **Build a Python utility**, **Draft a document**, **Analyze a spreadsheet**, and **Plan a complex task**.

### Example: create and test a utility

```text
Create a Python utility that counts rows in a CSV file.
Add clear usage instructions.
Test it with a small sample file.
Save the utility and sample file in this chat workspace.
```

### Example: create a document

```text
Create a project brief as a Word document.
Use the attached notes as the source.
Render the document and inspect the result.
Include the final document in your answer.
```

**Evidence:** [Composer and examples](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:436), [live activity](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:109), [completed turns](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:48), [answer behavior](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:182).

## 5. Upload and inspect General assistant files {#general-files}

### Attach files to a message

1. Open the attachment control in **Message General Agent or attach files**.
2. Select the files.
3. Describe the required result in the message.
4. Submit the message.

Message attachments appear with their original names and sizes. **Download original** retrieves the immutable original upload.

### Upload files without starting a task

1. Select **Current chat** or **Shared** in the sidebar.
2. Open **Add files**.
3. Select files under **Choose workspace files**.
4. Select **Upload**.

**Current chat** contains files for that chat. **Shared** contains files retained across chats in the same namespace.

### Inspect a file

1. Select a folder name to open that folder.
2. Select **Up** to open its parent folder.
3. Select a file name to open **File preview**.
4. Open **Actions** for additional file controls.
5. Select **Preview** to inspect the file.
6. Select **Download** to retrieve its current live version.

Preview extracts bounded text or structured data. It does not display the full rendered Office document or PDF page layout.

A scanned PDF may show **No embedded text** or an OCR warning. Sidebar preview does not perform OCR.

### Supported upload types

The picker accepts these extensions:

```text
pdf docx pptx xls xlsx csv tsv txt md rst json yaml yml toml
py js ts tsx jsx java c cc cpp h hpp go rs rb php sh zsh fish
sql ini cfg xml html css log
```

Images, audio, archives, and arbitrary file types are not accepted by the current upload picker.

Default limits are ten files per upload and 100 MiB per file. Server settings may reduce or increase these limits.

**Evidence:** [Allowed picker types](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:27), [workspace uploads](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:178), [file actions](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:259), [original attachment](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:51), [PDF extraction](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/file_inspector.py:58).

## 6. Keep, rename, and remove live files {#general-file-management}

### Keep a chat file for later chats

1. Select **Current chat**.
2. Open the file's **Actions** menu.
3. Select **Keep in shared** when available.
4. Select **Shared** to inspect the retained file.

### Rename a live workspace entry

1. Open the entry's **Actions** menu.
2. Select **Rename**.
3. Enter **New name**.
4. Select **Rename** in the dialog.

### Delete a live workspace entry

1. Open the entry's **Actions** menu.
2. Select **Delete**.
3. Review the permanent deletion notice.
4. Select **Delete file** to confirm.

### Clean up one chat

1. Wait for the active run to finish.
2. Select **Current chat**.
3. Select **Clean up chat files**.
4. Review the deletion notice.
5. Select **Clean up chat files** in the dialog.

Cleanup removes that chat's live files. Shared files and immutable turn artifacts remain available.

**Evidence:** [Promotion and management controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:302), [delete dialog](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:49), [cleanup dialog](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:57).

## 7. Retrieve versions and return to a chat {#general-history}

**Files from this turn** identifies created, modified, and deleted files. These downloads are immutable turn versions.

Created and modified artifacts contain the captured result. A deleted artifact contains the captured pre-deletion file.

Sidebar **Download** retrieves the live file. Turn **Download** retrieves that turn's version.

There is no automatic restore control for General assistant artifacts. Download a version before using it to restore a live file.

The browser shows one chat at a time. There is no historical chat picker or conversation export control.

### Save a return link

1. Open **Technical details** in the sidebar.
2. Copy **Refresh-safe link**.
3. Save the link before selecting **New chat**.
4. Open the saved link to return to that chat.

**New chat** creates another chat. It does not delete earlier records or files.

**Evidence:** [Immutable artifact controls](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:87), [artifact bytes](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/workspace.py:663), [return link](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:406), [single-chat behavior](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:198).

## 8. Stop and diagnose a General assistant run {#general-stop}

1. Select **Stop** in the active run panel.
2. Wait for the stopped result.
3. Inspect **Files from this turn** for partial file results.
4. Open **How this was produced** to inspect retained activity.
5. Open **Run diagnostics** for usage and timing.
6. Open error **Technical details** when a run fails.

Stopping does not undo prior file writes. A stopped run may have created or changed live files.

**Run diagnostics** shows **Tokens**, **Elapsed**, **Model calls**, **Tool calls**, and **By agent**.

**Conversation diagnostics** summarizes the chat. Token totals may be partial when the provider omits usage.

After an API restart, abandoned active General assistant runs are marked failed. They are not silently resumed.

Only completed user/assistant turns enter later model history. Failed and stopped requests may need to be restated.

**Evidence:** [Stop and diagnostics](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:109), [diagnostic fields](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/components.py:219), [file capture after runs](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/run_manager.py:277), [restart recovery](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/store.py:220).

## 9. Open a repository in Coding workbench {#coding-open}

### Before registration

Save editor buffers before creating a session. The workbench copies files on disk, including eligible existing user changes.

A Git repository is useful but not required. The source copy excludes `.git` metadata.

Choose test and build commands carefully. The current UI cannot edit registered check commands later.

### Register the project

1. Select **Coding workbench**.
2. Open **Open a repository** in the sidebar.
3. Enter **Absolute repository folder**.
4. Enter **Project name**.
5. Enter the intended **Tests command**.
6. Enter **Build command (optional)** if required.
7. Enter approved hostnames in **Documentation websites (optional)** if required.
8. Select **Open project**.
9. Select the project under **Project**.
10. Select **New coding session**.
11. Check the **original:** folder displayed beneath **Coding session**.

Use an absolute, physical folder path. Paths containing symlinks, parent traversal, or the filesystem root are rejected.

The **Tests command** default is `python -m pytest`. Empty test and build fields register no checks.

Documentation entries are comma-separated exact hostnames, such as `docs.python.org`. Do not enter full URLs or wildcard domains.

**Project** selects the project for the next session. **Coding session** independently selects an existing session from the current namespace.

The session list includes sessions from all registered projects. Current session labels are eight-character ID prefixes.

### Copy policy

The copy includes eligible source files and their existing changes. It excludes credentials, application state, links, caches, dependencies, and generated build files.

The UI does not display the full exclusion inventory. The project API record contains onboarding information.

Default source limits are 5,000 files and 50 MiB total. Each source file is limited to five MiB.

General assistant attachments and Shared files do not automatically enter the coding source copy.

**Evidence:** [Repository and session controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:43), [registration policy](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:49), [copy creation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:121), [source limits](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/source.py:116), [project record API](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding_api.py:66).

## 10. Select plan, review, or implement {#coding-modes}

The **Task mode** choices are exactly **plan**, **implement**, and **review**. The default is **plan**.

| Mode | Intended result | Repository behavior |
| --- | --- | --- |
| **plan** | A proposed implementation plan | Reads approved source. Does not edit source or run repository commands. |
| **review** | Findings about existing source | Reads approved source. Does not edit source or run repository commands. |
| **implement** | Source changes and recorded validation | Edits the session copy and can run commands in the selected runtime. |

### Plan before implementation

1. Select **plan** under **Task mode**.
2. Enter the request in **Task**.
3. Select **Start task**.
4. Read the completed plan.
5. Select **Approve plan and implement** to start approved implementation.

Select **Reject plan** to reject that plan. Start another **plan** task to request a revised proposal.

Plan approval is tied to the reviewed source version. Source changes can make an earlier plan stale.

### Review existing source

1. Select **review**.
2. Describe the review scope in **Task**.
3. Select **Start task**.
4. Read the findings.

### Implement directly

1. Select **implement**.
2. Describe the change and required checks in **Task**.
3. Select **Start task**.
4. Inspect the result, checks, and change proposal.

Direct workbench **implement** starts without a separate plan approval. Applying changes to the original remains a separate action.

The workbench has no file-upload control, source tree editor, or interactive terminal. Request source work through **Task**.

### Example: plan

```text
Plan a fix for the CSV parser's handling of quoted newlines.
Inspect the parser and existing tests.
Identify the files to change.
Describe the test cases before implementation.
```

### Example: review

```text
Review the authentication module for logic errors.
Report findings with file paths and line numbers.
Explain the impact and suggest focused fixes.
```

### Example: implement

```text
Fix the CSV parser's handling of quoted newlines.
Add focused regression tests.
Run the approved tests check with run_check.
Report the result and any remaining blockers.
```

**Evidence:** [Mode and task controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:114), [plan actions](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:198), [runtime and read-only backend](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:438), [stale plan rejection](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:858).

## 11. Answer questions, queue follow-ups, and stop {#coding-control}

### Answer a task question

1. Read the question shown for **waiting_input**.
2. Read **Suggested answers** when present.
3. Enter your response under **Your answer**.
4. Select **Answer and resume**.

The answer resumes the same checkpointed attempt with its remaining budgets. Suggested answers are text, not selectable buttons.

Source changes can invalidate a saved question. Start a fresh task if the service reports a stale decision.

### Queue a follow-up

1. Enter a request under **Follow-up instruction** while a task runs.
2. Select **Queue follow-up**.

This creates a linked follow-up attempt. It does not change the command currently running.

### Stop a task

1. Select **Stop task**.
2. Wait for the task to finish stopping.
3. Inspect the retained checks and changes.

Stopping also cleans up attempt-owned preview processes. It does not revert completed source edits or external effects of local commands.

### Continue after failure or Stop

1. Inspect the failed or stopped attempt.
2. Resolve its blocker.
3. Select **Continue as a new attempt** when available.

Continue creates another attempt with the original request and mode. It does not replay the interrupted command automatically.

Dependency setup attempts do not show this Continue control. Use the dependency preparation action again after fixing its blocker.

**Evidence:** [Question, follow-up, and Stop controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:121), [Continue control](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:231), [answer version checks](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:874), [Stop lifecycle](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:334).

## 12. Prepare locked dependencies {#coding-dependencies}

Dependency preparation is an explicit user action. The model cannot request online preparation through a coding tool.

Preparation downloads supported packages from public registries. Installation uses the saved artifact in private session dependency folders.

It does not install packages globally or into the application environment. Local commands still have host network access.

### Supported inputs

| Kind | Required files | Important restrictions |
| --- | --- | --- |
| Python | `requirements.txt` | Exact `==` versions and SHA256 hashes. No includes, URLs, editable dependencies, or pip configuration directives. |
| Python | `pyproject.toml` and `uv.lock` | Static single-project metadata and public PyPI wheels. The lock must pass the offline consistency check. |
| Node | `package.json` and `package-lock.json` | Single project, lock version 2 or 3, public npm URLs, and integrity hashes. |

Python acquisition uses wheels only. It does not build source distributions or install the local project package.

Python lock export includes declared dependency groups. Node preparation suppresses lifecycle scripts and enforces runtime engine compatibility.

Private registries, local packages, workspaces, Git dependencies, and source builds are unsupported by this preparation workflow.

### Prepare a session

1. Check the intended locked files in the original repository.
2. Save those files before creating the coding session.
3. Open **Dependencies**.
4. Review **Locked files** and any blocker text.
5. Select **Prepare python dependencies** or **Prepare node dependencies**.
6. Wait for preparation to finish.
7. Open **Dependency preparation log** on the setup attempt.
8. Check the dependency's **prepared** status.
9. Start the implementation task.

Preparation is bound to manifest and runtime identities. A changed lock or runtime makes the earlier preparation unsuitable.

Existing sessions do not refresh from original files. Create a new session after changing locked files in the original repository.

If an implementation changes session lock files, prepare those current session files before the next implementation attempt.

The UI has no command to install arbitrary missing dependencies. An unsupported package remains an explicit blocker.

**Evidence:** [Dependency controls and identity checks](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:95), [requirements validation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/setup.py:48), [Python lock validation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/setup.py:69), [Node validation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/setup.py:109), [setup submission](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:297).

## 13. Read check evidence {#coding-checks}

Ask the agent to use `run_check` with an approved check name. The UI has no separate **Run checks** button.

The opening form registers `tests` and optional `build`. General shell execution is not recorded as an approved check.

1. Ask the implementation to run the approved named checks.
2. Read the attempt's outcome beside its mode and status.
3. Read each check's phase, status, and exit code.
4. Open **Check log: {name}**.
5. Inspect failures, missing execution, and stale evidence before applying.

| Label | Meaning |
| --- | --- |
| `passed` | The recorded command returned exit code zero on the captured source version. |
| `failed` | The recorded command returned a nonzero exit code. |
| `not_run` | No suitable execution evidence exists. |
| `stale` | Source, environment, or approved command identity changed. |
| `verified` | All approved final checks have current passing evidence. |
| `checks_failed` | A current check or browser observation failed. |
| `not_verified` | Required evidence is absent or stale. |

Baseline checks describe the opening source state. They do not certify the final proposal.

A check that changes source is stale. Run it again after the source reaches its final state.

A screenshot alone cannot produce `verified`. Passing checks are evidence for their recorded commands, not proof of complete correctness.

After apply, session verification is stale for the merged original checkout. Run appropriate checks on that checkout before further delivery.

**Evidence:** [Check UI](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:175), [approved checks](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:628), [check outcomes](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/verification.py:11), [browser outcome rules](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/verification.py:89), [apply invalidation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:932).

## 14. Use preview processes and browser checks {#coding-previews}

Preview processes run in private attempt-owned source copies. Their writes are discarded rather than imported into the review copy.

At most two preview processes can run in an attempt. Their lifetime ends when the attempt stops or finishes.

The UI displays process logs and Stop controls. It has no interactive terminal or hosted preview link.

### Request a process

1. Select **implement**.
2. Request a noninteractive preview command in **Task**.
3. Specify an unused port for a web preview.
4. Require the server to bind explicitly to `127.0.0.1` in local mode.
5. Select **Start task**.
6. Open **Process: {command} · {state}** during execution.
7. Select **Stop process** to stop that process.

Earlier output can be discarded from the bounded log. The UI states when a cursor skipped discarded output.

Completed attempts show **Process log: {command}**. The visible retained output is bounded.

### Request a browser check

1. Check **Browser checks · available** under **Runtime and optional tools**.
2. Request an owned browser preview and specific assertions in **Task**.
3. Specify a relative page path, selector, or expected text.
4. Inspect **Browser: {path} · {status}** after completion.
5. Inspect the screenshot and any failure or stale reason.

Browser requests stay within the owned preview origin. Unrelated servers, occupied ports, and external page requests are rejected.

The listener must belong to the task's process group. A successful response from another local server is not accepted as preview evidence.

Source or dependency changes invalidate a running preview. Ask the agent to stop and recreate it before checking current files.

Screenshots are stored as immutable evidence outside source. They do not appear as repository changes.

### Example

```text
Implement the requested interface change.
Run the approved tests and build checks with run_check.
Start a private browser preview on unused port 8765.
Bind the server to 127.0.0.1.
Check the /settings page for the heading “Settings”.
Capture a screenshot and report browser failures.
```

**Evidence:** [Process and browser UI](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:143), [private copies and limits](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/process_sessions.py:77), [port admission](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/process_sessions.py:135), [stale browser checks](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/process_sessions.py:223), [owned listener](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/local_runtime.py:508).

## 15. Review and apply source changes {#coding-apply}

The completed attempt shows an immutable proposal under **Review changes**. The proposal compares current session source with its accepted baseline.

It can include changes from earlier unapplied attempts. It is not necessarily limited to the most recent task.

The session's initial baseline includes eligible pre-existing user changes. Those changes are not agent changes merely because they were already present.

### Apply selected files

1. Wait for pending session tasks to finish or stop.
2. Open **Review changes**.
3. Read the entire proposal.
4. Inspect check evidence.
5. Choose complete files under **Files to apply**.
6. Keep the original checkout stable during apply.
7. Select **Apply selected files to original**.
8. Inspect the resulting original files.
9. Run appropriate checks on the original checkout.

Selection is by complete file. The current UI does not support hunk selection or diff editing.

Apply validates the reviewed source revision and original-file preimages. Intervening original edits produce a conflict.

Apply uses a recovery journal. It does not promise a single atomic filesystem operation across every file.

Apply does not create a Git commit, push, publish a branch, or deploy the project.

### Reject an unapplied proposal

1. Wait for pending session tasks to finish or stop.
2. Open the current proposal under **Review changes**.
3. Select **Reject change proposal**.

Rejection restores the review copy to its accepted baseline. It discards all unaccepted session changes covered by that baseline comparison.

It does not change the original checkout. Earlier applied changes cannot be rejected through this control.

### Revert a recorded application

1. Wait for pending session tasks to finish or stop.
2. Open the applied proposal.
3. Select **Revert this application** when available.
4. Inspect the original checkout after reversion.

Revert uses the recorded apply journal. It refuses to overwrite later conflicting original edits.

Revert is not a general Git reset or history operation.

**Evidence:** [Review controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:210), [cumulative proposal capture](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:750), [reject baseline checks](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:897), [apply and revert](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:915), [journal implementation](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/changes.py).

## 16. Return after refresh or restart {#coding-recovery}

The coding page stores the selected session ID in the URL's `session` parameter. Refresh restores that selection when available.

The project and session registry persists across API restarts. Session source and immutable evidence are also retained.

Active attempts abandoned by an API restart are marked failed. Their commands are not replayed automatically.

Queued attempts remain queued. Saved questions remain available for an explicit answer.

### Recover interrupted work

1. Restart the application.
2. Select **Coding workbench**.
3. Select the intended **Coding session**.
4. Check the displayed original folder.
5. Read the interrupted attempt's error and retained evidence.
6. Inspect **Review changes** for partial work.
7. Select **Continue as a new attempt** after resolving blockers.

### Start from newer original files

1. Save the intended original files.
2. Select the correct sidebar **Project**.
3. Select **New coding session**.
4. Check the displayed original folder.

An existing session does not automatically import later original edits. Refresh and **Continue as a new attempt** retain that session's source copy.

**Evidence:** [Session URL](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:75), [restart state recovery](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/store.py:110), [new-session snapshot](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:121).

## 17. Enable optional navigation and browser tools {#optional-tools}

Operator setup changes application tooling. It is separate from project dependency preparation.

### TypeScript navigation

1. Open a terminal in the `general-agent` directory.
2. Install the locked app-owned tooling package.

```bash
npm ci --prefix tooling/coding --ignore-scripts --no-audit --no-fund
```

3. Restart the application.
4. Check **JavaScript/TypeScript navigation · available** under **Runtime and optional tools**.

The installed navigation SDK must be TypeScript 5.9.3. The default path is `tooling/coding/node_modules/typescript/lib/typescript.js`.

`CODING_TYPESCRIPT_SDK` can select another absolute path to that exact SDK. Navigation does not load repository plugins or execute source.

Python navigation uses static inspection and does not require this SDK.

### Local browser tooling

1. Install `lsof` through your operating system if absent.
2. Open a terminal in the `general-agent` directory.
3. Install the optional application browser extra.

```bash
uv sync --locked --all-groups --extra browser
```

4. Install Chromium with the application Python.

```bash
.venv/bin/python -m playwright install chromium
```

5. Start the services without removing the browser extra.
6. Check **Browser checks · available** under **Runtime and optional tools**.

macOS normally supplies `lsof`. Linux may require an OS package installation.

The current launcher runs `uv sync --locked --all-groups` without the browser extra. That synchronization can remove Playwright.

Until launcher handling changes, use the following separate terminals after installing the extra.

Terminal 1, from `general-agent`:

```bash
.venv/bin/uvicorn general_agent.api:app --host 127.0.0.1 --port 8001 --workers 1
```

Terminal 2, from `general-agent`:

```bash
.venv/bin/streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

Both commands use the existing application environment. They do not perform another dependency synchronization.

For this manual launch, press `Ctrl-C` in each terminal to stop its service. Use configured loopback ports if different.

These setup commands download packages and browser files. The workbench does not execute them automatically.

**Evidence:** [Optional setup](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:92), [launcher synchronization](/Users/charlie/Repos/deepagents-agents/general-agent/scripts/start.sh:27), [readiness](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/local_runtime.py:223), [manual service commands](/Users/charlie/Repos/deepagents-agents/general-agent/scripts/start.sh:56), [.env loading](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/config.py:263).

## 18. Approve public documentation websites {#documentation}

Documentation fetch tools are available only for approved project domains. Domain-scoped search also requires `BRAVE_SEARCH_API_KEY`.

1. Enter exact hostnames in **Documentation websites (optional)** before selecting **Open project**.
2. Ask the coding agent to consult a page on an approved website.
3. Ask for source URLs when the answer uses retrieved information.

To change approved domains, finish or stop pending project tasks. Reopen the same absolute root with the corrected hostname list.

This registration action updates documentation domains. It does not update an existing project's name or check commands.

Fetch permits public HTTPS and approved-domain redirects. It rejects private addresses, localhost, arbitrary ports, and unapproved websites.

Each attempt permits six fetched pages, two searches, and twelve requests including redirects. Retrieved text cannot authorize code changes or publication.

### Example

```text
Consult the approved docs.python.org page for csv.reader.
Explain the relevant newline handling.
Include the source URL in the plan.
```

**Evidence:** [Domain field](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:52), [domain update behavior](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:177), [fetch rules and limits](/Users/charlie/Repos/deepagents-agents/general-agent/docs/CODING_CONNECTORS.md:12).

## 19. Connect GitHub and publish a reviewed draft PR {#github}

GitHub is optional. Credentials belong in application configuration, never task messages or repository files.

### Operator configuration

1. Create a token restricted to the intended repository and capabilities.
2. Set `GITHUB_TOKENS_JSON` for the intended corporation ID.
3. Restart the application.

Example configuration value:

```dotenv
GITHUB_TOKENS_JSON='{"A123456":"REPLACE_WITH_GITHUB_TOKEN"}'
```

Read permissions support repository, issue, and pull-request inspection. Draft publication also requires content and pull-request write permissions.

Workflow changes may need additional permission. GitHub Enterprise hosts are unsupported.

### Connect the project

1. Open **GitHub** in the coding session.
2. Enter **GitHub owner**.
3. Enter **GitHub repository**.
4. Select **Connect this repository**.
5. Check the connected repository link.

The agent can read issues and pull requests after connection. Issue text does not authorize remote writes.

### Prepare delivery

1. Finish implementation and inspect its checks and proposal.
2. Open **Prepare a draft pull request**.
3. Enter **Pull request title**.
4. Enter **Pull request description**.
5. Enter **Base branch (blank uses the default)** if required.
6. Select **Prepare delivery review**.
7. Open **GitHub delivery: {title} · {status}**.
8. Review the repository, branches, base commit, complete diff, description, and actions.

Preparation creates no remote resource. It freezes the source, verification, remote preimages, and intended actions.

### Publish

1. Keep the reviewed source and remote base stable.
2. Select **Publish this draft PR**.
3. Inspect **Publication receipts**.
4. Select **Open draft pull request** when available.

Publication creates a new commit, `codex/` branch, and draft pull request. It does not merge or overwrite an existing branch.

Publication can trigger repository workflows. Original-checkout apply and GitHub delivery are separate actions.

If publication becomes uncertain, inspect receipts and GitHub before another action. Do not assume that a missing success response means nothing was created.

Binary, linked, oversized, or incomplete proposals cannot use this delivery path.

**Evidence:** [GitHub UI](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/coding_github.py:6), [delivery controls](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/coding_github.py:25), [publication contract](/Users/charlie/Repos/deepagents-agents/general-agent/docs/CODING_CONNECTORS.md:33).

## 20. Enable reviewed Snowflake reads {#snowflake}

The connector supports schema inspection and bounded table reads. It does not provide arbitrary SQL execution or deployment.

### Operator configuration

1. Provision a dedicated read credential and warehouse controls.
2. Set a corporation-scoped `SNOWFLAKE_CONNECTIONS_JSON` profile.
3. Restart the application.

Example configuration value:

```dotenv
SNOWFLAKE_CONNECTIONS_JSON='{"A123456":{"account":"org-account","token":"REPLACE_WITH_BEARER_TOKEN","token_type":"OAUTH","role":"DEV_READER","warehouse":"DEV_WH","database":"APP","schema":"PUBLIC","tables":["APP.PUBLIC.EVENTS"]}}'
```

Supported token types are `OAUTH`, `PROGRAMMATIC_ACCESS_TOKEN`, and operator-provided `KEYPAIR_JWT`. Token refresh and signing are not automatic.

This connector supports `org-account.snowflakecomputing.com` account hosts. Region-qualified, PrivateLink, government, and custom hosts are unsupported.

### Enable for the project

1. Finish or stop pending project tasks.
2. Open **Snowflake reads**.
3. Review the displayed account, role, warehouse, and allowed tables.
4. Select **Enable these Snowflake reads**.
5. Ask the coding agent for a supported schema or rows request.
6. Select **Disable Snowflake reads** when access is no longer required.

The section appears only when the application has a profile for that namespace. Profile changes invalidate the previous approval.

Reads select explicit simple columns from approved tables. Structured equality filters are supported.

Each rows request returns at most 100 rows and selects at most 20 columns. Reads may incur warehouse costs.

There is no fixed monetary cost ceiling. The connector cannot perform joins, procedures, DDL, DML, or table changes.

Interrupted reads are not resubmitted automatically. Inspect retained query receipts if cancellation is unconfirmed.

### Example

```text
Inspect the approved APP.PUBLIC.EVENTS schema.
Read up to ten rows from explicit approved columns.
Explain the result's limits and source.
```

Snowpark, dbt, and Streamlit source work uses the normal coding workflow when available toolchains and locked dependencies support it.

**Evidence:** [Snowflake UI](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:86), [profile, operations, and limits](/Users/charlie/Repos/deepagents-agents/general-agent/docs/CODING_CONNECTORS.md:77), [query receipts route](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding_api.py:102).

## 21. Connect an ACP editor {#acp-editor}

The ACP adapter uses the running loopback application. It shares projects, namespace, queue, runtime, checks, questions, and apply review.

### Configure the editor

1. Start the application.
2. Register the local repository in Coding workbench.
3. Check the registered check commands.
4. Save editor buffers before creating a session.
5. Set the editor's custom agent executable to the application's absolute Python path.
6. Add the adapter arguments below.
7. Set the process working directory to `general-agent`.
8. Set the editor's ACP `cwd` to the exact registered repository root.

Executable:

```text
/absolute/path/to/general-agent/.venv/bin/python
```

Arguments:

```text
-m general_agent.coding.acp
--corp-id A123456
--api-url http://127.0.0.1:8001
```

Use the intended corporation ID. Use an explicit loopback IP address for the API URL.

### Work through ACP

1. Use **Plan** or **Review** for source inspection.
2. Select **Implement** for implementation.
3. Review the plan permission request.
4. Approve the plan to start implementation.
5. Review the resulting exact diff.
6. Approve the separate apply request only when the proposal is ready.

ACP **Implement** presents a plan permission first. Direct web workbench **implement** has no equivalent preliminary permission step.

When the adapter asks a question, answer in the next editor prompt. Cancellation stops the paused task.

The adapter reads saved approved source. It does not use unsaved buffers or editor terminal/filesystem methods.

Binary or incomplete previews require workbench review. Specific editor application compatibility has not been verified.

**Evidence:** [ACP setup](/Users/charlie/Repos/deepagents-agents/general-agent/docs/ACP_EDITOR.md:12), [permissions and question handling](/Users/charlie/Repos/deepagents-agents/general-agent/docs/ACP_EDITOR.md:39), [supported inputs and validation scope](/Users/charlie/Repos/deepagents-agents/general-agent/docs/ACP_EDITOR.md:59).

## 22. Enable optional VS Code inline suggestions {#inline-editor}

Inline suggestions use a separate optional model. They have no tools and do not queue coding tasks.

Accepting a suggestion changes the editor buffer through normal VS Code completion. It does not apply a workbench proposal.

### Operator setup

1. Set the separate inline model configuration in `.env`.
2. Set that provider's required credential.
3. Restart the application.

```dotenv
INLINE_MODEL_NAME=YOUR_PROVIDER:YOUR_INLINE_MODEL
INLINE_MODEL_KWARGS_JSON={}
```

Suggestions can incur provider charges. They are disabled when `INLINE_MODEL_NAME` is empty.

### Development extension setup

1. Register the original repository in Coding workbench.
2. Create a coding session.
3. Copy the full session ID from its URL.
4. Open `editors/vscode` in VS Code.
5. Select **Run → Start Debugging** with the included configuration.
6. Open the registered repository in the extension development window.
7. Trust the workspace.
8. Set the following editor settings.

```json
{
  "generalAgentInline.enabled": true,
  "generalAgentInline.apiUrl": "http://127.0.0.1:8001",
  "generalAgentInline.corpId": "A123456",
  "generalAgentInline.sessionId": "REPLACE_WITH_EXISTING_SESSION_ID"
}
```

9. Request an inline completion in an eligible existing source file.
10. Inspect the offered insertion before accepting it.

The model receives a bounded window around the cursor, not the entire repository. New requests cancel older requests.

Changed buffer versions or session source bindings invalidate pending suggestions. Close and reopen the document after session source changes.

Saving the original file does not refresh session source. Create a new workbench session when the original baseline must change.

Restart clears ephemeral buffer registrations. Reopen or resynchronize documents afterward.

The extension is a development integration. Packaged distribution, real editor latency, and suggestion quality remain separate validation work.

**Evidence:** [Inline configuration](/Users/charlie/Repos/deepagents-agents/general-agent/docs/INLINE_EDITOR.md:11), [extension setup](/Users/charlie/Repos/deepagents-agents/general-agent/docs/INLINE_EDITOR.md:24), [buffer limits and lifecycle](/Users/charlie/Repos/deepagents-agents/general-agent/docs/INLINE_EDITOR.md:51).

## 23. Select the optional Docker runtime {#docker}

The default local workflow does not require Docker. Selecting Docker is an explicit operator choice.

1. Install and start Docker through your normal operator workflow.
2. Build the coding image from `general-agent`.

```bash
docker build -f docker/coding/Dockerfile -t general-agent-coding:local .
```

3. Set `CODING_RUNTIME=docker` in `.env`.
4. Restart the application.
5. Inspect **Runtime and optional tools**.

Docker readiness does not pull an image or install Docker. An unavailable Docker runtime does not switch to local execution.

The configured runtime uses disabled networking, bounded resources, and transferred source. It does not mount the original checkout or host home.

Dependency preparation remains a separate explicit network action. The browser capability requires its separately built browser image.

Actual Docker daemon execution was unavailable during implementation validation. Treat Docker image and daemon validation as an outstanding release gate.

**Evidence:** [Docker setup and validation limit](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:127), [Docker readiness](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/runtime.py).

## 24. Adjust settings and understand limits {#settings}

Settings are environment-backed. There is no general settings editor in the UI.

1. Stop pending tasks before changing runtime or connector settings.
2. Edit `.env` in the application directory.
3. Restart both services.
4. Refresh the browser.
5. Check the relevant readiness or connector display.

Do not edit `.data/`, `workspace/.app/`, or application-managed session files manually.

| Setting | Default | Use |
| --- | --- | --- |
| `MODEL_NAME` | Template: `openai:gpt-6-luna` | Select the tool-capable task model. |
| `MODEL_KWARGS_JSON` | `{}` | Supply model-specific options as a JSON object. |
| `DEFAULT_CORP_ID` | `A123456` | Select the local data namespace. |
| `API_HOST` / `APP_HOST` | `127.0.0.1` | Keep services loopback-only. |
| `API_PORT` / `APP_PORT` | `8001` / `8502` | Select API and UI ports. |
| `API_BASE_URL` | `http://127.0.0.1:8001` | Match the API address used by the UI. |
| `COMMAND_TIMEOUT_SECONDS` | `120` | Bound individual foreground commands. |
| `RUN_TIMEOUT_SECONDS` | `900` | Bound an attempt's runtime. |
| `MAX_COMMAND_OUTPUT_BYTES` | `100000` | Bound retained command output. |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` / `MAX_TASK_CALLS` | `32` / `64` / `12` | Bound model, tool, and delegated calls. |
| `MAX_RUN_TOKENS` | `1000000` | Bound provider-reported usage. |
| `MAX_UPLOAD_FILES` / `MAX_UPLOAD_MB` | `10` / `100` | Bound upload count and per-file size. |
| `MAX_REPOSITORY_FILES` / `MAX_REPOSITORY_MB` | `5000` / `50` | Bound approved source inventories. |
| `MAX_CODING_WORKERS` | `2` | Bound global coding workers. |
| `MAX_CORP_CODING_WORKERS` | `1` | Bound coding workers within one namespace. |
| `CODING_RUNTIME` | `local` | Select local or explicit Docker coding. |
| `CODING_STORAGE_MB` | `512` | Bound dependency artifacts and inventories; also size Docker tmpfs. |
| `CODING_MEMORY_MB` / `CODING_PIDS` | `1024` / `128` | Set Docker container limits. |

Preview defaults limit extraction to 20 pages, 20 sheets, 50 rows, 20 columns, and 50,000 characters.

Provider-reported token limits can be partial or overshoot on an in-flight response. They are not a precise monetary budget.

Local commands have timeout, output, and cancellation bounds. Docker memory and PID settings do not constrain local host processes.

Local disk usage has no container-enforced quota. Source and artifact inventory caps still apply.

The application filters command environments and redacts configured secrets in retained output. This does not prevent local commands from reading host files.

Optional `LANGSMITH_TRACING` can transmit model and tool data. Enable it only when intended.

**Evidence:** [Settings template](/Users/charlie/Repos/deepagents-agents/general-agent/.env.example:16), [limits and trust](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:273), [corporation worker setting](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/config.py:172).

## 25. Resolve common blockers {#troubleshooting}

The following actions use existing controls. They do not require manual database changes.

| Symptom or message | Cause | Action |
| --- | --- | --- |
| `General Agent requires uv` | `uv` is missing from the launcher environment. | Install `uv`, then rerun the launcher. |
| `Missing .env` | The local configuration file does not exist. | Copy `.env.example` to `.env`, then configure the model. |
| `General Agent configuration is invalid` | Model, JSON settings, bounds, or service addresses fail validation. | Correct the reported configuration, then restart. |
| `Port ... is already in use` | Another process owns the configured API or UI port. | Stop your conflicting service or choose unused loopback ports. |
| `Cannot reach API` | The API is stopped or the UI uses another address. | Start the API and check `API_BASE_URL`. |
| Provider authentication error | The selected model lacks a valid provider credential. | Correct its application credential, then restart. |
| Tool or model budget error | The task exhausted its configured budget. | Inspect partial results, then start a narrower task. |
| Truncated output | The retained output cap was reached. | Ask for a shorter summary or a bounded output file. |
| Unsupported upload | The extension is outside the picker allowlist. | Use a supported input format. |
| Upload count or size rejection | The configured upload limit was exceeded. | Reduce the upload count or file size. |
| Scanned PDF preview warning | The document contains no extractable embedded text. | Request OCR only when local OCR tooling is available. |
| `Implementation is unavailable` | Runtime readiness or abandoned-runtime cleanup failed. | Read **Runtime and optional tools** and resolve its reported blocker. |
| Missing command or executable | The selected toolchain cannot run the approved command. | Install the required trusted toolchain through operator setup. |
| Missing project import | Locked dependencies are absent or unsupported. | Inspect **Dependencies** and prepare supported locked packages. |
| Python dependency preparation blocked | Versions, hashes, wheels, metadata, or lock consistency are unsupported. | Correct the supported lock inputs, then prepare again. |
| Node dependency preparation blocked | The lock, registry, integrity, workspace, or engine requirements are unsupported. | Correct supported inputs or select a compatible trusted Node toolchain. |
| Browser not configured | Playwright, Chromium, or `lsof` is unavailable. | Complete optional browser setup without removing its extra. |
| Browser became unavailable after launcher use | Launcher synchronization omitted the optional browser extra. | Reinstall the extra and use the manual two-terminal launch. |
| TypeScript navigation not configured | The exact supported SDK is absent or invalid. | Install the app-owned TypeScript 5.9.3 tooling package. |
| Preview port already in use | The requested host port is occupied. | Request another unused port. |
| Preview stale | Source or installed dependencies changed after preview startup. | Stop the process and request a new preview. |
| `not_verified` | Current approved check evidence is missing or stale. | Request `run_check` for every approved final check. |
| `checks_failed` | A recorded check or browser observation failed. | Inspect logs, fix the cause, then rerun current checks. |
| Apply conflict | Original source changed after the proposal's preimage was captured. | Preserve current edits and create a new session from current source. |
| Stale plan or input decision | The reviewed source version changed. | Start a new task against the current session source. |
| Revert conflict | Original files changed after the recorded application. | Preserve later edits and review a manual reconciliation. |
| Rejected proposal | The review copy returned to its accepted baseline. | Start another task to request new changes. |
| Controls disabled during work | The session has queued, running, stopping, or waiting-input work. | Finish the task, answer its question, or select **Stop task**. |
| Project root rejected | The path is relative, protected, linked, or overlaps another registered root. | Choose an eligible absolute physical repository root. |
| Source inventory exceeded | Eligible files exceed configured count or size bounds. | Reduce eligible source or deliberately adjust operator limits. |
| Existing session lacks saved original edits | Sessions do not refresh from the original checkout. | Select **New coding session** after saving the original files. |
| Project check command was entered incorrectly | Existing project checks have no supported edit control. | Register a separate checkout at a distinct root with correct checks. |
| Approved documentation website is incorrect | The project's exact-domain approval needs revision. | Finish pending work and reopen the same root with corrected domains. |
| Registered root was replaced | The physical root identity differs from its registration. | Use an eligible distinct physical root; same-root identity replacement has no supported update control. |
| GitHub section says configure a token | The namespace has no server-side token. | Configure `GITHUB_TOKENS_JSON`, then restart. |
| Draft delivery rejected | Source, remote preimages, evidence, or delivery limits disagree. | Inspect the conflict and prepare a fresh review after reconciliation. |
| Publication uncertain | The remote mutation's result could not be confirmed. | Inspect **Publication receipts** and GitHub before another action. |
| Snowflake reads absent | The namespace has no configured profile. | Configure `SNOWFLAKE_CONNECTIONS_JSON`, then restart. |
| Snowflake approval invalidated | The configured account profile changed. | Review and enable the current displayed profile. |
| Interrupted Snowflake read | Restart or cancellation left uncertain server completion. | Inspect query receipts and confirm remote status before another read. |
| ACP startup failure | The API, corporation ID, module directory, or registered root is incorrect. | Correct the editor command and start the shared API. |
| Inline suggestions disabled | The application or extension has not enabled suggestions. | Configure the inline model and the extension settings. |
| Inline source binding stale | The session source or document binding changed. | Close and reopen the document, or select a current session. |

There is no supported project-delete or project-settings UI. Do not bypass that limitation by editing application databases.

For an incorrect check, **plan** and **review** remain useful. Command execution cannot substitute another command for the approved check's evidence.

For an apply conflict, leave the conflicting original file intact. A new session captures the latest original baseline without discarding prior evidence.

**Evidence:** [Launcher errors](/Users/charlie/Repos/deepagents-agents/general-agent/scripts/start.sh:7), [API errors](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/ui/api_client.py:28), [runtime readiness](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:25), [unchanged project reuse](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:94), [overlap and reuse](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/store.py:159), [apply conflict handling](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/service.py:915).

## 26. Capability reference {#capabilities}

| Capability | General assistant | Coding workbench |
| --- | --- | --- |
| Planning and delegation | Available through the agent harness. | Available within coding tasks. |
| Host shell commands | Automatic trusted-local execution. | Available in `implement` with the selected runtime. |
| Read-only task modes | No enforceable read-only UI mode. | `plan` and `review`. |
| Documents and spreadsheets | Specialized PDF, DOCX, PPTX, and XLSX workflows. | Source-oriented work; binary documents require specialized inspection. |
| Upload picker | Supported documents, text, and source extensions. | No task attachment picker. |
| Shared files | Explicitly retained across chats. | No automatic import from General assistant Shared files. |
| Immutable file versions | Per-turn created, modified, and deleted artifacts. | Immutable proposals, check evidence, and screenshots. |
| Review before original source writes | No repository apply workflow. | Explicit selected-file apply, reject, and journal-based revert. |
| Source navigation | General file tools. | Python inspection and optional TypeScript/JavaScript compiler navigation. |
| Recorded approved checks | General command output only. | Revision- and runtime-bound `run_check` evidence. |
| Interactive terminal | Unavailable. | Unavailable. |
| Managed preview processes | No workbench process UI. | Noninteractive private previews with bounded logs and Stop. |
| Browser screenshots | No built-in browser workflow. | Optional owned-origin checks and immutable screenshots. |
| Public documentation broker | No built-in web search or webpage reader. | Approved-domain fetch and optional domain-scoped search. |
| GitHub | No dedicated delivery UI. | Optional repository reads and explicitly published draft PRs. |
| Snowflake | No dedicated connector UI. | Optional approved schema and bounded table reads. |
| ACP editor | Unavailable for General chats. | Shared-service adapter with plan and apply permissions. |
| Inline editor suggestions | Unavailable for General chats. | Separate optional model and VS Code development extension. |
| Automatic deployment or merge | Unavailable as a product workflow. | Unavailable as a product workflow. |

The application does not include built-in Microsoft 365, email, calendar, or audio understanding. It does not export General assistant conversations.

Local shell permission is broader than the product's supported workflows. Avoid interpreting that permission as a validated connector or deployment capability.

**Evidence:** [General capabilities and exclusions](/Users/charlie/Repos/deepagents-agents/general-agent/README.md:173), [coding controls](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py), [connector authority](/Users/charlie/Repos/deepagents-agents/general-agent/docs/CODING_CONNECTORS.md), [editor boundaries](/Users/charlie/Repos/deepagents-agents/general-agent/docs/ACP_EDITOR.md:59).

## 27. Editorial audit notes for the HTML report {#editorial-notes}

These notes are for the report author. Keep them separate from normal user instructions.

1. Preserve lowercase `plan`, `implement`, and `review` in workbench control references. ACP mode names use title case.
2. Distinguish **Stop**, **Stop task**, and **Stop process**. They act at different lifecycle scopes.
3. Distinguish live **Download**, immutable turn **Download**, and attachment **Download original**.
4. Show that **Project** and **Coding session** are independent selectors. Verify the displayed original root before every coding task.
5. Do not imply that reopening a root updates check commands or project names.
6. Explain that reopening a root can update documentation domains after pending tasks finish.
7. Do not invent a source editor, task attachments, **Run checks**, or **Run browser** button.
8. Explain that check and browser work is requested through the agent task.
9. Do not describe activity visibility as a command approval step.
10. Show the launcher/browser-extra caveat beside browser setup, not only in troubleshooting.
11. Describe onboarding exclusions without claiming a visible full inventory. README currently overstates their UI presentation.
12. Describe rejection as restoration to the accepted baseline. It can discard changes from several unapplied attempts.
13. Describe apply as journaled selected-file writes. Avoid a multi-file atomicity claim.
14. Describe session verification as stale for the merged original after apply.
15. State that local copies, scoped file tools, and filtered environments do not sandbox host shell commands.
16. Mark Docker, live GitHub/Snowflake mutation, and specific editor compatibility according to their actual validation limits.
17. Keep connector secrets as placeholders in examples. Use quoted JSON values compatible with the launcher's `.env` sourcing.
18. Keep setup commands separate from agent prompts and project dependency preparation.

### Material documentation or product gaps

| Gap | Source evidence | Effect on instructions |
| --- | --- | --- |
| Launcher omits the browser extra. | [scripts/start.sh:27](/Users/charlie/Repos/deepagents-agents/general-agent/scripts/start.sh:27) | Optional browser setup needs an explicit extra-preserving launch. |
| Existing registration reuses checks and name. | [projects.py:94](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:94) | Same-root resubmission is not a check correction workflow. |
| Source replacement message suggests re-registration, but existing identity remains pinned. | [projects.py:69](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:69), [projects.py:92](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:92) | Do not promise same-root re-registration as recovery. |
| Full onboarding inventory is not rendered. | [coding.py:58](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:58), [projects.py:109](/Users/charlie/Repos/deepagents-agents/general-agent/general_agent/coding/projects.py:109) | Explain copy policy and the project API record. |
| General starter copy promises timeline display before execution. | [general.py:446](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:446), [general.py:466](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/general.py:466) | Avoid implying a guaranteed pre-execution review opportunity. |
| No explicit source refresh or project settings controls exist. | [coding.py:43](/Users/charlie/Repos/deepagents-agents/general-agent/app_pages/coding.py:43) | Use a new session for original-file updates; disclose configuration limitations. |

### Recommended HTML topic groups

- **Start:** Choose a workspace, first start, user namespace, settings.
- **General assistant:** First task, files, file management, history, Stop and diagnostics.
- **Coding workbench:** Open repository, modes, task control, dependencies, checks, previews, apply, restart.
- **Optional tools:** Navigation/browser setup, documentation, GitHub, Snowflake, ACP, inline, Docker.
- **Reference:** Troubleshooting, capability table, source evidence.

Place the supplied General assistant and Coding workbench architecture viewers beside their corresponding workflow introductions.

Use example prompts as copyable text. Use setup commands as separate copyable code blocks.

Retain evidence links in a source-details area for every meaningful capability or restriction. Do not expose editorial notes as application controls.
