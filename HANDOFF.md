# Project handoff: Chinook Deep-Agent text-to-SQL POC

Last updated: 2026-07-18

## Executive summary

The main deliverable is in [`data-analyst-agent/`](data-analyst-agent/). It is a
localhost proof of concept for conversational analytics over Chinook SQLite:

- FastAPI owns conversations, runs, approval state, and result artifacts.
- A Deep Agent coordinator delegates database questions to one isolated
  `text-to-sql` subagent through the built-in `task` tool.
- The specialist reads an OSI `0.1.1` semantic model before writing SQL.
- Every `execute_sql` call pauses for human approval, editing, or rejection.
- SQL is executed through deterministic read-only safeguards.
- Streamlit provides a refresh-safe chat and SQL-review interface.
- A Jupyter notebook explains the implementation step by step.

The POC is functional and tested, but deliberately process-local and
single-user. It is not production-ready without persistence, authentication,
authorization, and stronger deterministic SQL/schema validation.

## Requirements and decisions captured during the work

The implementation was shaped by these explicit choices:

- Database: Chinook SQLite for an easy local POC.
- Model provider: OpenAI, configured through `.env`.
- Default model: `gpt-5.4-mini`.
- Interaction: conversational, non-token-streaming UI.
- Agent activity: show sanitized status such as context loading, semantic-model
  inspection, skill loading, planning, schema fallback, SQL checking, approval,
  and execution.
- Agent topology: coordinator plus a custom `text-to-sql` subagent invoked by
  the built-in Deep Agents `task` tool.
- Semantic grounding: read the OSI file first instead of discovering the
  database through repeated SQL attempts.
- SQL review: use LangChain/Deep Agents built-in HITL middleware with
  approve/edit/reject decisions.
- Structured output: provider-native strict Pydantic schemas at the executor,
  specialist, and coordinator boundaries.
- Result handling: retain up to 500 rows in a thread-scoped application
  artifact; expose at most 10 sample rows to either model.
- Answers: include direct answer, exact executed SQL/result ID when applicable,
  material assumptions, and concise interpretation.
- Simple list/ranking questions: default to five rows.
- Persistence: local in-memory state is acceptable for the POC.
- Conversation routing: retain `thread_id` in the Streamlit URL. This supports
  refresh, bookmarks, duplicate tabs, and browser history. The ID is routing
  state, not an authorization secret.
- New conversation: create a new backend thread and update the URL.
- UI direction: restrained analyst workspace, native Streamlit components,
  accessible light/dark themes, minimal motion, and no unnecessary charts or
  multipage navigation.
- Local startup: one foreground Bash launcher should start and supervise both
  FastAPI and Streamlit.

## What has been implemented

### Agent architecture

[`text2sql_agent/agent.py`](data-analyst-agent/text2sql_agent/agent.py)
constructs:

- one coordinator named `chinook-data-analyst`;
- one custom subagent named `text-to-sql`;
- no default general-purpose subagent;
- a shared OpenAI chat model;
- explicit query-writing and schema-exploration skills on the custom subagent;
- filesystem permissions that allow only `AGENTS.md`, `semantic/**`, and
  `skills/**`, followed by catch-all deny rules;
- provider-native `SQLAnalysisResult` and `FinalAnswer` response contracts;
- `InMemorySaver` checkpointing and `AgentContext(thread_id, run_id)`.

The coordinator has only the safe `get_saved_result` tool. Database work is
delegated to the specialist.

The specialist has:

- `sql_db_list_tables`, `sql_db_schema`, and `sql_db_query_checker` as
  fallbacks;
- no toolkit direct-query tool;
- `execute_sql`, protected by approve/edit/reject HITL;
- `get_saved_result` for prior artifacts;
- explicit instructions to use OSI physical `source` and field-expression names
  rather than semantic dataset/field identifiers.

### OSI semantic layer

[`semantic/chinook.osi.yaml`](data-analyst-agent/semantic/chinook.osi.yaml)
uses OSI version `0.1.1` and covers all 11 Chinook tables:

- Artist
- Album
- Employee
- Customer
- Genre
- Invoice
- MediaType
- Track
- InvoiceLine
- Playlist
- PlaylistTrack

It includes fields, primary keys, relationships, synonyms, AI instructions, and
canonical metrics:

- total revenue;
- line revenue;
- units sold;
- invoice count;
- customer count;
- track count.

### Skills and context

