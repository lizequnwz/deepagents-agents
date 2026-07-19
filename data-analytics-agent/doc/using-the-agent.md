# Using the Data Analytics Agent

## Purpose and mental model

The application is a local conversational analytics workspace. A user selects
one ready data source, asks a business question, reviews the generated SQL, and
decides whether it may execute. A chart is generated only after an explicit
visualization request and a separate review of the exact chart specification.

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
# Set OPENAI_API_KEY in .env.
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

The agent defaults simple rankings and lists to five rows unless the user asks
for another size. It should state material assumptions rather than silently
guessing.

To request a chart, say so explicitly:

```text
Chart monthly inflows and outflows for 1998 as a line chart.
```

The agent creates exactly one chart per request. If the current saved result is
not chart-ready, it first proposes a new grouped query for SQL review.

## Review SQL

Every `execute_sql` action pauses before database execution. The review panel
shows:

- exact proposed SQL;
- selected source and dialect;
- timeout;
- result-row cap;
- approve/edit/reject controls.

Review joins, filters, metric definitions, date logic, ordering, and row limit.

### Approve

Use **Run this SQL** without changing the editor. The same SQL is validated
again and executed.

### Edit

Change the SQL in the editor, then use **Run this SQL**. The edited text becomes
the authoritative query. It is parsed and validated before the agent resumes.

### Reject

Provide actionable feedback. Rejection does not complete the run and does not
execute SQL. The text-to-SQL specialist revises its analysis and submits a new
`execute_sql` action, producing another review cycle.

## Read the result

A completed turn can contain:

- direct answer;
- material assumptions;
- concise interpretation;
- result table;
- CSV download;
- exact executed SQL;
- sanitized activity history.

The full capped result is stored outside model context. The model receives only
the configured sample and an opaque result ID. This keeps large data artifacts
out of the prompt/checkpoint while allowing the UI to retrieve the table.

## Generate a chart

The visualization specialist consumes one source/thread-scoped saved result. It
cannot execute SQL or generate arbitrary Python. It validates a constrained
`ChartSpec`, then `create_chart` generates it automatically. While the run is
active, the progress panel shows the chart type and a bounded subset of
arguments such as x/y mappings, orientation, or category limit; internal result
IDs and the full tool payload are not shown.

Generated specs support bar, line, area,
scatter, pie/donut, histogram, box, heatmap, and simple maps. Business
aggregation remains in reviewed SQL; only presentation sorting/category limits,
histogram bins, and box-plot quartiles happen in the chart layer.

After the visualization result returns to the coordinator, the completed
assistant turn includes a chart-success message and the exact spec. Streamlit
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
| `GET /api/runs/{run_id}` | Poll state and incremental activity |
| `POST /api/runs/{run_id}/decisions` | Approve, edit, or reject pending SQL |
| `GET /api/results/{result_id}` | Page through the saved capped result |

Use FastAPI `/docs` for authoritative request and response schemas.

## Invariants

Do not change these casually:

1. A conversation has exactly one immutable `source_id`.
2. An active conversation accepts only one run at a time.
3. Every SQL execution requires an interrupt decision.
4. The backend executes the exact reviewed SQL.
5. Final executable answers must reference a result from the same source and
   thread.
6. Full results remain application artifacts, not model messages.
7. Visualization occurs only on explicit request and produces one validated
   chart tied to one saved result.

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

## Verification checklist

- Both `/health` and Streamlit health are successful.
- The sidebar lists the expected source and description.
- Changing source creates a different URL.
- New conversation retains the source and creates a different URL.
- Generated SQL is visible before execution.
- Reject produces a revised review rather than a completed answer.
- Edited SQL shown after completion exactly matches what ran.
- Result, SQL, source, and conversation provenance remain aligned.
- Non-chart questions do not invoke visualization.
- Chart progress identifies the type and selected mappings.
- Generated charts remain tied to the saved result ID.
