# Documentation

Updated 1 October 2026. Start with the task you want to complete.

| I want to… | Read |
|---|---|
| Install and run the app | [Quick start](../README.md#run), then [configuration](development/configuration.md) |
| Ask questions or review an upload | [User guide](user/using-the-agent.md) |
| Try realistic questions | [Examples](user/deep-dive-examples.md) and [sample CSV](user/examples/monthly-index.csv) |
| Inspect/replay portable work | [Downloadable analysis example](examples/README.md) |
| Continue implementation | [Handoff](../HANDOFF.md), [roadmap](roadmap/roadmap.md), and [ablation plan](roadmap/simplification-and-ablation.md) |
| Check delivered capabilities | [Current capability status](roadmap/implementation-progress.md) |
| Verify the latest release | [Release verification](reviews/release-verification-2026-09-30.md) |
| Check the latest usability improvements | [Business usability verification](reviews/business-usability-2026-10-01.md) |
| Check the latest ablation and review repair | [1 October outcome](reviews/ablation-outcomes-2026-10-01.md) |
| Understand system boundaries | [Architecture](development/architecture.md) |
| Connect a source | [Source onboarding](development/adding-data-sources.md) and [semantic modeling](development/semantic-model-best-practices.md) |
| Run regression or provider evaluations | [Testing](development/testing.md) |
| Read assessments and their evidence | [Reviews](reviews/README.md) |

## Development guides

- [Architecture](development/architecture.md) — authoritative system boundaries and lifecycle.
- [Backend development](development/backend-development.md) — source execution, contracts, cancellation and verification.
- [Configuration](development/configuration.md) — setup, providers, approvals, budgets and reload.
- [Testing](development/testing.md) — reproducible prompts, independent grading and evidence limits.
- [Adding sources](development/adding-data-sources.md) — registry and onboarding.
- [Semantic modeling](development/semantic-model-best-practices.md) — conventions and validation.
- [Semantic discovery](development/semantic-discovery.md) — implemented retrieval and deferred scale options.
- [Snowflake backend](development/snowflake-backend.md) — optional adapter and operating boundary.
- [Diagram index](diagrams/README.md) — source-onboarding visuals and editable sources.

## How to maintain the collection

Current behavior belongs in `user/` and `development/`. The capability inventory
records delivery; the handoff gives the next session's starting point; the roadmap
and ablation plan define remaining work and gates. The completed cleanup/Excel/export
plan was removed because its outcomes are now in release verification and current
guides.

Dated assessments and receipts belong in `reviews/`. Retain useful historical
material with its actual evidence; do not read it as current implementation guidance.
Missing historical receipts do not establish passed evaluations and are not listed
as available documents. Keep generated evidence beside its source, update links
when moving files, and publish one compact verification record for each delivered
increment rather than duplicate planning/status documents.
