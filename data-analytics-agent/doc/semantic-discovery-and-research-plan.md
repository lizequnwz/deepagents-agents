# Semantic Discovery and Research Capability Plan

## Objective

Evolve the Data Analytics Agent so it can work efficiently with both small and
very large OSI semantic models and support metadata-grounded research before
query execution.

The target experience has two natural paths:

- **Research:** inspect available semantic metadata, develop analytical
  opportunities and hypotheses, identify limitations, and propose an analysis
  plan without executing SQL unless the user asks for observed data.
- **Analysis:** resolve the required semantic context, execute the smallest
  sufficient set of SQL and optional statistical steps, and produce the normal
  evidence-backed answer, visualization, and report.

Keep both paths inside the existing coordinator. Do not add a research
subagent, a custom LangGraph workflow, a vector database, or another persistent
artifact type for the initial implementation.

## Design principles

- Keep the OSI document as the authoritative semantic source.
- Parse the model once and expose focused semantic views instead of repeatedly
  placing the raw YAML in model context.
- Give the agent enough high-level context to orient itself, then let it fetch
  only the relevant datasets, fields, metrics, and relationships.
- Prefer a few batched tools over many narrow tools.
- Keep discovery deterministic and source-bound.
- Keep business-facing semantic metadata separate from physical SQL details.
- Preserve the current coordinator, specialist, approval, result, visualization,
  and reporting boundaries.
- Start with exact and lexical search. Add embeddings only if real large-model
  evaluations show they are necessary.
- Treat example values and observed profiles as data access, not harmless
  metadata.
- Remove the obsolete raw-file agent path once the replacement works. Do not
  retain a compatibility fallback.

## Current limitation

The text-to-SQL specialist currently reads the complete OSI file at the start
of every stateless assignment. This is acceptable for the bundled models but
scales poorly when a model contains thousands of fields or an investigation
uses several SQL assignments.

The coordinator also owns analysis brainstorming but receives only a source
description, curated examples, dialect, and semantic-model path. It has no
small, structured interface for understanding the actual datasets, metrics,
and relationships before deciding what analyses are possible.

The existing semantic loader validates the OSI file but does not retain a
typed, reusable representation for agents. The implementation should turn that
existing loading boundary into the foundation for semantic discovery.

## Proposed architecture

### 1. Application-owned semantic catalog

Load and validate each source's OSI model once when the source is initialized.
Convert it into an immutable `SemanticCatalog` containing only the structures
the application needs:

- model name, description, version, and global AI context;
- datasets keyed by logical name;
- fields keyed by dataset and logical field name;
- selected dialect expressions;
- primary keys;
- metrics keyed by logical name;
- relationships and a dataset adjacency map;
- names, descriptions, and synonyms used for search;
- optional physical column types already obtained during source readiness;
- a content hash identifying the loaded model revision.

The catalog should be the shared source for readiness validation, prompt
overview generation, and semantic tools. Avoid creating separate parsing and
indexing models that can drift from each other.

Keep provider-specific physical metadata behind `SQLBackend`. The catalog may
consume the targeted readiness snapshot, but semantic tools must never
enumerate undeclared database objects.

### 2. Compact semantic overview

Generate a deterministic overview from the catalog and include it in the
coordinator and text-to-SQL prompts.

The overview should contain:

- model name and description;
- global AI instructions and material caveats;
- dataset, field, relationship, and metric counts;
- concise dataset names and descriptions;
- canonical metric names and short descriptions;
- the model content hash.

For small models, the overview may list every dataset and metric. For large
models, keep it bounded and emphasize model-level structure. Use serialized
size and entity counts rather than line count to decide how much to include.

Do not place physical expressions or complete field lists in the coordinator's
overview. The text-to-SQL specialist obtains those details only for selected
entities.

### 3. Focused semantic tools

Expose one shared catalog through role-specific read-only tools.

#### `search_semantic_model`

Input:

- natural-language query;
- optional entity kinds: dataset, field, or metric;
- bounded result limit.

Output:

- matching logical names;
- entity kind and parent dataset where applicable;
- concise description;
- matching synonym or text reason;
- model hash.

Search exact names, normalized names, synonyms, and descriptions. Begin with a
simple deterministic scoring function. Search identifies candidates; it does
not decide join paths or invent semantic definitions.

#### `get_semantic_entities`

Input:

