# Using the analyst

Select a source, ask a question, and inspect findings while their report is
prepared. “Show monthly sales” uses descriptive SQL. “Forecast sales and explain
seasonality” asks Python to explore and evaluate an analytical model.

For copy-ready investigations and checks, use the
[deep-dive test questions](deep-dive-examples.md), including a small synthetic CSV
for testing uploads, parallel analysis, and reports.

## Upload and review a file

To use a local file, attach one CSV or Parquet with the upload button in the chat
composer and send it, optionally with your question. Check suggested column types,
optionally declare what one row
represents and the columns that uniquely identify it, then confirm. Analysis is
unavailable until confirmation. If you included a question, it starts once you
confirm the schema. The review shows ten sample rows; conversion and
key validation use the complete file. Duplicate keys are rejected, never removed.

CSV starts as text to preserve leading zeros and literal values such as `NA`.
Ambiguous slash dates stay text until you explicitly select day-first or
month-first. Number conversion uses approximate floating point; retain text
when exact decimal interpretation needs clarification. Native Parquet decimals
and timestamps can retain their stored types. Types and row keys describe
structure; they do not define business metrics or units.

Each file belongs to one separate conversation. It cannot be joined with another
conversation or warehouse. Upload a new file to refresh or change a confirmed
schema. The app preserves original bytes, a file hash, the reviewed snapshot and
derived lineage. Reports include the file identity and review choices. Upload
time does not establish when the source data was last updated.

## Reopen conversations and reuse evidence

Use saved conversation navigation to return after a restart. Follow-up requests
such as “make that a line chart” reuse suitable saved evidence; “refresh using
current data” requests new source execution. Download full CSV/Parquet from the
evidence panel and HTML from the report panel. Preview pages are labeled.

## Edit charts and open reports

On a completed result, open **Edit chart** to adjust the title, axis labels,
colors, or chart type, then choose **Save chart and report**. These controls use
the existing saved data without a model or warehouse call. Unsupported chart
types explain the constraint. Downsampled charts retain their type; ask for a
new chart over the complete saved evidence when a different type is needed.

The chart and report update together. A rendering failure leaves the last
successful pair displayed; save the same edit again to retry. If another edit
has already changed the report, reload before editing. Reopening a conversation
restores its latest successful presentation. Original chart/report versions and
the original analytical turn remain saved. Finish active work before editing.

Reports remain required and downloadable, with **Report preview** collapsed
until opened. **Primary evidence** identifies the selected result, not a
correctness certification. Forecast bounds show their declared interval/range
kind and method; nominal coverage is explicitly distinguished from empirical
coverage measured on held-out observations.

## Follow work and inspect evidence

For complex work, the analyst can gather several results, execute several Python
steps and ask SQL for more data. The investigation record and artifacts preserve
continuity. No notebook kernel needs to stay alive.

The question appears before one assistant activity view. Complex requests show an
**Analysis plan** with pending, in-progress and completed steps. One live status
above the plan describes the current work, elapsed time and simultaneous analyses.
Clarification, review and recovery controls appear directly below that status.
Completed turns collapse their plan behind **View steps**, keeping the answer
prominent; unfinished steps keep their recorded states. Independent saved-data analyses can run together; source retrieval
and dependent analyses remain sequential. The default allows two analysis workers;
set `ANALYSIS_PARALLEL_WORKERS=1` for sequential execution.

Expand **Activity** for exact SQL/Python, bounded inputs/outputs and diagnostics.
Its open state is retained as findings appear and the report is prepared. Each
parallel worker has its own activity identity and, when enabled, its own review.
Approving one proposal leaves the other awaiting review. Approval pauses are
labeled as waiting for input; stopped operations are labeled stopped.

**Assumptions and interpretation** starts collapsed. Open it for analytical context;
partial-result notices, unresolved questions and analysis warnings remain visible.

## Clarify or correct a request

Use the composer during a run to add context or correct the request. “Received”
means the correction is saved; “Applied” means the coordinator has consumed it.
An executing SQL/Python step may finish before the next model boundary delivers
the correction. Its evidence retains the original scope. A correction after
publication is accepted as a separate queued follow-up, with its own run ID.

When clarification is needed, answer the inline business question (free text is
always accepted). This resumes the same investigation. A correction invalidates
an outstanding code proposal, so revised code requires a new review when enabled.

## Stop, resume, and retry

Stop requests cancellation and pauses once execution exits; Resume continues
from saved state. An interrupted step whose output was not saved may run again.
Partial findings say what remains unresolved. HTML reports keep intermediate
analysis outputs in a collapsed inspection section, with labeled ten-row table
previews and visible analytical warnings. Full saved evidence remains in the app.
Retry report preserves finished
data work: it reuses an intact report, rebuilds missing HTML from its saved
specification, or repairs the presentation using published findings. Resume also
uses report recovery once findings are published. A successful retry clears the
old error; retries wait until previous execution has exited. Optional review settings expose exact SQL or Python edits before
execution. Time, call and data limits remain enforced even with review disabled;
see [run controls and defaults](../development/configuration.md#controlling-a-run).

## Delete saved history

Open **Manage history** in the sidebar and click **Delete history**. Choose
**This conversation** (the default) or **All conversations**, then confirm or
cancel. To delete a different conversation, select it in Saved conversations first.
All conversations includes configured sources and uploaded files. Deletion is permanent and
includes saved datasets, Python executions and figures, analyses, charts, reports,
investigation summaries, pending approvals, original uploaded files and reviews,
and graph checkpoints. The app opens
a new empty conversation afterward. Configured sources and source databases remain.

Stop running work and wait until it pauses before deleting its conversation.
Clear all history is refused if any conversation is still running or stopping;
no conversations are deleted in that case.
