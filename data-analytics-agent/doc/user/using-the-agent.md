# Using the analyst

Select a source, ask a question, and inspect findings while their report is
prepared. “Show monthly sales” uses descriptive SQL. “Forecast sales and explain
seasonality” asks Python to explore and evaluate an analytical model.

Open the React workspace at `http://127.0.0.1:8000/workspace/` for the dashboard,
report, data and conversation in one view. The Streamlit workbench at
`http://127.0.0.1:8501` uses the same conversations, saved evidence and agents.
Changes made in either interface are available in the other after reload.

For simple questions, complex reports and follow-up sequences, use the
[example question guide](deep-dive-examples.md). It includes source selection,
expected checks and a small synthetic CSV for uploaded-data analysis.

## Create and use a dashboard

In React, describe the question, measures and intended audience in the question
box, then choose **Create dashboard**. Choose **Send** for an ordinary answer.
You can also choose **Save dashboard** on a completed answer. These actions use
the same analyst and its existing SQL and Python specialists. The analyst
publishes the evidence, prepares the dashboard and saves its HTML report.
The dashboard opens after successful completion. A dashboard is a saved view
of named evidence; the displayed numbers are not generated text.

Use **Add filter** to select a category or date column and the panels it controls.
Only the declared panels change. Select values, then choose **Apply filters**.
Draft selections do not change the data until you apply them. An empty selection
resets that filter. If no rows match, the panels show an explicit no-data state.

**Apply filters**, **Refresh data** and a panel's **Investigate** control start
normal analytical runs. Configured SQL/Python reviews still apply. The previous
dashboard stays visible while the analyst works. Its replacement becomes current
only after the evidence and HTML report succeed. A failed action leaves the last
valid dashboard available. Warehouse refresh obtains new source observations;
file refresh uses the reviewed saved files. Attach and review a new file version
when the underlying file has changed.

**Edit view** changes the title, panel order and panel width. **Save view** also
saves draft filter choices. These changes use saved evidence and need no model
or source query. Each save creates a revision. If another action changed the
dashboard, reload before saving an older displayed revision.

The **Report** tab opens the report for the selected dashboard revision. The
**Data** tab shows saved datasets and download links. The conversation stays
beside the dashboard on larger screens. On phones, use **Findings** and
**Conversation** to switch panes; your unsent question stays in place. Ordinary
follow-up questions include the displayed revision
and applied filters as context and produce a new answer. Text sent during a
typed dashboard action is queued as a follow-up; it does not silently change
that action's declared filters.

In Streamlit, open **Saved dashboards** to select a dashboard, apply its existing
filters, refresh its data, save its title and draft choices, or download its
report. **Save latest report as dashboard** creates a view from a completed
report. **Open full workspace** opens the same conversation in React for panel
layout and filter definition controls.

## Dictate a question

