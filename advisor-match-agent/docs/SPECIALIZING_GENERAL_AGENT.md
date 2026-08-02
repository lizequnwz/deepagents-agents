# Specializing General Agent

This repository demonstrates how to specialize a general Deep Agent into a narrow, auditable application. Advisor Match Agent accepts one CSV or XLSX, interprets its schema flexibly, matches rows against an authoritative source with deterministic policy, conducts bounded exception review, and creates a verified workbook.

The reusable lesson is to place adaptability and decisions in different components.

## Responsibility boundary

| Component | Owns | Must not own |
| --- | --- | --- |
| Agent | Bounded interpretation, clarification, tool order, summaries, and review conversation | Row-level identity decisions or unrestricted data access |
| Skill | Procedural workflow and links to policy/contracts | Credentials or duplicate business logic |
| Typed tools | Context/path validation, workflow gates, deterministic service calls, bounded results | Open-ended code execution |
| Domain package | Schemas, normalization, candidate ranking, decision policy, and workbook projection | Conversation or model prompts |
| Source adapter | Read-only authoritative records and schema validation | Fuzzy policy |
| SQLite/store | Corporation-scoped sessions, manifests, decisions, and audit | User-visible spreadsheet editing |

The agent needs flexible reasoning because sheet names, header positions, and column meanings vary. Identity policy must remain ordinary versioned code because it needs reproducibility, tests, auditability, and consistent behavior across rows.

## Three-stage specialization pattern

### 1. Interpret and validate

Expose bounded raw evidence rather than forcing an early parser assumption. The domain profiler should show physical rows, plausible headers, headerless columns, patterns, and small samples. The agent chooses one typed mapping only when clear and asks when multiple interpretations are plausible.

End interpretation with deterministic validation. Bind headed fields by exact zero-based index and observed header, or headerless fields by exact index and null header. Return a fingerprint over source bytes and the canonical mapping so the execution tool can reject drift.

Use a preflight summary for workflow questions that require the user, such as whether to continue when useful name rows lack firm and strong identifiers. Do not invent another persisted planning object unless recovery genuinely requires it.

### 2. Execute deterministically

Retrieve the authoritative source after input clarification. Store the full snapshot behind an opaque, corporation-scoped ID; return only a bounded manifest to the model. Execution revalidates both input fingerprint and reference integrity before invoking domain policy.

Malformed individual values belong to row-level results when other rows remain processable. Reserve whole-run failure for structural errors, safety limits, or authoritative-source integrity failures.

### 3. Review bounded exceptions

Persist typed decisions and expose filters/pages rather than the whole session. The agent explains qualitative evidence and applies only explicit user choices. Record complete before/after audit JSON in the same transaction as the effective decision update. Regenerate derived artifacts from structured state after every change.

## Repository extension points

- `general_agent/agent.py`: narrow system prompt, registered typed tools, read-only skill middleware, limits, and disabled general-purpose subagent.
- `general_agent/advisor_tools.py`: the agent-facing workflow boundary.
- `general_agent/advisor_matching/`: schemas, profiling/loading, normalization, policy, matcher, source adapter, and workbook generator.
- `general_agent/store.py`: session, snapshot, proposal, and review persistence.
- `general_agent/workspace.py`: corporation-scoped uploads, protected data roots, and immutable turn artifacts.
- `skills/advisor-match/`: runtime playbook and policy/contracts.

Keep domain models under the domain package unless they are public FastAPI contracts. Keep skill scripts as thin developer drivers that import production logic rather than maintaining a second implementation.

## Security boundaries to preserve

General Agent is trusted-local, not a multi-user authentication system. Corporation IDs isolate storage but do not authenticate callers. Preserve:

- loopback-only FastAPI and Streamlit hosts;
- `virtual_mode=True`, traversal and symlink rejection;
- corporation scope on conversations, runs, uploads, snapshots, sessions, reviews, workbooks, and artifacts;
- protected hidden paths and read-only installed skills;
- no shell, arbitrary Python, network browsing, package installation, general writes, or subagents in the runtime agent;
- model/tool/token limits, cancellation, restart recovery, and immutable artifacts;
- bounded model views of sensitive uploads and reference data.

Prompts are not a security boundary. Enforce paths, scope, limits, fingerprint checks, reference hashes, and decision rules in application code.

## Matching policy design

Apply exact identifiers before probabilistic-looking evidence. This implementation uses exact CRD, unique normalized email, then supported exact/fuzzy names. Firm normalization removes harmless legal suffixes; close firm matching is deterministic. City and state form location support; ZIP is context only; street address is excluded.

Fuzzy scores are ranking thresholds, not probabilities. Keep them internal and versioned. Calibrate policy against labeled historical cases before production use.

## Workbook design

The workbook is a projection, never the source of truth. Preserve the original upload, store structured decisions, and regenerate the workbook after every review change. Reopen it and verify sheet order, row reconciliation, formula safety, and text handling before delivery.

A human-first default view is compatible with auditability: keep useful identity/evidence columns visible and place technical IDs, rule IDs, automated status, and duplicate groups in hidden columns at the right.

## Production database replacement

The synthetic source implements `AdvisorReferenceSource`. A Snowflake implementation should produce the same projected schema and immutable manifest. For million-row sources, do not transfer the table into model context and do not compare every unresolved row with every advisor. Use a stable source snapshot, exact CRD/email lookup, normalized-name blocking, deterministic candidate pagination, query IDs, and load/performance tests.

## Validation order

Review and test changes in this order:

1. capability escape or network access;
2. corporation leakage and protected-path integrity;
3. input mapping and fingerprint validation;
4. identity-policy correctness and row-level failures;
5. review audit and workbook reconciliation;
6. agent prompt/skill consistency;
7. UI and documentation.

Run focused tests first, then `uv run pytest`, fixture generation, and `git diff --check`. The live provider-backed smoke test remains opt-in. Advisor profile building remains an unregistered `# TODO` and must not be simulated.
