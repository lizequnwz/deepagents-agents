# Agent efficiency and conversational progress

Implemented increments 0–5 of the [implementation plan](implementation-plan-agent-efficiency-and-progress.md), verified on 2026-09-08.

## Delivered in order

| Increment | Result |
|---|---|
| 0 — Isolation | Test collection overrides inherited storage before application imports; each test gets fresh storage. Sentinel history and artifacts are checked for unchanged bytes. |
| 1 — Owner prompts | SQL correctness rules live in the SQL system prompt; chart guidance lives in the coordinator prompt. Deleted query-writing and chart-design skills. Analysis and report skills remain. |
| 2 — Semantic context | `get_semantic_context` replaces the three fragmented discovery tools. Small catalogs are supplied inline; larger catalogs get bounded definitions, metric dependencies, declared joins, bridge keys and explicit ambiguity. Business and physical projections remain separate. |
| 3 — Proportional work | Prompts distinguish direct conversation, metadata research, simple descriptive answers and iterative investigations. No classifier or narration model was added; SQL retains exclusive source execution. |
| 4 — Activity | The question precedes one assistant shell with elapsed time, current action, Stop and a stable Activity disclosure. Findings appear before report completion. Diagnostics stay inside Activity. |
| 5 — Durable steering | Corrections have persisted IDs and per-agent acknowledgements, are reconciled at model/tool boundaries, and block stale publication. Clarification uses a resumable interrupt. Published answers remain immutable; later corrections queue a new turn. |

Corrections received during SQL/Python execution are applied after the current step. Corrections to pending code reviews reject the obsolete proposal and require review of revised code. Queued follow-ups preserve the original published evidence even if its report fails. Report-only retry continues to reuse saved evidence.

## Verification

The baseline isolated suite passed **156 tests, 6 deselected**. The completed implementation passed **172 tests, 6 deselected**, in 26.51 seconds. Both test collection and the full deterministic suite left inherited sentinel conversation/run records and an artifact unchanged. The four warnings concern upstream HTTP client deprecation, experimental LangGraph v3 streaming and DuckDB's deprecated batch-reader method.

Commands:

```sh
.venv/bin/pytest --collect-only -q
.venv/bin/pytest -m 'not live' --tb=short
.venv/bin/ruff check data_analytics_agent streamlit_app.py tests --select F
git diff --check
```

Ruff's existing unused/undefined-code checks and whitespace checks passed.

| Scenario | Deterministic evidence |
|---|---|
| Small-catalog scalar | Real DeepAgents harness returns the expected count, publishes evidence and renders its report; no semantic discovery, SQL skill read, planning or Python call. |
| Bridge aggregation | Semantic tests include bridge definitions and required join keys. |
| Large catalog | One context request resolves relevant definitions outside the overview. |
| Ambiguous definitions | Alternative declared routes and invalid exact selections return explicit refinement information; oversized packages do not return broken partial definitions. |
| Requested charts | Existing chart/version tests retain chart types, display-only sampling, uncertainty and report metric bindings. |
| Iterative analysis | Persistent analyst tests exercise repairs, multiple saved inputs, saved execution steps and incomplete-population handling. |
| Chart revision | Shared chart versions preserve saved evidence and lineage. |
| Repair | Tool error diagnostics retain identity and duration; execution tests exercise repair and subsequent success. |
| Report failure | Findings remain usable; report-only retry does not recompute; queued follow-up preserves a failed parent's evidence. |
| Steering and recovery | Nested real-harness SQL/Python boundary tests, approval invalidation, publication races, clarification resume, checkpoint restart, Stop/Resume and stable UI identities. |

An isolated fixture API and Streamlit browser preview also verified disclosure persistence and composer focus/draft preservation during polling, correction acknowledgement, and a 390 × 844 viewport. AppTest covers stable Activity identity through publication/completion and the report retry control. The preview services were stopped after inspection.

## Timing evidence and limits

The retained [synthetic trace](agent-efficiency-synthetic-trace.json) reports six scripted model calls (four coordinator, two SQL), four tool calls, findings at 1,217 ms and 82 ms of report preparation. The tools are SQL execution, delegation, publication and report creation. Token usage is unavailable from the scripted model; the zero-valued token fields must not be interpreted as measured usage.

These are wiring and artifact checks, not measurements of live routing intelligence or provider latency. The original scripted baseline did not enforce mandatory skill reads, so its call counts are not a valid speed comparison. No matched live before/after prompt-size, token or latency comparison was run, and no percentage speedup is claimed. The six opt-in live evaluations remain excluded.

## Rollout and remaining limits

Restart the API and UI together for **API contract 10**. OSI edits require a restart. Graph and bounded semantic caches include source identity, catalog hash and dialect; semantic caches also distinguish projection and request selections. A changed or unversioned checkpoint is rejected rather than silently resumed against different definitions; saved evidence remains available for a new turn.

Oversized semantic packages conservatively return refinement guidance and omissions rather than splitting required definitions. Narrow exact selections or paginated browsing are required in those cases. Declared-route exploration is bounded and reports unresolved work when its cap is reached.

The pre-existing offline map/report renderer incompatibility remains outside this change. Requested chart types are not silently substituted to conceal it.