- a bounded list of dataset and metric names;
- optional selected field names.

Coordinator output:

- logical names, descriptions, grain, keys, semantic field descriptions,
  synonyms, time markers, metric definitions, and local AI context.

Text-to-SQL output additionally includes:

- exact physical dataset sources;
- dialect-selected field and metric expressions.

Batch several entities in one call. Do not require one call per dataset or
field.

#### `get_relationships`

Input:

- a bounded set of dataset names;
- optional target dataset for path discovery.

Output:

- declared direct relationships among or adjacent to the selected datasets;
- declared join fields;
- a shortest declared path when a target is supplied;
- explicit failure when no declared path exists;
- model hash.

Use exact graph traversal over declared OSI relationships. Do not use semantic
search or model inference to create relationship paths.

These three tools are sufficient for the first release. A separate
`list_datasets` tool is unnecessary because the overview and semantic search
cover broad discovery. Split tools later only if observed tool payloads become
too large or confusing.

### 4. Agent access

The coordinator receives:

- the compact semantic overview;
- business-facing semantic search, entity, and relationship tools;
- existing result-inspection and reporting tools.

The text-to-SQL specialist receives:

- the same compact overview;
- SQL-facing semantic search, entity, and relationship tools;
- `execute_sql` and its existing query-writing skill.

The visualization and statistical specialists continue to consume saved result
artifacts and do not need semantic-discovery tools.

Once the tools are in use, remove semantic-file read permission from the
coordinator and text-to-SQL specialist. Keep skill-file access unchanged.

## Semantic discovery workflows

### Small model

1. Read the compact overview already present in the prompt.
2. If the required dataset, metric, and relationship are obvious, fetch their
   exact definitions in one batched entity call.
3. Fetch the declared relationship path when more than one dataset is needed.
4. Continue to research synthesis or SQL generation.

The system may return most semantic metadata in one call for a small model, but
it should still use the catalog interface rather than raw YAML.

### Large model

1. Use the bounded overview to identify likely domains and canonical metrics.
2. Search for candidate datasets, fields, and metrics using business terms from
   the question.
3. Fetch exact definitions for the strongest candidates in one batch.
4. Expand only the relevant declared relationship neighborhood.
5. Fetch additional entities only when required to resolve grain, calculations,
   filters, or join paths.
6. Stop discovery when the question can be answered safely.

The normal path should require a small number of bounded calls, not exhaustive
pagination through the catalog.

## Research behavior

Research is a coordinator-owned path, not a new agent or a persistent global
mode.

Route to Research when the user asks what can be analyzed, requests hypotheses
or analytical ideas, wants to understand available data, or asks for an
analysis plan without requesting actual database values.

The coordinator should:

1. Inspect the semantic overview.
2. Search and fetch the relevant semantic entities and relationships.
3. Identify the business questions supported by the model.
4. Separate supported analysis opportunities from untested hypotheses.
5. Identify useful metrics, dimensions, segments, grains, and time windows.
6. State missing data, semantic ambiguities, and unsupported questions.
7. Recommend a small prioritized analysis plan.

A useful research answer should distinguish:

- **Supported opportunities:** directly enabled by declared semantic metadata.
- **Hypotheses:** plausible relationships that require analysis to test.
- **Limitations:** missing entities, outcomes, dates, relationships, units, or
  definitions.
- **Next analyses:** complete, executable analysis briefs.

Metadata-only Research returns no result IDs and does not trigger automatic
visualization or report generation.

## Analysis behavior

Keep the existing Analysis workflow:

1. Resolve the required semantic context.
2. Delegate one complete assignment at a time to text-to-SQL.
3. Inspect saved evidence and continue sequential investigation only when
   needed.
4. Use statistical analysis only when inference materially improves the answer.
5. Create the normal visualization and report for successful data-bearing
   analysis.

Semantic discovery becomes the text-to-SQL specialist's grounding mechanism;
it does not change SQL approval, validation, execution, result storage, or
provenance.

## Transition between Research and Analysis

Do not require the user to select a mode before asking a question. Infer the
path from intent while treating explicit wording as authoritative.

Examples:

- "What could we analyze?" uses Research only.
- "Help me develop customer engagement hypotheses" uses Research only.
- "Compare engagement by acquisition channel" uses Analysis.
- "Explore the options and then run the best three" performs Research first
  and then Analysis because execution was explicitly requested.