- [`AGENTS.md`](data-analyst-agent/AGENTS.md) contains stable operating policy.
- [`skills/query-writing/SKILL.md`](data-analyst-agent/skills/query-writing/SKILL.md)
  contains SQL-writing guidance.
- [`skills/schema-exploration/SKILL.md`](data-analyst-agent/skills/schema-exploration/SKILL.md)
  contains fallback schema-exploration guidance.

Custom Deep Agents subagents do not inherit coordinator skills automatically,
so both skills are assigned explicitly.

### SQL safety

[`text2sql_agent/sql_tools.py`](data-analyst-agent/text2sql_agent/sql_tools.py)
implements defense in depth:

1. SQLGlot parses the SQLite dialect.
2. Exactly one `exp.Query` is allowed.
3. DDL, DML, transactions, commands, `PRAGMA`, `ATTACH`, and similar operations
   are rejected.
4. SQLite is opened with URI `mode=ro`.
5. An SQLite authorizer denies mutation and administrative opcodes.
6. A progress handler enforces the configured deadline.
7. The executor fetches at most 501 rows, returns/stores 500, and reports an
   accurate truncation flag.
8. The exact reviewed SQL is executed without an invisible `LIMIT` rewrite.

### Result artifacts and structured output

[`text2sql_agent/schemas.py`](data-analyst-agent/text2sql_agent/schemas.py)
defines strict schemas including:

- `QueryResult`
- `SQLAnalysisResult`
- `FinalAnswer`
- `SavedResult`
- `ResultPage`
- run, conversation, activity, approval, and API request/response models.

[`text2sql_agent/stores.py`](data-analyst-agent/text2sql_agent/stores.py)
provides thread-safe process-local stores for:

- conversations;
- runs and activity events;
- full capped SQL result artifacts.

Models receive a result ID and at most 10 sample rows. The UI can retrieve the
complete capped result through pagination.

### HITL and run lifecycle

[`text2sql_agent/run_manager.py`](data-analyst-agent/text2sql_agent/run_manager.py)
implements:

- run states `queued`, `running`, `approval_required`, `completed`, and
  `failed`;
- internal Deep Agents `astream_events(version="v3")` consumption without
  streaming model tokens to Streamlit;
- sanitized activity labels;
- approval extraction without exposing raw middleware tool payloads;
- LangGraph resume commands shaped as
  `Command(resume={"decisions": [...]})`;
- edited-SQL validation before resume;
- repeated rejection/replanning/approval cycles;
- same-thread checkpoint resume.

### FastAPI

[`text2sql_agent/api.py`](data-analyst-agent/text2sql_agent/api.py) exposes:

- `GET /health`
- `POST /api/conversations`
- `GET /api/conversations/{thread_id}`
- `POST /api/conversations/{thread_id}/messages`
- `GET /api/runs/{run_id}?after_event_id=...`
- `POST /api/runs/{run_id}/decisions`
- `GET /api/results/{result_id}?offset=...&limit=...`

Agent work runs as FastAPI background tasks. Concurrent runs on the same
conversation return `409`.

### Streamlit UI

The entry point is
[`streamlit_app.py`](data-analyst-agent/streamlit_app.py). Supporting modules
are:

- [`text2sql_agent/ui/api_client.py`](data-analyst-agent/text2sql_agent/ui/api_client.py)
- [`text2sql_agent/ui/components.py`](data-analyst-agent/text2sql_agent/ui/components.py)
- [`.streamlit/config.toml`](data-analyst-agent/.streamlit/config.toml)

Implemented UX:

- URL-backed conversation rehydration;
- short conversation identifier and copyable full link in technical details;
- new-conversation action;
- API readiness indicator;
- example prompts for empty conversations;
- pending user message shown while the agent works;
- live sanitized activity status;
- focused SQL review card;
- primary approve action;
- edited-SQL action enabled only after a change;
- progressively disclosed reject/replan feedback;
- assumptions and interpretation;
- complete capped result table;
- CSV download;
- collapsed exact executed SQL;
- collapsed “How this was produced” activity timeline;
- responsive layout with no horizontal page overflow at the tested 375px
  viewport;
- native Streamlit light/dark theme configuration.

### Startup script

[`scripts/start.sh`](data-analyst-agent/scripts/start.sh):

- checks for `uv`, `curl`, `.env`, API key, database, and semantic model;
- runs `uv sync --locked`;
- refuses to overwrite occupied ports;
- starts FastAPI;
- waits for `/health`;
- starts Streamlit;
- waits for Streamlit health;
- reports both URLs;
- supervises both processes;
- stops both on Ctrl+C or child-process failure.

