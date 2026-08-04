# Advisor Match Agent

Advisor Match Agent is a loopback-only LangGraph application that matches one
uploaded advisor CSV/XLSX against an authoritative reference, supports bounded
pre-match clarification, and publishes a verified `advisor_matches.xlsx` workbook
for offline review.

The control plane is an explicit `StateGraph`. Two non-streaming LLM decisions
are allowed: a typed request router and a typed input-mapping interpreter. Each
gets at most three total structured-output attempts. Normalization, candidate
generation, scoring, identity decisions, and workbook generation remain
deterministic Python. The graph ends when the workbook is published; it does not
apply row-level review decisions in chat.

## State and storage

- `InMemorySaver` holds graph checkpoints and pending `interrupt()` calls.
- Conversations, turns, runs, and progress events are process-local.
- An API restart intentionally starts a fresh conversation and loses pending
  progress.
- `.data/advisor_repository.sqlite3` durably stores attachment metadata,
  reference snapshots, match sessions, and artifact metadata.
- Older application/checkpoint databases are left untouched and are not read.

## Run locally

Copy `.env.example` to `.env`, configure `MODEL_NAME` and provider credentials,
then run:

```bash
uv sync --locked --all-groups
./scripts/start.sh
```

The API and Streamlit UI must remain bound to loopback addresses. Corporation
IDs provide storage isolation, not authentication.

## Important files

- `general_agent/graph.py` — nodes, edges, interrupts, and graph compilation.
- `general_agent/graph_state.py` — graph state and structured LLM contracts.
- `general_agent/user_messages.py` — deterministic user-facing workflow copy.
- `general_agent/advisor_service.py` — explicit application-service boundary.
- `general_agent/advisor_matching/` — deterministic policy and workbook code.
- `general_agent/runtime_store.py` — in-memory chat/run/event state.
- `general_agent/advisor_repository.py` — durable match and artifact records.
- `docs/contracts/` — matching, mapping, offline-review, and workbook contracts.
- `docs/advisor_match_workflow.html` — interactive workflow diagram.

Matching policy: `docs/contracts/matching-policy.yaml`.

## Validate

```bash
uv run pytest
uv run python scripts/generate_advisor_match_fixtures.py
git diff --check
```

The live provider smoke remains opt-in. Profile building is still an
unregistered `# TODO` and is not simulated.
