# Advisor Match Repository Guidance

## Purpose and trust model

- This is a stateless financial-advisor matching application built with
  LangChain, FastAPI, and Streamlit.
- It matches one uploaded CSV/XLSX against an authoritative advisor source and
  generates a placeholder profile report from a file containing CRDs.
- Every API request carries its own source bytes and configuration. There are no
  conversations, checkpoints, databases, workflow sessions, or persistent local
  artifacts.
- Model instructions are not a security boundary. Enforce upload, inspection,
  row, schema, firm-resolution, and matching rules in application code.

## Start here

- `advisor_match/api.py`: app factory, REST routes, errors, and result packaging.
- `advisor_match/mapping.py`: bounded structured column-mapping calls.
- `advisor_match/advisor_service.py`: stateless deterministic service boundary.
- `advisor_match/advisor_matching/`: schemas, normalization, policy, matching,
  reference adapter, input profiling/loading, workbook, and profile generation.
- `streamlit_app.py`: two-tab form workflow using ephemeral session state.
- `docs/contracts/`: static policy and output contracts.

## Non-negotiable invariants

- Never modify the sibling parent `general-agent` project.
- Do not add conversations, graph orchestration, interrupts, checkpoints,
  persistence, or pod-local cross-request state.
- The model may inspect only bounded upload profiles. It must never receive the
  complete authoritative table or decide matches row by row.
- Deterministic code owns normalization, candidate generation, scoring,
  decisions, duplicate detection, firm handling, and workbook generation.
- Exact CRD is decisive with conflict warnings. Unique normalized email is
  strong. Name matching needs independent evidence. Nicknames and fuzzy names
  are candidate evidence only; a fuzzy name alone is never confirmed.
- Never modify uploaded bytes. All-rows firm overrides affect copied mapped
  values only and are recorded in workbook/result audit metadata.
- Always generate and verify the four-sheet `advisor_matches.xlsx` export in
  memory. Row-level decisions exist only in the workbook.
- Matching ends after verified workbook generation. Downloaded review edits are
  not re-ingested or validated.
- Profile reporting emits only deterministic static HTML from validated opaque
  CRDs; it must not fetch or simulate profile data.
- The reference source is injected per request, schema/row-limit checked, and
  never cached or persisted. Duplicate authoritative CRDs block matching.
- Mapping makes at most three structured-output attempts and returns an explicit
  failure rather than silently guessing.

## Development and validation

- Preserve unrelated user changes and avoid speculative abstractions.
- Use Python 3.11+ and absolute imports inside `advisor_match`.
- Keep production settings environment-backed and validated.
- Dependency changes belong in `pyproject.toml` and `uv.lock`.
- Do not commit, push, open a PR, or delete user data unless explicitly asked.

Run the narrowest relevant test first, then:

```bash
uv sync --locked --all-groups
uv run pytest
uv run python scripts/generate_advisor_match_fixtures.py
git diff --check
```

Use the billable live mapping smoke test only when intentionally requested.
Review changes in this order: upload/capability escape, identity-policy
correctness, reference integrity, audit/export correctness, then UI and docs.