### Tutorial notebook

[`agent_internals_tutorial.ipynb`](data-analyst-agent/agent_internals_tutorial.ipynb)
is an executable student lab covering:

- architecture;
- OSI grounding;
- prompts, memory, and skills;
- structured schemas;
- SQL safety;
- result artifacts;
- real agent construction;
- HITL interruption/resume;
- sanitized activity;
- API lifecycle;
- guided exercises.

Live OpenAI calls are disabled by default through `RUN_LIVE_AGENT = False`.

## How to run the project

From the project directory:

```bash
cd data-analyst-agent
cp .env.example .env
# Add OPENAI_API_KEY to .env.
./scripts/start.sh
```

Open:

- Streamlit: `http://127.0.0.1:8501`
- FastAPI health: `http://127.0.0.1:8000/health`

Press Ctrl+C in the launcher terminal to stop both services.

The local `chinook.db` currently exists and is gitignored. The local `.env`
also exists and must never be committed or copied into logs/documentation.

At handoff time, ports 8000 and 8501 were not listening; start the services
before browser testing.

## How to test

Run the normal suite:

```bash
cd data-analyst-agent
uv run pytest -q
```

Current verified result on 2026-07-18:

```text
29 passed, 1 skipped
```

The skipped test is the opt-in live OpenAI smoke test:

```bash
RUN_LIVE_SMOKE=1 uv run pytest -m live
```

The notebook was also executed end-to-end with live model calls disabled.

The Streamlit flow was manually verified in the in-app browser:

1. Create a conversation.
2. Submit an example analytical question.
3. Observe sanitized progress.
4. Reach SQL approval.
5. Edit the generated SQL.
6. Execute the edited SQL.
7. Inspect answer, assumptions, interpretation, table, timing, and CSV action.
8. Refresh and recover the same conversation from the URL.
9. Start a new conversation and confirm the URL/thread changes.
10. Check desktop and 375px layouts.

## Known limitations and risks

### Deliberate POC limitations

- All conversations, checkpoints, runs, events, and results are process-local.
- Restarting FastAPI invalidates old conversation URLs. Streamlit detects the
  resulting `404` and creates a new conversation.
- There is no authentication, user identity, tenancy, or authorization.
- The result endpoint is unscoped at HTTP level; an opaque result ID is not a
  security boundary.
- There is no recent-conversation index.
- There are no charts or multipage navigation.
- FastAPI background tasks and in-memory state are unsuitable for horizontal
  scaling.
- The model/result cap is 500 rows; this is not intended for bulk export.

### SQL correctness risk

During live testing, the model once generated SQL using OSI logical names such
as `invoice_lines` instead of physical Chinook names such as `InvoiceLine`.
The prompt was strengthened to make the distinction explicit, but prompt
guidance is not a deterministic guarantee.

The current `sql_db_query_checker` is model-based and may not detect every
missing physical table/column before HITL. The human can edit SQL, and execution
will fail safely, but the review experience can still be improved.

### Dependency and warning cleanup

The normal tests currently show:

- a `langchain-community` deprecation warning; the SQL toolkit should eventually
  migrate to maintained standalone integrations or local deterministic tools;
- a Starlette/FastAPI TestClient deprecation warning related to the HTTPX test
  integration.

Live runs also produced experimental LangGraph v3-streaming warnings and a
Pydantic serialization warning involving `AgentContext` during resume. These
did not break the verified workflow but should be investigated before a
production iteration.

### Configuration caveat

`.env.example` currently enables `LANGSMITH_TRACING=true` while also containing
a placeholder LangSmith key. For a smoother first-run experience, consider
making tracing opt-in by default.

## Recommended next steps

### Priority 0: correctness and security before broader use

1. Add a deterministic pre-HITL SQL validation tool that:
   - validates SQLGlot syntax and read-only semantics;
   - runs `EXPLAIN QUERY PLAN` on a read-only SQLite connection;
   - reports missing physical tables/columns before presenting SQL to the user.
2. Require the specialist to call that validator before `execute_sql`.
3. Add authentication and tenant-aware authorization if the app will be used by
   more than one trusted local user.
4. Scope result retrieval to the authenticated user/conversation at the API
   boundary.

### Priority 1: durable application state

