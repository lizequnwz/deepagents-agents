# Using the Data Analytics Agent

## Purpose and mental model

The application is a local conversational analytics workspace. A user selects
one ready data source and asks a business question. SQL and statistical Python
either execute immediately or pause for review according to independent
deployment settings. Ordinary data answers automatically attempt one useful
chart over their final evidence.

A conversation is permanently bound to one source. That source determines:

- the OSI semantic model;
- SQL dialect;
- execution backend and target;
- timeout and row limits;
- starter questions and source description.

Changing the selector creates a new conversation. It does not mutate the
source of the existing conversation.

## Start the application

From `data-analytics-agent/`:

```bash
cp .env.example .env
# Choose MODEL_PROVIDER/MODEL_ID and configure OpenAI or AWS credentials.
./scripts/start.sh
```

The launcher synchronizes the locked environment, runs configuration and
source-readiness checks, verifies both ports are available, then supervises
FastAPI and Streamlit.

Open:

- Streamlit: `http://127.0.0.1:8501`
- FastAPI health: `http://127.0.0.1:8000/health`
- Interactive API documentation: `http://127.0.0.1:8000/docs`

Press Ctrl+C in the launcher terminal to stop both processes.

## Select a data source

The sidebar lists only ready sources. A source is ready when its backend target
is usable and its OSI model passes structural and live-schema validation.

The current registry includes:

- Chinook music store
- Financial services

Unavailable sources appear in a separate diagnostic section with warnings and
errors. They cannot be selected.

The selector is disabled while a run or SQL review is active. Finish or
reject the current review before changing source.

## Ask a useful question

Selecting a source example places its full question in the chat input without
submitting it. Edit the wording or add filters, dates, and row-count requirements
before sending.

Good analytical questions specify:

- the business measure;
- the population or filters;
- grouping;
- time range and date interpretation;
- desired ordering and result size.

For example:

```text
Show monthly transaction inflows and outflows for 1998. Use transaction date,
explain how direction is interpreted, and sort chronologically.
```

The agent does not add a SQL `LIMIT` unless the user explicitly requests a row
count. Ranking words such as “top” establish ordering but do not establish a
hidden count. It should state material assumptions rather than silently
guessing.

To require a particular chart, name it explicitly:

```text
Chart monthly inflows and outflows for 1998 as a line chart.
```

The agent normally creates one chart without needing chart words. An explicit
type remains authoritative. If the selected final result is not chart-ready,
the coordinator may make one SQL-reshape recovery attempt.

For statistical inference, ask the business question rather than naming a test
unless you have a firm methodological requirement:

```text
Test whether transaction amounts differ between the two customer segments.
Report effect size, uncertainty, assumptions, and useful diagnostics.
```

The coordinator reuses a clearly suitable untruncated saved result or proposes
analysis-ready SQL first. Statistical methods are not restricted to a fixed
catalog. Ordinary descriptive trends use SQL and the normal chart path; Python
is reserved for uncertainty or modeling. Examples include:

```text
Estimate how customer tenure and segment relate to order value, with adjusted
effects and uncertainty.

Separate the monthly trend and seasonality, then forecast the next three months
with a time-ordered validation and intervals.
```

The specialist loads focused regression or time-series guidance only when the
question needs it. It aims to complete the analysis in one execution, with one
targeted repair available for a genuine code failure.

## Example journeys

### Simple autonomous answer

With `REQUIRE_SQL_APPROVAL=false`, ask for monthly revenue. The coordinator
uses one validated SQL assignment, returns one primary evidence reference, and
automatically selects a time-series chart. The turn exposes the table, CSV,
originating question, and exact executed SQL.

### Multi-query investigation with statistics

Ask what drove a change and whether the observed difference is meaningful. The
coordinator creates todos, gathers baseline, segment, and analysis-ready results
sequentially, reconciles their populations and date windows, then invokes one
statistical analysis when uncertainty materially improves the conclusion. One
final evidence result is charted; intermediate dead ends are not.

### Fully reviewed investigation

