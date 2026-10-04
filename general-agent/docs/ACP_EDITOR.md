# ACP editor adapter

The adapter exposes the existing coding workbench through the official
[Agent Client Protocol Python SDK](https://github.com/agentclientprotocol/python-sdk).
It connects to the running loopback API; it shares that application's repository
registry, corporation scope, task queue, runtime, budgets, durable questions,
change review, and apply decisions. It does not start another application or
drive a separate DeepAgents graph.

## Launch

Start the application using the operator setup in [README.md](../README.md).
Register the project in the coding workbench under the corporation you intend
to use, and review its approved check commands. Save editor buffers before
creating a session: sessions begin from the registered files on disk.

Configure an ACP client's custom agent command with the project's absolute
Python executable and the following arguments:

```text
/absolute/path/to/general-agent/.venv/bin/python
-m general_agent.coding.acp
--corp-id YOUR_CORPORATION
--api-url http://127.0.0.1:8001
```

Use the General Agent project as the process working directory so Python can
import the application module. The editor's ACP `cwd` must be the exact
registered repository root. The API URL must use an explicit loopback IP
address; the adapter rejects redirects, remote hosts, credentials in the URL,
and ambient proxy configuration. The corporation option is required. Model
credentials belong to the running application, not the editor command.

The process uses standard input/output for ACP. Startup failures and diagnostics
go to standard error. Launch fails if the shared application is unavailable.

## Work in the editor

New sessions start in **Plan**. **Review** also inspects source without changing
files or running repository commands. Select **Implement** to request the full
workflow: the adapter first presents a plan for a single-use permission decision,
then submits approved implementation to the shared queue. Agent changes and
checks run against the isolated session copy.

After implementation, the editor receives the immutable diff and a separate
single-use permission request to apply those exact changes to the original
checkout. Declining or cancelling keeps the proposal in the session. Incomplete
or binary previews require workbench review. The shared service rejects stale
decisions and original-file conflicts; the adapter never retries them with a new
revision. Verification from the session becomes stale for the original checkout
after apply.

When a task needs information, the adapter displays its question and choices,
then ends the current editor turn. Send the answer as the next prompt to resume
that same checkpointed task with its remaining budget. Cancelling stops the
paused task. Loading a session restores pending questions and replays completed
turns from the latest bounded history; failed and stopped work is excluded.

Text and approved local source links are supported. Source links become `/repo`
references to the isolated copy. The adapter does not read unsaved buffers or
call the editor's filesystem or terminal methods. Additional directories,
editor-provided MCP servers, images, audio, embedded resources, authentication,
and inline completion are unsupported.

## Protocol and validation

The locked official SDK is `agent-client-protocol` 0.12.1 and supports ACP
protocol version 1. This adapter uses its session-mode API. The current
[ACP configuration documentation](https://agentclientprotocol.com/protocol/v1/session-config-options)
prefers configuration options, but the installed SDK's agent interface and
router do not yet expose that method; no custom protocol extension is added.
The SDK owns framing, request validation, updates, and permission RPCs.

Provider-free tests cover native SDK request routing, corporation scope, plan
and apply permissions, cancellation, saved-source links, question resume,
history reload, stale decisions, and conflicts. A shared-service test performs
question → plan → approved edit → approved check → immutable diff → approved
apply against a temporary repository. A separate subprocess test uses the
official SDK's stdio transport and a synthetic loopback API. That transport test
requires permission to bind a local test socket when run in a restricted
sandbox. These tests establish the adapter contract; no specific editor
application's compatibility has been verified.

[DeepAgents' ACP integration](https://docs.langchain.com/oss/python/deepagents/acp)
was evaluated. Its graph-driving server owns a separate session/interrupt
lifecycle. This application's SDK adapter instead keeps all execution and
approval decisions in the existing coding service.
