# Local inline editor suggestions

Inline completion is a separate inference path from coding tasks and the
[ACP adapter](ACP_EDITOR.md). It proposes an insertion into a versioned unsaved
editor buffer. It has no tools, cannot change repository files, and does not
queue a coding attempt. Accepting an insertion changes the editor document
through VS Code's normal completion behavior.

## Enable deliberately

Configure the running application with a suitable model and its provider
credentials. Suggestions can incur provider charges:

```dotenv
INLINE_MODEL_NAME=YOUR_PROVIDER:YOUR_INLINE_MODEL
INLINE_MODEL_KWARGS_JSON={}
```

The default is disabled. Inline configuration is separate from `MODEL_NAME`.
The server caps output at 1,024 model tokens and 2,048 insertion characters,
with a five-second inference deadline and a 4,096 provider-reported total-token
limit. Provider output/settings support must be validated for the chosen model.

Register the local repository and create a coding workbench session first.
The extension maps files under that exact root to eligible files in the session.
Existing files must be present in the approved session inventory. Source changes
inside that session invalidate open buffer bindings; close/reopen the document
to bind current source. Saving editor files does not silently import them into
an existing session.

The extension source is [editors/vscode](../editors/vscode/). For a development
host, open that folder in VS Code and use **Run → Start Debugging** with the
included launch configuration. This launches an extension development window.
Open the registered repository there, trust the workspace, then set:

```json
{
  "generalAgentInline.enabled": true,
  "generalAgentInline.apiUrl": "http://127.0.0.1:8001",
  "generalAgentInline.corpId": "A123456",
  "generalAgentInline.sessionId": "REPLACE_WITH_EXISTING_SESSION_ID"
}
```

The project also contains a packaging manifest; distributing a packaged
extension is a separate release action. No VS Code installation or live editor
validation was performed here.

## Buffer and cancellation contract

The extension synchronizes buffer content and its editor version before asking
for a completion. Both cursor offsets and edits use UTF-16, matching VS Code.
The server rejects offsets that split a Unicode character. A changed editor
version, changed source binding or cancelled generation cannot offer a stale
suggestion. New requests cancel older work; cancellation IDs prevent an old
request from cancelling a replacement generation.

The service accepts at most 200,000 UTF-8 bytes per buffer, 128 open buffers
globally and 32 per corporation. Inactive buffers expire after 15 minutes when
the next buffer is opened. Model context includes only the path and up to
6,000 preceding and 2,000 following characters. At most one generation per
corporation and two globally can run; admission is limited to 20 per minute.
Closing documents or the application cancels outstanding work. Restart clears
ephemeral buffers, so reopen/resynchronize them.

HTTP connects directly to an explicit loopback IP with no ambient proxy,
redirect following or remote URL support. Requests have a ten-second deadline
and a two-MiB response bound. Workspace trust and source-policy validation are
required. Model credentials remain in the running application.

`GET /coding/inline/status` reports completed-request counts, offered insertions,
provider usage/missing usage, latency and single-use **editor-reported**
acceptances. Cancelled/timed-out inference is not included in completed-request
statistics. An acceptance callback is not proof that a suggestion was saved,
correct, or retained. No buffer contents are persisted in these metrics.

Provider-free tests cover versions, offsets, cancellation races, source drift,
inference limits, Responses content blocks, scoped API access and client URL/
path boundaries. Real editor latency and suggestion quality remain release gates.
