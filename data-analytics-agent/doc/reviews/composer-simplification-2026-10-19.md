# Composer and attachment simplification

19 October 2026. Removed the Analyze selector and its associated feature at the
user's request, and consolidated uploads into the native chat **+** button.
These changes remain local and uncommitted.

## Resulting behavior

- Application-selected datasets, population filter controls, source-expansion
  permission state and the warehouse-refresh endpoint are removed from the UI,
  API, runtime, reporting and export metadata. No compatibility paths remain.
- Saved datasets, source/conversation isolation, lineage, ordinary report revisions
  and conversational follow-ups remain available.
- All supported data and document formats use the chat attachment button. A table
  joins the current file workspace and receives its own schema review; its question
  waits for confirmation and is submitted once. Excel keeps the same conversation
  target and question through worksheet/range selection.
- Documents join the current file or warehouse conversation. Existing document
  inspection and extracted-table review remain available without another uploader.
- A table attached in an established warehouse conversation offers a separate file
  conversation. Cancelling restores the question draft and leaves the existing
  conversation available.
- The composer keeps stable attachment settings through active work and completion.
  Submitting an attachment during active work gives feedback to finish or stop
  that work first. Text and voice corrections still work.

API/storage contract is **22**. Restart both services together with fresh storage
when upgrading incompatible history, preserving needed older artifacts separately.
Portable bundles retain format **4**, final evidence selections, saved input lineage,
document provenance and exact analytical helper sources.

## Verification

The local suite contains **634 tests**, with six live provider tests deselected.
The full sandboxed run passed 632; two notebook tests failed because Jupyter could
not bind loopback ports. Both passed when rerun with local-port access.

After the stable-composer adjustment, **31 focused tests passed** across chat
workflow, workspace documents, Excel and transcription. Composer identity is
checked through publication, failure and completion. Ruff undefined/unused-symbol
checks and `git diff --check` passed. The removed feature identifiers are absent
from production Python and active evaluation requests.

Checks use synthetic local inputs and mocked/scripted agents. No live provider,
warehouse, browser-layout or human usability study ran.