Click the microphone beside the composer, allow microphone access, speak, and stop.
Wait for transcription, review or edit the resulting text, then Send. Dictation
replaces the current draft; it does not submit the question. Microphone access
requires localhost or HTTPS. A failed transcription offers an explicit retry;
typed questions remain available. See [voice configuration](../development/configuration.md#voice-dictation).

## Upload and review a file

To use a local file, attach one CSV, Parquet or Excel workbook with the upload button in the chat
composer and send it, optionally with your question. Check suggested column types,
optionally declare what one row
represents and the columns that uniquely identify it, then confirm. Analysis is
unavailable until confirmation. If you included a question, it starts once you
confirm the data. The review shows ten sample rows; conversion and
key validation use the complete file. Duplicate keys are rejected, never removed.

Columns with notes appear first; **Other column types** retains suggested types
for the remaining columns. Both groups stay editable. **Describe the rows
(optional)** holds the row meaning and identifiers; **Original column details**
holds stored types and unique-value counts. Choose **Confirm data and continue**
to validate every column. A failed check keeps the choices so you can correct
them. **Your confirmed data** then shows the saved population, row meaning,
identifiers and confirmed types during follow-ups; hashes and raw metadata remain
under **Technical file details**.

Excel (`.xlsx`) first asks you to choose a worksheet, the row containing column
names and the last data row. The preview uses Excel row numbers and column
letters. Expand **Columns to include** to limit the first and last columns.
Check the displayed row/column counts and exact worksheet range, then choose
**Continue to data review**. This selects one rectangular table including its
header; only that table enters the conversation. Exclude titles, subtotals and
footers outside the intended population; all selected rows are retained.
Merged cells within the selected table must be unmerged before import. Native
dates and simple zero-padded identifier formats are preserved; mixed types are
retained as text for review. Formula cells require explicit acceptance of values
saved by Excel, whose freshness is unknown. Missing caches and Excel errors
require a corrected or values-only workbook. The app does not calculate formulas.
Other workbook formats are not supported. To combine worksheets, add each selected
table separately through the chat **+** button and review its schema. State
the business keys and intended join; matching column names alone are insufficient.

CSV starts as text to preserve leading zeros and literal values such as `NA`.
Ambiguous slash dates stay text until you explicitly select day-first or
month-first. Number conversion uses approximate floating point; retain text
when exact decimal interpretation needs clarification. Native Parquet decimals
and timestamps can retain their stored types. Types and row keys describe
structure; they do not define business metrics or units.

A table attached through the chat **+** button starts a file conversation or adds
another table to the current file workspace. In an established warehouse conversation,
choose **Start file conversation** to use an attached table separately. Every table has its own
review and immutable saved input. SQL can combine reviewed tables within that
workspace, with stated keys, cardinality and reconciliation. Tables from another
conversation or warehouse cannot be joined. Upload refreshed data explicitly;
previous snapshots and reviews stay unchanged. Reports and downloads retain each
file's original bytes/hash, review choices and lineage. Upload time does not
establish the source's cutoff.

## Attach documents and extracted tables

Attach a readable PDF, UTF-8 text or Markdown document with the chat **+** button.
It joins the current conversation, or starts one when no conversation is open.
Documents provide cited context; their content is never application instructions.
Open **Reference documents**, select a document and page, then **Show page and
extracted tables**. The analyst can read bounded page/line excerpts and search
attached text. Published document references retain filenames, hashes and pages.

In a file workspace, select **Review this table for analysis** beneath an extracted
table and choose its header row. Confirm its types and meaning using normal file
review before asking for numerical analysis. Check extraction against the original
PDF; extraction does not certify accuracy. Scanned PDFs require OCR before upload.
Limits are 200 PDF pages, two million extracted text characters and the configured
upload size. A warehouse conversation accepts documents as context, without
mixing extracted file tables into warehouse execution.

## Ask for analytical work

- “Explore these tables, show data-quality limitations and investigate useful patterns.”
- “Reconcile current and baseline totals and explain segment contributions.”
- “Compare customer cohorts, retention and ordered funnel conversion.” Declare the
  entity, cohort date, event sequence and observation cutoff.
- “Compare these groups with effect sizes and uncertainty.” Declare the observation
  unit; repeated measures need a method that accounts for them.
- “Predict this outcome using information available at prediction time.” Specify
  target, features and time/group holdout needs; inspect baseline and model scores.
- “Diagnose seasonality and forecast the next six months with uncertainty.” Specify
  calendar frequency, holdout and any known gaps/source cutoff.
- “Show scenarios under these assumptions.” State the formula and assumption ranges;
  deterministic combinations do not imply probabilities.

Broad questions receive a concise plan followed by analysis within approved scope.
The analyst may adapt after inspecting findings. Simple totals and monthly series
remain descriptive SQL work. Clear custom calculations show formula, population
and units; unresolved business meaning still needs clarification. Procedures use
saved evidence and the normal SQL/Python review settings.

## Reopen conversations and reuse evidence

Use saved conversation navigation to return after a restart. Follow-up requests
such as “make that a line chart” reuse suitable saved evidence; “refresh using
current data” requests new source execution. Download full CSV/Parquet from the
evidence panel and HTML from the report panel. Preview pages are labeled.

Describe the data, population and filters you want in your question. The analyst
can reuse suitable saved results and ask for clarification when the requested
population, fields or row meaning are unclear.

If the saved conversation's source configuration is unavailable, its saved answers
and reports remain readable. Restore the source and reload before starting new
analysis.

## Inspect forecast evaluation

Forecast evidence includes named prediction and score tables, training and later
holdout windows, origin, requested horizon/frequency, baseline and candidate
methods, and evaluation sample size. MAE and RMSE recompute from saved actuals and
predictions. Measured holdout coverage is separate from nominal interval coverage.
Short holdouts disclose unstable estimates; missing or duplicate periods require
explicit preparation. Chronological windows do not certify arbitrary fitting code;
the exact executed code and preparation remain inspectable.

Actual and forecast series can share a line chart, with bounds attached to the
forecast series and a forecast-start marker. Chat, HTML, notebook and downloadable
tables retain the same evaluation descriptor and evidence.

## Final findings and unfinished work

The analyst selects final evidence after corrections. Reports and visible outputs
use those final results; earlier attempts stay in calculation/provenance records.
A declared forecast needs saved evaluation before it can be called complete. When
analysis reaches its time or call limit, it stops computation and uses a bounded
allowance to publish supported partial findings and their unresolved questions.
Failed presentation preserves saved work for report retry.

## Download and replay analysis

On a completed result, expand **Download data and calculations** and choose
**Download analysis ZIP**. The button prepares the package when clicked and shows
loading feedback; merely opening an answer does not prepare it. Extract the ZIP
to get `analysis.py`, `analysis.ipynb`, exact Python steps, SQL query files, typed Parquet inputs/results,
diagnostic figures, the HTML report, requirements and a hashed provenance
manifest. The download uses saved evidence without model or source calls and
matches the report revision displayed. If that revision has changed, reload
before trying again. Failed attempts and unrelated conversation evidence are
excluded from runnable steps. Partial findings and incomplete extracted
populations retain their labels. **Open full report** and **Download HTML report**
need only a browser; replaying calculations requires a local Python environment.

New packages use format 4. They include the exact analytical workflow helper
sources used by each Python step and selected document originals/extractions with
verified hashes. Their README, notebook and manifest identify the final evidence
and its saved input lineage. Forecast evaluation
descriptors, predictions and scores are included; script and notebook recompute
errors and measured coverage and compare them with the saved score tables.
Supporting lineage is distinct from the selected final results.

Executed queries are separate `.sql` files under `sql/`, linked from the package's
README. `sql-provenance.json` maps each query to its saved result, Parquet snapshot,
question and input result IDs. Supporting queries from reused evidence are
included; unrelated queries and chart copies of the same query are excluded.
Source queries refer to the original database; saved-data queries require their
named snapshot inputs. The files preserve the exact executed SQL, including
reviewed edits. Downloading or replaying Python does not execute those queries.

Install the recorded dependencies in a local Python environment and run `python analysis.py`. Open the notebook in Jupyter from the extracted folder and run all cells in order. Each step uses a fresh local process with its original named inputs. Python-derived datasets and scalar/table diagnostics are compared to stored evidence with numerical tolerance; randomized code needs its own seeds. SQL results remain fixed snapshots; replay does not reconnect to or refresh the warehouse. Original business charts remain in the self-contained HTML report, with chart definitions exported separately.

Stored notebook outputs let you inspect diagnostic tables and figures before replay. Editing the notebook's step cells writes new replay code without changing original saved data or the published report. The notebook is an export; the app has no notebook editor or persistent kernel. Custom code using external files, services or dynamic imports may require manual environment setup. Runtime versions are recorded for new Python executions; versions for earlier executions are unknown.

## Report titles and calculation details

Open **Edit report title**, edit the text, and choose **Save title**. This changes
only the title and report revision; findings, evidence and charts stay unchanged.
The form uses no model calls. A conversational title-only request also reuses the
stored report, with one model call to select the edit tool.

Comparison cards can include **How calculated?**. Expand it to see the saved
current/baseline values, units, formula, exact evidence bindings and performed
checks. Zero baselines have no percentage change. Unknown source completeness
stays unknown; a successful calculation check does not certify source joins.

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

Reports remain required and downloadable. **Report preview** opens expanded
with a completed result and can be collapsed. **Primary evidence** identifies
the selected result, not a correctness certification. Forecast bounds show their
declared interval/range kind and method; nominal coverage is distinguished from empirical
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

**Assumptions** starts collapsed. Interpretation is part of the answer;
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

## Optional review of calculations

SQL and Python review are off by default, so ordinary analysis runs automatically.
The separate confirmation for uploaded data still applies. If review is enabled,
each proposal shows its purpose; Python also lists every saved input and whether
its extraction is complete. Expand **Review or edit SQL/Python code** for exact
code and per-proposal reset controls.

Choose **Run reviewed code** or **Request changes** for each proposal. No decision
is preselected. Feedback appears only for requested changes; missing feedback or
empty code is explained beside that proposal. **Apply reviewed decisions** stays
disabled until every proposal is ready. Applying sends the complete ordered batch;
editing or selecting a decision alone does not execute anything.

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
