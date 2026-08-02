# Advisor Match Agent Repository Guidance

## Purpose and trust model

- This is a loopback-only financial-advisor matching application built with
  DeepAgents, LangChain, FastAPI, Streamlit, and SQLite.
- Its only supported agent workflow is matching one uploaded CSV/XLSX against
  an authoritative advisor source, reviewing decisions, and exporting results.
- The runtime agent has no shell, arbitrary Python/code execution, network,
  package-installation, general file-write, or subagent capability.
- Prompt instructions are not a security boundary. Enforce corporation scope,
  path validation, row limits, and decision rules in application code.

## Start here

- `general_agent/agent.py`: sole-purpose prompt, narrow tools, filesystem skill
  reads, budgets, and disabled general-purpose subagent.
- `general_agent/advisor_tools.py`: typed workflow and review-session tools.
- `general_agent/advisor_matching/`: schemas, normalization, policy, matching,
  source adapter, input profiling/loading, and workbook generation.
- `general_agent/advisor_backend.py`: non-shell, skill-read-only backend and
  corporation/run context.
- `general_agent/store.py`: application and advisor-review persistence.
- `general_agent/workspace.py`: minimal corporation-scoped protected attachment,
  reference-snapshot, and workbook-artifact storage.
- `skills/advisor-match/`: the only skill installed for the runtime agent.
- `docs/SPECIALIZING_GENERAL_AGENT.md`: source architecture and specialization
  rationale; preserve its reusable-base boundaries.

## Non-negotiable invariants

- Never modify the sibling parent `general-agent` project.
- Scope every conversation, run, upload, snapshot, match session, review
  decision, proposal, workbook, and artifact by `corp_id`.
- Keep both services loopback-only. Corporation IDs isolate storage but are not
  authentication; do not present this app as safe for untrusted users.
- Keep `virtual_mode=True`, traversal/symlink rejection, protected storage roots,
  attachment/reference/artifact IDs, read-only installed skills, model/tool/token
  limits, cancellation, restart recovery, and immutable workbook artifacts.
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

## Agent prompt and skill

- `SYSTEM_PROMPT` in `general_agent/agent.py` is canonical and must match the
  backend's actual narrow capabilities.
- Keep skill trigger/workflow details in `skills/advisor-match/SKILL.md` and its
  references rather than hard-coding a skill catalog in the prompt.
- Edit source skills only. `Settings.prepare_directories()` replaces the
  installed skill tree and installs only `advisor-match`.
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
