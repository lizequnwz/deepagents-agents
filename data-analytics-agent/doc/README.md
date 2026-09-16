# Documentation

This folder is organized by how the material is used. Start with the user guide
for the product workflow, then use the development guides for implementation
work. Dated reviews and generated presentation assets are kept separate from
the current guidance.

## User guide

- [Using the agent](user/using-the-agent.md) — the supported analyst workflow,
  controls, and report behavior.

## Development

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
- [Safety and human approval](development/safety-and-hitl.md) — safety,
  approval, and execution constraints.

## Roadmap and deferred work

- [Improvement roadmap](roadmap/roadmap.md) — the current prioritized product
  opportunities.
- [Deferred next steps](../HANDOFF.md) — work explicitly outside the current
  release.

## Reviews and historical records

- [Reviews and evidence index](reviews/README.md)
- [Design review — 10 September 2026](reviews/design-review-2026-09-10.md)
- [Data plugin comparative review — 14 September 2026](reviews/data-plugin-comparative-review-2026-09-14.md)
- [Standalone data plugin review — 14 September 2026](reviews/data-plugin-standalone-review-2026-09-14.md)
- [Review packet](reviews/review-packet.html)
- [Review evidence](reviews/data-plugin-review-evidence/) — source receipts
  supporting the standalone review.

These dated documents preserve context and evidence. They are not substitutes
for the current architecture, user, or development guides.

## Diagrams

See the [diagram index](diagrams/README.md). Editable workflow sources and
their generated HTML/SVG views live together there.

## Presentations

- [Inside Codex Data](presentations/inside-codex-data/README.md) — the
  explorable presentation, presenter guide, and generated QA receipt.

Generated HTML, presentation, and QA files are intentionally retained beside
their source material so they can be opened offline and reviewed as delivered
artifacts. Rebuild instructions are documented in each source directory.
