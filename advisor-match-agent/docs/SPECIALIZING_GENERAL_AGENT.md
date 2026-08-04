# Why This Application Uses an Explicit Graph

The original specialization wrapped a fixed advisor-matching procedure in a
general Deep Agents harness. Repository review showed that nearly all material
behavior was already deterministic: profiling, validation, firm resolution,
reference snapshots, candidate generation, scoring, match decisions, ambiguity
classification, and workbook generation.

The refactor keeps the reusable domain modules and narrows model judgment to two
well-defined contracts:

- route the user's conversational intent;
- interpret a bounded upload profile into an exact typed mapping.

Everything else is an explicit graph edge or application-service call. This
improves predictability, makes node/state transitions observable, removes skill
installation and general-purpose middleware, and permits ordinary unit and
integration tests without simulating autonomous tool selection.

The trade-off is deliberate: adding an unrelated capability now requires a new
route and node rather than dropping a tool into a general agent. For a
single-purpose financial identity workflow, that reviewable friction is useful.
Future advisor-matching variants can add explicit nodes, deterministic policy
versions, or a bounded conversational layer without reintroducing a planner.

The current graph deliberately stops after workbook publication. Moving
post-match review into the downloaded workbook removes review pagination,
manual-override proposals, approval state, review-audit mutations, and repeated
workbook regeneration. That reduces state and failure modes while preserving
the deterministic matching output and its audit evidence.

Useful former runtime-skill material now lives in `docs/contracts/`; maintenance
utilities live in `scripts/advisor_match/`. Those files document or exercise
code-owned behavior and are never loaded as model instructions.