Set both approval flags to `true`. Each SQL or Python execution pauses
independently. Approve, edit, or reject the pending step; the same run resumes
with its earlier evidence and remaining execution budgets intact until the
coordinator can synthesize the final multi-result answer.

## Use the automatic HTML report

Every successful data-bearing analysis creates one compact report after the
final evidence, optional statistics, and ordinary automatic chart are complete.
The report uses the same material results as the answer, includes reproducible
SQL automatically, and does not trigger extra analysis merely to decorate the
document. Greetings, brainstorming, clarifications, and failed/no-evidence
turns do not create empty reports.

The normal chart remains visible in the chat result, and the report may reuse
its exact validated `ChartSpec`. The report appears in an isolated preview, can
be opened in a full-page browser view, and is immediately downloadable as the
canonical self-contained HTML file. All three use the same stored bytes.

## Request a tailored report or infographic

Ask for the document you want in ordinary language. You may specify audience,
purpose, style, density, sections, format, or visual direction, or let the
coordinator infer a professional default. For example:

```text
Create a concise editorial infographic for operations leaders using the
analysis so far. Emphasize the three most actionable findings and include the
supporting chart and provenance.
```

```text
Build a detailed statistical analysis report with methods, assumptions,
diagnostics, estimates, uncertainty, interpretation, and the useful output
tables. Use a restrained technical style.
```

The coordinator reuses compatible results, charts, and statistical analyses
from the current conversation. If evidence is missing, it invokes the existing
specialist flow first, including normal SQL or Python review when applicable.
It asks a clarification only when the answer would materially change the
document.

You can open the generated file offline, request feedback-driven revisions in
chat, or ask for further analysis first. There is no mandatory approve or
finalize step. An explicit report turn owns its charts instead of creating a
redundant top-level chart. A report embeds every row only when the requested
presentation needs every row; otherwise it includes only the displayed or
charted evidence.

## SQL execution and optional review

With `REQUIRE_SQL_APPROVAL=false` (the default), SQL is validated once by the
backend and runs immediately. Set it to `true` to pause every `execute_sql`
action. The review panel then shows:

- exact proposed SQL;
- selected source and dialect;
- timeout;
- result-row cap;
- approve/edit/reject controls.

Review joins, filters, metric definitions, date logic, ordering, and row limit.

### Approve

Use **Run this SQL** without changing the editor. The backend validates that
SQL once immediately before executing it.

### Edit

Change the SQL in the editor, then use **Run this SQL**. The edited text becomes
the authoritative query. The backend validates that exact text once immediately
before execution.

### Reject

Provide actionable feedback. Rejection does not complete the run and does not
execute SQL. The text-to-SQL specialist revises its analysis and submits a new
`execute_sql` action, producing another review cycle.

## Statistical Python execution and optional review

With `REQUIRE_PYTHON_APPROVAL=true` (the default), every
`execute_statistical_python` action pauses. Set it to `false` for immediate
bounded execution after validation. In review mode, the panel shows the
complete proposed Python; immutable parent result and
source; originating question and SQL; row count, truncation, columns, profile,
and at most 10 preview rows; and the execution timeout.

The runtime preloads the complete scoped saved result as pandas `df`, with `pd`
and `np` also available. Code must assign a named dictionary to
`analysis_outputs`. It may use pandas, NumPy, SciPy, statsmodels,
scikit-learn, matplotlib, and seaborn to reshape data, handle missingness,
derive fields, fit models, perform tests, and produce compact outputs.

**Run this Python** approves unchanged code or submits the exact editor text as
an authoritative edit. The parent result ID cannot be edited. Reject with
feedback to request a new proposal. Failures return bounded diagnostics and may
receive one targeted repaired proposal and review; at most two actual
executions are permitted.

The POC subprocess has a hard timeout and stripped service secrets, but it is
not a production sandbox: executed code retains local filesystem, process,
import, and network capabilities. Use it only in a trusted local environment.

## Read the result

A completed turn can contain:

- direct answer;
- material assumptions;
- concise interpretation;
- one primary and several supporting evidence tables;
- a CSV download, originating question, and exact executed SQL for each result;
- structured statistical method, assumptions, warnings, interpretation,
  compact outputs, bounded diagnostic figures, and exact executed Python;
