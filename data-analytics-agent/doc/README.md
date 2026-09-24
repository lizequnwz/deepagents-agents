# Documentation

Start with the task you want to complete. Current guides, delivery status,
proposals, and dated evidence serve different purposes.

## Start here

| I want to… | Read |
|---|---|
| Install and run the app | [Quick start](../README.md#run), then [configuration](development/configuration.md) |
| Use the analyst or upload a file | [User guide](user/using-the-agent.md) |
| Try realistic questions | [Deep-dive examples](user/deep-dive-examples.md) and the [sample CSV](user/examples/monthly-index.csv) |
| Understand how the system works | [Architecture](development/architecture.md) |
| Connect a data source | [Source onboarding](development/adding-data-sources.md), then [semantic modeling](development/semantic-model-best-practices.md) |
| See what is delivered and what is next | [Implementation progress](roadmap/implementation-progress.md), then the [roadmap](roadmap/roadmap.md) |
| Inspect test outcomes or earlier assessments | [Reviews and evidence](reviews/README.md) |
| Open a source-onboarding diagram | [Diagram index](diagrams/README.md) |

## How to read the collection

- **Current behavior:** `user/` and `development/`. Architecture defines system
  boundaries; configuration defines operating controls. Capability design records
  explicitly identify their deferred options.
- **Delivery status:** [implementation progress](roadmap/implementation-progress.md)
  records delivered work and remaining acceptance gates. Check it before treating
  a roadmap recommendation as unfinished.
- **Proposals:** the roadmap and simplification plan preserve their dated
  recommendations. [Deferred next steps](../HANDOFF.md) is a short handoff.
- **Historical evidence:** `reviews/` holds dated reviews, test records, and
  supporting artifacts. Their findings describe the version reviewed.
- **Visual material:** `diagrams/` keeps the current onboarding diagram with
  its editable source and generated views. The architecture guide contains the
  current system diagram.

## Full guide index

### User guides

- [Using the agent](user/using-the-agent.md) — the supported analyst workflow,
  controls, and report behavior.
- [Deep-dive test questions](user/deep-dive-examples.md) — copy-ready investigations,
  a synthetic upload, expected behavior, and report/run-control checks.

### Development

- [Configuration](development/configuration.md) — first-run setup, provider
  alternatives, approval, run controls, and development reload.
- [Architecture](development/architecture.md) — the authoritative system
  boundaries and request lifecycle.
- [Backend development](development/backend-development.md) — backend
  contracts, source execution, cancellation, and verification.
- [Adding data sources](development/adding-data-sources.md) — registry and
  onboarding steps for a new source.
- [Semantic model best practices](development/semantic-model-best-practices.md)
  — modeling conventions and validation rules.
- [Semantic discovery and research](development/semantic-discovery.md) — the
  implemented metadata research path and deferred scale options.
- [Snowflake backend](development/snowflake-backend.md) — the implemented
  optional adapter and its operating boundary.

### Roadmap and deferred work

- [Implementation progress](roadmap/implementation-progress.md) — dated
  delivery record through 21 September 2026 and remaining acceptance gates.
- [Improvement roadmap](roadmap/roadmap.md) — recommendations refreshed on
  19 September 2026, with dated product research, an actionable next-release
  scope, and acceptance criteria for agent quality and result interactions.
- [Deferred next steps](../HANDOFF.md) — work explicitly outside the current
  release.
- [Simplification and ablation plan](roadmap/simplification-and-ablation.md) —
  reduce setup and routine model work while testing capability preservation.

### Reviews and historical records

- [Reviews and evidence index](reviews/README.md)
- [Semantic discovery review — 21 September 2026](reviews/semantic-discovery-review-2026-09-21.md)
- [Artifact handoff review — 20 September 2026](reviews/artifact-handoff-review-2026-09-20.md)
- [Live smoke tests and retry repairs — 20 September 2026](reviews/live-smoke-2026-09-20.md)
- [Design review — 10 September 2026](reviews/design-review-2026-09-10.md)
- [Data plugin comparative review — 14 September 2026](reviews/data-plugin-comparative-review-2026-09-14.md)
- [Standalone data plugin review — 14 September 2026](reviews/data-plugin-standalone-review-2026-09-14.md)
- [Review evidence](reviews/data-plugin-review-evidence/) — source receipts
  supporting the standalone review.

These dated documents preserve context and evidence. They are not substitutes
for the current architecture, user, or development guides.

### Diagrams

See the [diagram index](diagrams/README.md). Editable workflow sources and
their generated HTML/SVG views live together there.

Generated review HTML and supporting evidence remain beside their source
material so the dated assessments can be read offline.

## Keeping documentation organized

Update the relevant current guide when behavior changes, and record delivery
and verification in the implementation log. Put dated assessments and test
receipts in `reviews/`; put proposed work in `roadmap/`. Keep example data beside
its user guide and generated assets beside their editable sources. Add new
reading material to this index, and update links whenever a file moves.
