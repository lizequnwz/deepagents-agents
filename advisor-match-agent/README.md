# Advisor Match Agent

Advisor Match Agent is a trusted-local DeepAgents application that matches financial-advisor rows from one uploaded CSV or XLSX against an authoritative advisor reference, conducts a bounded conversational review, and publishes a verified `advisor_matches.xlsx` artifact.

The initial reference is a wholly synthetic development dataset. No Snowflake connection or advisor profile builder is implemented yet.

> [!CAUTION]
> Keep both services loopback-only. Corporation IDs provide storage isolation, not authentication. Uploaded advisor information is sensitive and bounded samples/review pages are sent to the configured model provider.

## Workflow

1. Upload one `.csv` or `.xlsx` in the chat composer.
2. Ask the agent to match its advisors.
3. The model inspects bounded raw rows, detects a header or headerless layout, selects one sheet, and asks when column meanings are ambiguous.
4. Deterministic code validates exact indexes and headers. If name rows lack firm, valid CRD, and valid email, choose a corrected upload or explicitly continue.
5. The agent retrieves an opaque authoritative snapshot; deterministic code performs every row decision.
6. Review `Ambiguous Match` first and `No Match` second in bounded conversational pages. Automated matches are available on request.
7. Confirm a presented candidate, confirm no match, or supply an exact CRD for a separately reconfirmed override.
8. Download the styled, verified four-sheet workbook artifact and optionally approve with unresolved exceptions. Every successful revision has its own immutable artifact ID.

Profile building is a documented `# TODO` and is not exposed as a tool.

The model never reads or edits the whole workbook, receives the full master table, runs shell commands, installs packages, browses the web, or delegates to a general-purpose subagent.

## Output workbook

- `Matched`: effective automatic and user-confirmed matches.
- `Review Required`: ambiguous candidates and no-match rows.
- `Original Input`: the selected source table in original order.
- `Run Summary`: session, mapping, counts, hashes, policy versions, and approval state.

The first two sheets use a compact human-first layout with technical audit fields hidden by default. Headers are frozen and filtered; widths, fills, wrapping, status colors, and text-safe CRD/ZIP formats are applied. Every revision is regenerated deterministically, reopened for validation, and published under a new immutable artifact ID.

## Synthetic data and examples

- Master source: `general_agent/advisor_matching/data/master_advisors.csv`
- Example uploads: `examples/advisor-match/`
- Generator: `scripts/generate_advisor_match_fixtures.py`
- Matching policy: `skills/advisor-match/references/matching-policy.yaml`

All fixture identities are invented and use reserved example email domains.

## Quick start

Requirements: macOS or Linux, Python 3.11+, `uv`, and credentials for a LangChain chat model with reliable tool calling.

```bash
cp .env.example .env
# Set MODEL_NAME and the required provider credential.
./scripts/start.sh
```

Open <http://127.0.0.1:8502>. The loopback API is at <http://127.0.0.1:8001/docs>.

## Configuration

Important defaults:

| Variable | Default |
| --- | ---: |
| `API_HOST` / `APP_HOST` | `127.0.0.1` |
| `ADVISOR_MAX_INPUT_ROWS` | `50000` |
| `ADVISOR_MAX_REFERENCE_ROWS` | `1000000` |
| `MAX_UPLOAD_MB` | `100` |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` | `32` / `64` |

LangSmith tracing is off by default because prompts and tool pages can contain advisor information.

## Storage and isolation

Uploads are written once to protected corporation-scoped storage and referenced by opaque attachment ID. Reference snapshots and verified workbook revisions use the same pattern. SQLite stores conversations, sessions, decisions, audits, hashes, and file locations; there is no generic chat/shared workspace or model-visible upload path.

Derived state lives under `.data/`. Do not hand-edit it. Installed skills are rebuilt under `.data/runtime/skills` at startup, and only `advisor-match` is exposed through the agent's read-only virtual filesystem.

## Development and tests

```bash
uv sync --locked --all-groups
uv run python scripts/generate_advisor_match_fixtures.py
uv run pytest
git diff --check
```

The deterministic suite does not require model credentials. Provider-backed smoke tests remain opt-in.

The general specialization rationale remains in `docs/SPECIALIZING_GENERAL_AGENT.md`; this project implements its deterministic matching boundary with a synthetic source and persisted review sessions.

The concrete state and conversational-review design is documented in `docs/ADVISOR_MATCH_ARCHITECTURE.md`.
The inherited-capability disposition is documented in `docs/CAPABILITY_RESTRICTIONS.md`.