- structured activity history with context, skill, agent, and tool lifecycle;
- expandable curated tool arguments;
- bounded debug tool inputs, tool results, and agent state when trusted-local
  debug mode is enabled;
- an automatic downloadable HTML report for every successful evidence-backed
  analysis when reporting is enabled.

The activity API is append-only. Tool start, completion, and failure events
share a call ID, and Streamlit consolidates those events into one progress
step. Repeated calls remain visible instead of being deduplicated. Normal
activity never includes tool outputs, result rows, model reasoning, or full
delegation prompts.

The rotating `logs/api.log` always records bounded,
recognized-secret-key-redacted tool results plus tool completion/failure
metadata. With `AGENT_DEBUG_DETAILS=true`, each tool step also exposes its
bounded raw input and result in Streamlit, and the log additionally records
tool starts and bounded inputs. Each active run and completed turn also
contains the latest state snapshot for the coordinator and each observed
specialist. Snapshots include
bounded messages and ordinary state fields, but replace memory contents with
path/size metadata and redact recognized secret keys. This mode can still
expose questions, SQL, model text, sampled business data, and unrecognized
secrets; use it only in a trusted local environment.

The full capped result and its eager immutable column profile are stored outside
model context. The SQL specialist, coordinator, and visualization specialist
receive the profile and at most `head(10)` rows. They cannot paginate through
the remaining rows. Streamlit retrieves every stored page for the table and CSV.
When the retrieval cap is reached, the UI states that the table, profile, and
chart describe only the stored prefix of the database result.

## Generate a chart

After the coordinator completes direct or multi-step analysis, the visualization
specialist consumes one selected source/thread-scoped final result. It
cannot execute SQL or generate arbitrary Python. It validates a constrained
`ChartSpec`, then `create_chart` generates it automatically. While the run is
active, the progress panel shows the chart type and a bounded subset of
arguments such as x/y mappings, orientation, or category limit; internal result
IDs and the full tool payload are not shown.

Generated specs support bar (including a constrained bar/line dual axis), line, area,
scatter, pie/donut, histogram, box, heatmap, and simple maps. Business
aggregation remains in validated SQL; only presentation sorting/category limits,
histogram bins, and box-plot quartiles happen in the chart layer.

An explicit chart type is a strict constraint; otherwise the specialist chooses
a supported business-useful type. If the saved result has the
wrong grain or encodings, visualization returns `needs_sql_reshape`; the
coordinator may make one validated SQL recovery attempt against the configured
source tables. The prior result ID identifies evidence; it is never a table that
SQL can query. A second incompatibility or an impossible request returns
`cannot_create` instead of leaving the run open. Category limits require an
explicit meaningful sort and produce a visible “Displaying X of N” warning.

After the visualization result returns to the coordinator, the completed
assistant turn retains its business answer and includes the exact spec. Streamlit
deterministically reconstructs the Plotly figure from the saved result. The
underlying table and CSV remain available in a collapsed expander. Invalid
points are excluded with a visible warning; line/area nulls remain gaps. US ZIP
and city/state marker maps use cached centroid data and report partial location
coverage.

## Conversations and URLs

The `thread_id` query parameter is routing state:

```text
http://127.0.0.1:8501/?thread_id=<conversation-id>
```

Refresh, bookmarks, browser history, and duplicate tabs can restore that
conversation while the API process remains alive. The ID is not an
authorization credential.

Because storage is process-local:

- restarting FastAPI clears conversations, runs, results, and checkpoints;
- an old URL starts a replacement conversation when its thread no longer
  exists;
- this behavior is appropriate for the POC, not for a multi-user deployment.

**New conversation** keeps the selected source and creates a new thread URL.
Changing the source also creates a new thread URL. Previous live conversations
remain restorable through their original URLs until the API restarts.