Each recommended next analysis should be expressed as a compact analysis brief:

- objective;
- population and grain;
- metrics;
- dimensions or segments;
- time window;
- required datasets and relationships;
- expected result shape;
- material assumptions or unresolved choices.

When the user asks to run a proposed analysis, the coordinator should restate
that complete brief in the text-to-SQL assignment. Conversation history is
sufficient for the initial release. Do not add a research-plan store or new API
artifact until a concrete UI or persistence requirement exists.

## Optional profiling capability

Do not include live value profiling in the first semantic-discovery release.

If research quality later requires observed values, add a separate governed
`inspect_field_profile` capability rather than mixing data access into semantic
tools. It may return bounded metadata such as null count, distinct count,
minimum, maximum, and top low-cardinality values.

Requirements for a later profiling capability:

- restrict access to OSI-declared fields;
- exclude sensitive or identifier-like fields by default;
- label scope, population, source, and generation time;
- use backend timeouts and source permissions;
- never return arbitrary row samples by default;
- make it clear that the output is observed and potentially stale data.

Profile-backed exploration should not silently masquerade as metadata-only
Research.

## Implementation plan

### Phase 1: Semantic catalog

- Refactor the existing OSI loader into an immutable catalog constructed once
  per source.
- Reuse the catalog for current semantic validation.
- Add exact indexes, relationship adjacency, selected-dialect expressions, and
  deterministic overview generation.
- Keep current agent behavior working during this phase.

Outcome: one application-owned representation of the semantic model.

### Phase 2: Semantic tools

- Implement `search_semantic_model`, `get_semantic_entities`, and
  `get_relationships` over the catalog.
- Create coordinator-facing and SQL-facing projections from the same tool
  implementation.
- Add the compact overview to both prompts.
- Update text-to-SQL grounding instructions to use the tools.
- Remove raw semantic-file reads and permissions after the new path works end
  to end.

Outcome: scalable progressive semantic discovery for SQL and coordinator use.

### Phase 3: Research behavior

- Update coordinator policy and prompt routing for Research versus Analysis.
- Define the expected research-answer structure and analysis-brief format.
- Ensure metadata-only Research skips text-to-SQL, saved results,
  visualization, and reporting.
- Document example Research-to-Analysis conversations.

Outcome: grounded analytical brainstorming without unnecessary execution.

### Phase 4: Scale only when required

- Measure semantic tool usage and retrieval misses on large representative
  models.
- Improve lexical scoring or add hybrid embedding retrieval only if those
  measurements show a real need.
- Add governed field profiling only if users need observed distributions or
  representative values before choosing an analysis.

Outcome: additional complexity is introduced only for demonstrated product
needs.

## Focused acceptance criteria

- Existing small-model SQL questions continue to complete through the smallest
  analysis path.
- The text-to-SQL specialist no longer reads raw OSI YAML.
- Large-model questions retrieve only a bounded relevant semantic subset.
- SQL uses exact declared physical sources, expressions, metrics, and
  relationship paths from the catalog.
- Global and dataset-level semantic instructions remain available when using
  targeted discovery.
- "What can we analyze?" produces a schema-grounded research answer without
  SQL, result IDs, visualization, or report creation.
- A user can select a proposed analysis in a follow-up and transition into the
  existing SQL workflow.
- Source isolation, approval, execution, artifact provenance, visualization,
  statistics, and reporting behavior remain unchanged for Analysis.

## Non-goals

- A new research subagent.
- A custom LangGraph workflow or intent-classification service.
- A vector database in the first release.
- Arbitrary database schema enumeration.
- Automatic profiling of every field.
- Persisted research-plan artifacts or new API contracts without a concrete UI
  requirement.
- Parallel text-to-SQL delegation.
- Cross-source discovery or analysis.
- Compatibility support for raw-file semantic loading after migration.

## Likely implementation areas

- `data_analytics_agent/semantic.py`
- a small semantic tool module under `data_analytics_agent/`
- `data_analytics_agent/coordinator.py`
- `data_analytics_agent/agents/text_to_sql/agent.py`
- `skills/text-to-sql/query-writing/SKILL.md`
- `AGENTS.md`
- semantic-model, source, routing, and text-to-SQL tests
- architecture and user documentation under `doc/`

Prefer extending these existing seams over introducing new packages, agents,
stores, middleware, or graph layers.
