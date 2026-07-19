# Developer documentation

This documentation is for Python and agent developers maintaining or extending
the Data Analytics Agent. The root [`README.md`](../README.md) is the concise
entry point; these guides explain the contracts and procedures behind it.

## Learning paths

### Run and use the agent

1. [`using-the-agent.md`](using-the-agent.md)
2. [`operations-and-testing.md`](operations-and-testing.md)
3. [`safety-and-hitl.md`](safety-and-hitl.md)

### Add or improve a data source

1. [`adding-data-sources.md`](adding-data-sources.md)
2. [`semantic-model-best-practices.md`](semantic-model-best-practices.md)
3. [`operations-and-testing.md`](operations-and-testing.md)

### Add a database backend

1. [`architecture.md`](architecture.md)
2. [`backend-development.md`](backend-development.md)
3. [`safety-and-hitl.md`](safety-and-hitl.md)
4. [`snowflake-blueprint.md`](snowflake-blueprint.md)

### Add another specialist agent

1. [`architecture.md`](architecture.md#adding-specialist-capabilities)
2. Review the existing `agents/visualization/` result-contract pattern.
3. [`safety-and-hitl.md`](safety-and-hitl.md#trust-boundary)
4. [`backend-development.md`](backend-development.md#keep-backend-and-agent-contracts-separate)

The executable [`agent_internals_tutorial.ipynb`](../agent_internals_tutorial.ipynb)
is the companion lab. It demonstrates the registry, OSI grounding, backend
contract, result provenance, HITL interruption, API lifecycle, and UI behavior.
The production graph additionally includes the feature-flagged visualization
specialist and constrained chart contract.

## Guide index

| Guide | Use it when |
| --- | --- |
| [Using the agent](using-the-agent.md) | Running the UI, selecting sources, reviewing SQL, restoring conversations, or diagnosing user-facing problems |
| [Architecture](architecture.md) | Understanding ownership, source binding, agent topology, extension seams, or process-local limitations |
| [Adding data sources](adding-data-sources.md) | Registering another SQLite database or changing source metadata and limits |
| [Semantic-model best practices](semantic-model-best-practices.md) | Authoring or reviewing an OSI `0.1.1` model |
| [Backend development](backend-development.md) | Implementing or testing another `SQLBackend` |
| [Safety and HITL](safety-and-hitl.md) | Changing SQL validation, approval, execution, result access, or trust boundaries |
| [Operations and testing](operations-and-testing.md) | Configuration, startup, readiness, tests, notebook execution, and troubleshooting |
| [Snowflake blueprint](snowflake-blueprint.md) | Planning the future Snowflake adapter at a conceptual level |

## Canonical diagrams

Each diagram has an embedded dual-theme SVG, an interactive Archify HTML file,
and editable JSON source.

| Diagram | SVG | Interactive | Source |
| --- | --- | --- | --- |
| System architecture | [SVG](diagrams/system-architecture.svg) | [HTML](diagrams/system-architecture.html) | [JSON](diagrams/system-architecture.architecture.json) |
| Query approval sequence | [SVG](diagrams/query-approval.svg) | [HTML](diagrams/query-approval.html) | [JSON](diagrams/query-approval.sequence.json) |
| Data-source onboarding | [SVG](diagrams/data-source-onboarding.svg) | [HTML](diagrams/data-source-onboarding.html) | [JSON](diagrams/data-source-onboarding.workflow.json) |

Regenerate the HTML files from the Archify installation:

```bash
ARCHIFY="$HOME/.codex/skills/archify"

node "$ARCHIFY/bin/archify.mjs" render architecture \
  doc/diagrams/system-architecture.architecture.json \
  doc/diagrams/system-architecture.html

node "$ARCHIFY/bin/archify.mjs" render sequence \
  doc/diagrams/query-approval.sequence.json \
  doc/diagrams/query-approval.html

node "$ARCHIFY/bin/archify.mjs" render workflow \
  doc/diagrams/data-source-onboarding.workflow.json \
  doc/diagrams/data-source-onboarding.html

node doc/diagrams/export_dual_theme_svg.mjs \
  doc/diagrams/system-architecture.html \
  doc/diagrams/system-architecture.svg \
  doc/diagrams/query-approval.html \
  doc/diagrams/query-approval.svg \
  doc/diagrams/data-source-onboarding.html \
  doc/diagrams/data-source-onboarding.svg
```

Run Archify `validate` and `check` after any diagram change.

## Sources of truth

When documentation and behavior disagree, use this order:

1. Tests for an enforced behavior.
2. Pydantic/domain contracts in [`data_analytics_agent/schemas.py`](../data_analytics_agent/schemas.py).
3. Runtime code in [`data_analytics_agent/`](../data_analytics_agent/).
4. Trusted registry data in [`data_sources.yaml`](../data_sources.yaml).
5. Curated semantic meaning in [`semantic/`](../semantic/).
6. This documentation.

Update the relevant guide in the same change whenever one of those contracts
changes.