## API lifecycle

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Model, registry, and aggregate readiness |
| `GET /api/data-sources` | Source metadata, examples, limits, warnings, and readiness |
| `POST /api/conversations` | Create a source-bound conversation |
| `GET /api/conversations/{thread_id}` | Rehydrate turns and active run |
| `POST /api/conversations/{thread_id}/messages` | Queue one run |
| `GET /api/runs/{run_id}` | Poll status, incremental structured activity, and current debug snapshots |
| `POST /api/runs/{run_id}/decisions` | Approve, edit, or reject pending SQL or Python |
| `GET /api/results/{result_id}` | Page through the saved capped result |
| `GET /api/reports/{report_id}/view` | Open the exact stored HTML in a full-page browser view |

Use FastAPI `/docs` for authoritative request and response schemas.

## Invariants

Do not change these casually:

1. A conversation has exactly one immutable `source_id`.
2. An active conversation accepts only one run at a time.
3. SQL and Python approval modes are independent deployment settings.
4. Autonomous execution preserves the same validation, scoping, limits, and
   exact-code provenance as reviewed execution.
5. Every statistical Python execution uses an immutable scoped result ID.
6. Statistical inference never runs on a result marked `truncated`.
7. Every final evidence reference must resolve from the same source and thread;
   completed statistical analysis makes its parent result primary.
8. Full results remain application artifacts, not model messages.
9. Ordinary data answers attempt one validated chart tied to final evidence;
   explicit report turns own their charts through `ReportSpec`.
10. Every successful data-bearing turn creates one report over the same final
    evidence when reporting is enabled.

## Common problems

| Symptom | Likely cause | Action |
| --- | --- | --- |
| No sources are selectable | Every source failed readiness | Inspect unavailable-source errors and `GET /api/data-sources` |
| Source is missing | Its target or OSI model failed validation | Follow [Adding data sources](adding-data-sources.md) |
| API setup incomplete | Missing API key or invalid limits/registry | Inspect `/health` and `.env` |
| Old conversation disappeared | FastAPI restarted | Start a new conversation |
| Selector is disabled | A run or review is active | Complete the current lifecycle |
| Edited SQL is rejected | It is invalid, unsafe, or multiple statements | Submit one read-only SELECT/CTE/set-operation |
| Result ID is unavailable | It belongs to another thread/source or process memory was cleared | Re-run the analysis in the current conversation |
| Second message returns `409` | The conversation already owns an active run | Wait for or resolve the current run |
| Chart request reaches another SQL review | Existing result is not chart-ready | Review the new grouping/query; chart generation then continues automatically |
| Map omits locations | ZIP/city-state values could not all be resolved | Read the coverage warning and correct or simplify the source result |
| Chart feature unavailable | `ENABLE_DATA_VISUALIZATION=false` | Enable it and restart FastAPI |
| Statistical feature unavailable | `ENABLE_STATISTICAL_ANALYSIS=false` | Enable it and restart FastAPI |
| HTML report is missing | Reporting is disabled or report rendering failed after one repair | Check `ENABLE_REPORTING`, expand the report tool activity, and inspect trusted-local debug logs if enabled |
| Statistical result needs SQL reshape | Result is truncated or analytically unsuitable | Review the one allowed analysis-ready SQL recovery query |
| Python proposal fails | Runtime error, timeout, or bounded-output violation | Review one targeted repaired proposal; at most two actual runs are allowed |

## Verification checklist

- Both `/health` and Streamlit health are successful.
- The sidebar lists the expected source and description.
- Changing source creates a different URL.
- New conversation retains the source and creates a different URL.
- Generated SQL is visible before execution when SQL approval is enabled.
- Reject produces a revised review rather than a completed answer.
- Edited SQL shown after completion exactly matches what ran.
- Result, SQL, source, and conversation provenance remain aligned.
- Chartable ordinary data questions invoke visualization once after final
  evidence selection.
- Chart progress identifies the type and selected mappings.
- Generated charts remain tied to the saved result ID.
- Statistical review, when enabled, shows the immutable parent result and complete Python.
- Edited Python shown after completion exactly matches what executed.
- Truncated saved results cannot complete statistical analysis.
- Successful evidence-backed answers include a downloadable HTML report; an
  explicit report request does not add a redundant top-level chart.
