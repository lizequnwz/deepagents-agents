# Advisor Match Agent Repository Guidance

## Purpose and trust model

- This is a loopback-only financial-advisor matching application built with
  LangGraph, LangChain, FastAPI, Streamlit, and SQLite.
- Its only supported agent workflow is matching one uploaded CSV/XLSX against
  an authoritative advisor source, reviewing decisions, and exporting results.
- The runtime agent has no shell, arbitrary Python/code execution, network,
  package-installation, general file-write, or subagent capability.
- Prompt instructions are not a security boundary. Enforce corporation scope,
  path validation, row limits, and decision rules in application code.

## Start here

- `general_agent/graph.py`: explicit nodes, edges, routing, and interrupts.
- `general_agent/advisor_service.py`: deterministic workflow service boundary.
- `general_agent/advisor_matching/`: schemas, normalization, policy, matching,
  source adapter, input profiling/loading, and workbook generation.
- `general_agent/runtime_store.py`: process-local conversations, runs, and events.
- `general_agent/advisor_repository.py`: durable advisor-review persistence.
- `general_agent/workspace.py`: minimal corporation-scoped protected attachment,
  reference-snapshot, and workbook-artifact storage.
- `docs/contracts/`: static policy and workbook contracts; never model skills.
- `docs/SPECIALIZING_GENERAL_AGENT.md`: architecture rationale.

## Non-negotiable invariants

- Never modify the sibling parent `general-agent` project.
- Scope every conversation, run, upload, snapshot, match session, review
  decision, proposal, workbook, and artifact by `corp_id`.
- Keep both services loopback-only. Corporation IDs isolate storage but are not
  authentication; do not present this app as safe for untrusted users.
- Keep traversal/symlink rejection, protected storage roots,
  attachment/reference/artifact IDs, structured-output retry limits,
  cancellation, documented restart loss, and immutable workbook artifacts.
- The model may inspect bounded profiles and review pages. It must never receive
  the complete master table or full workbook and must never decide matches row
  by row.
- Deterministic code owns normalization, candidate generation, scoring,
  decisions, duplicate detection, review mutations, and workbook regeneration.
- Exact CRD is decisive with conflict warnings. Unique normalized email is
  strong. Name matching needs independent evidence. Nicknames and fuzzy names
  are candidate evidence only; a fuzzy name alone is never confirmed.
- An unlisted candidate requires exact CRD resolution, display, and explicit
  confirmation in a later user turn before it is applied.
- Never modify the original upload. Always regenerate and verify the four-sheet
  `advisor_matches.xlsx` export from persisted structured decisions.
- Profile building remains an unregistered `# TODO`; do not simulate it.
- Do not hand-edit `.data/` or other derived runtime state. The generic
  chat/shared workspace is intentionally unsupported.

## Graph prompts and contracts

- Keep router and mapping prompts in `general_agent/graph_prompts.py` aligned
  with their strict schemas in `general_agent/graph_state.py`.
- Runtime skills and general-purpose tool selection are intentionally absent.
- Keep static behavior contracts in `docs/contracts/`.
- Treat prompt, tool schema, policy, and workbook changes as behavior changes;
  add focused deterministic tests.

## Development and validation

- Preserve unrelated user changes and avoid broad refactors.
- Use Python 3.11+ and absolute imports inside `general_agent`.
- Keep production settings environment-backed and validated.
- Dependency changes belong in `pyproject.toml` and `uv.lock`; never install
  packages from an agent workflow.
- Do not commit, push, open a PR, or delete user data unless explicitly asked.

Run the narrowest relevant test first, then:

```bash
uv sync --locked --all-groups
uv run pytest
uv run python scripts/generate_advisor_match_fixtures.py
git diff --check
```

Use the billable live smoke test only when intentionally requested. Review
changes in this order: capability escape/network access, corporation leakage,
path isolation, identity-policy correctness, audit/export correctness, then UI
and documentation consistency.
