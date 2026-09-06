# Using the analyst

Select a source, ask a question, and inspect findings while their report is
prepared. “Show monthly sales” uses descriptive SQL. “Forecast sales and explain
seasonality” asks Python to explore and evaluate an analytical model.

Use saved conversation navigation to return after a restart. Follow-up requests
such as “make that a line chart” reuse suitable saved evidence; “refresh using
current data” requests new source execution. Download full CSV/Parquet from the
evidence panel and HTML from the report panel. Preview pages are labeled.

For complex work, the analyst can gather several results, execute several Python
steps and ask SQL for more data. The investigation record and artifacts preserve
continuity. No notebook kernel needs to stay alive.

Stop pauses work after execution exits; Resume continues it. You may stop and
send a correction instead. Partial findings say what remains unresolved. Retry
report preserves finished data work. Optional review settings expose exact SQL
or Python edits before execution.

## Delete saved history

Open **Manage history** in the sidebar and click **Delete history**. Choose
**This conversation** (the default) or **All conversations**, then confirm or
cancel. To delete a different conversation, select it in Saved conversations first.
All conversations includes every configured source. Deletion is permanent and
includes saved datasets, Python executions and figures, analyses, charts, reports,
investigation summaries, pending approvals, and graph checkpoints. The app opens
a new empty conversation afterward. Configured sources and source databases remain.

Stop running work and wait until it pauses before deleting its conversation.
Clear all history is refused if any conversation is still running or stopping;
no conversations are deleted in that case.