1. Replace `InMemorySaver` with a durable LangGraph checkpointer.
2. Replace process-local conversation/run/result stores with a database or
   object/artifact store.
3. Persist conversation metadata separately from graph checkpoints.
4. Define retention and deletion behavior for SQL results.
5. Add restart/recovery integration tests.

### Priority 2: evaluation and observability

1. Build a Chinook evaluation set containing:
   - natural-language question;
   - expected tables/joins;
   - expected SQL properties;
   - expected result;
   - expected assumptions.
2. Track SQL validity, execution success, semantic accuracy, number of replans,
   and human edit rate.
3. Make LangSmith tracing explicitly opt-in and confirm prompts/results are
   handled according to data policy.
4. Resolve or consciously pin around the current dependency warnings.
5. Add structured application logging with run/thread correlation IDs, while
   keeping secrets, prompts, and result rows out of normal logs.

### Priority 3: UX and operational polish

1. Replace the blocking Streamlit polling loop with `st.fragment` auto-refresh
   or another bounded polling mechanism if responsiveness becomes an issue.
2. Add Streamlit `AppTest` coverage for empty state, approval controls,
   change-aware edit behavior, new conversation, and expired-thread recovery.
3. Add a recent-conversation list only after durable persistence exists.
4. Add optional charts only after the answer/result contract includes validated
   visualization intent and a table remains available as the accessible
   alternative.
5. Consider a production process supervisor/container setup instead of the
   local foreground Bash launcher.

## Key learnings

1. **A semantic model reduces exploration but does not replace validation.**
   OSI provides stable meaning, joins, metrics, and synonyms; a deterministic
   live-schema check is still needed to catch drift and logical/physical naming
   mistakes.
2. **Logical and physical names must be unambiguous.** Agent prompts should
   explicitly state that OSI dataset/field names are conceptual and
   `source`/expression values are executable identifiers.
3. **Custom subagents need explicit capabilities.** Deep Agents custom
   subagents do not automatically inherit coordinator skills.
4. **HITL requires stable checkpoint identity.** Interrupt and resume must use
   the same checkpointer and `thread_id`, with decisions translated into the
   exact LangGraph resume shape.
5. **Human review complements deterministic safeguards.** Prompts and approval
   are not security boundaries; SQL parsing, read-only mode, authorizers,
   timeouts, and row caps remain essential.
6. **Large results should be artifacts, not conversation context.** Keeping up
   to 500 rows outside the checkpoint while sharing only 10 sample rows limits
   token use and still supports full UI inspection.
7. **Structured output turns agent behavior into an application interface.**
   Strict schemas make API/UI code predictable and keep assumptions and
   interpretation separate from raw data.
8. **Observability must be intentionally sanitized.** Raw middleware
   descriptions can expose tool arguments. Convert them to stable,
   user-oriented activity labels at the API boundary.
9. **URL-backed conversation IDs are appropriate routing state for this POC.**
   They provide refresh and deep-link recovery, but must never be treated as
   authorization tokens.
10. **Real browser testing finds issues unit tests miss.** It exposed raw tool
    payload text, logical-name SQL, action-state behavior, refresh handling, and
    responsive-layout concerns.
11. **Native Streamlit patterns age better than broad CSS overrides.** Theme
    configuration, bordered containers, status blocks, pills, Material icons,
    and horizontal containers produced a cleaner and more maintainable UI.
12. **A foreground launcher is the right level of local orchestration.** It
    keeps logs visible, fails early on configuration/port problems, and gives
    one Ctrl+C cleanup path without introducing production infrastructure.

## Primary references

The implementation and documentation were informed by:

- [LangChain Deep Agents documentation](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- [Deep Agents event streaming](https://docs.langchain.com/oss/python/deepagents/event-streaming)
- [LangChain human-in-the-loop middleware](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
- [Datawhale Deep Agents in Action](https://datawhalechina.github.io/deepagents-in-action/)
- [Apache Ossie/OSI core specification](https://github.com/apache/ossie/blob/main/core-spec/spec.md)
- the repository-local `.codex/skills/langchain-dev-guide`;
- the installed Streamlit version-matched development guidance;
- UI/UX Pro Max accessibility, layout, and interaction guidance.

For detailed user-facing setup and architecture documentation, continue with
[`data-analyst-agent/README.md`](data-analyst-agent/README.md). For a teaching
walkthrough, use
[`data-analyst-agent/agent_internals_tutorial.ipynb`](data-analyst-agent/agent_internals_tutorial.ipynb).
