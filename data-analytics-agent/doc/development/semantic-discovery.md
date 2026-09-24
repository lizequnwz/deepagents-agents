# Semantic discovery and SQL grounding

The source-bound catalog stays in application memory. Agents receive a bounded
overview, compact discovery candidates, and exact definitions for their selected
business concepts. The coordinator handles metadata-only research directly;
text-to-SQL owns detailed grounding and source execution for data-bearing work.

## Discovery and definition resolution

`get_semantic_context` has two explicit modes:

- A question without exact selections returns `mode="discovery"`, independent
  candidate lists for metrics, datasets, fields, and time fields, and
  `question_coverage="requires_selection"`. Candidate quotas are separate and
  field candidates are diversified by dataset. These are not SQL definitions.
- Exact `dataset_names`, `metric_names`, `field_names`, or `relationship_names`
  return `mode="definitions"`. The response includes selected fields, primary
  keys, metric dependencies, chosen joins, and applicable instructions.
  `definitions_complete` describes only those selections;
  `question_coverage="not_assessed"` never asserts natural-language coverage.

The specialist checks every requested measure, dimension, filter, time role,
population, and output grain. It resolves business ambiguity from the question
and catalog or returns it through the coordinator's clarification workflow.
Several explicitly requested metrics do not inherently imply ambiguity.

A request for a dataset alone returns its instructions and keys, not every field.
Specify `field_names` for grouping, filtering, dates, or additional observations.
Metric dependencies and relationship keys are added automatically. Bridge-only
datasets therefore do not bring their entire schemas into model context.

`browse_semantic_model` supports `dataset`, `field`, `metric`, `relationship`,
and `example` entity kinds. It accepts `query`, a logical `dataset_name` filter,
`time_only`, `offset`, and `limit`. Search one business role at a time: a measure
as a metric, grouping/filter concepts as fields, and dates as time fields.
An empty query with `time_only=true` lists declared dates even when a phrase
such as “monthly” does not overlap their names. Returned examples are curated
context/question examples, **not verified question/SQL pairs**.

### Example

For monthly line revenue by genre:

1. Discover revenue metrics, genre fields, and invoice date fields separately.
2. Resolve `metric_names=["line_revenue"]` and
   `field_names={"genres": ["name"], "invoices": ["invoice_date"]}`.
3. Inspect the declared bridge relationships and any blocking issues. If routes
   are ambiguous, select exact `relationship_names` and resolve again.
4. Generate SQL using the exact sources/expressions, preserving requested scope
   and grain. Supply `metric_names=["line_revenue"]` and the chosen relationship
   names to `execute_sql`.

Self relationships are included for a selected dataset and can also be browsed
or selected explicitly. Alternative routes are reported as compact candidates;
only an unambiguous or explicitly selected route expands into definitions.
Breadth-first route search has a work cap and reports an incomplete search.
A disconnected pair is informational because independent scalar populations
can be valid; it never authorizes an undeclared join.

## Size and version boundaries

Exact context responses have a 12,000 serialized-character budget. Definitions
and instructions are indivisible. Overflow marks definitions incomplete, keeps
bounded repair diagnostics, and requests narrower selections; it never silently
removes required dependencies while reporting success. Optional field omissions
are counted on each dataset.

Browsing has both a 50-item maximum and a 6,000-character budget. It returns a
continuation offset. A single oversized definition produces an explicit omission
rather than a partial SQL expression. Candidate descriptions may be shortened,
because exact definitions must be fetched before use.

Small complete catalogs still fit directly in the SQL specialist's prompt.
Context caching is bounded and keyed by source, model hash, dialect, projection,
and exact request. Catalog changes require a restart. Character budgets are not
model-token guarantees, and repeated tool responses can accumulate; evaluation
should measure total discovery tokens and calls, not just one response's size.

## Expression contract and readiness

`semantic_bindings.py` builds immutable symbol/dependency indexes when a catalog
loads. Discovery and SQL validation reuse those same bindings.

- Fields are scalar physical SQL over their own dataset. Aggregates, windows,
  stars, statements, and subqueries are unsupported field expressions.
- Logical-field composition is not supported. Write the full physical scalar
  expression instead; do not reference another field's logical alias.
- Metrics resolve declared logical fields or unambiguous physical field names.
  Scalar field expressions are expanded with preserved operator precedence;
  expressions include logical dataset aliases and their physical source map.
  Declared operand fields are included too, retaining their semantic instructions.
- Metrics must bind at least one dataset. A relation-free `COUNT(*)` is rejected;
  use a declared non-null key, for example `COUNT(invoices.invoice_id)`, when
  counting that population. Metric-to-metric composition and windows are not
  supported.
- Join keys must resolve to physical columns. Composite and self relationships
  are supported; computed relationship keys are rejected during readiness.
- Backend readiness checks physical columns inside computed expressions as well
  as simple field references. It does not inspect undeclared tables or data.

String-form AI instructions and object-form synonyms, instructions, and examples
are preserved. The pinned OSI version remains 0.1.1. Business units, time meaning,
and aggregation grain remain curated descriptions/instructions; primary keys
are not presented as a complete metric-grain contract.

## SQL execution validation

`execute_sql` validates its final query arguments inside the tool, after any
approval-stage edit and before opening the source execution stream. Existing
read-only validation remains in place. `semantic_sql.py` uses SQLGlot scopes and
qualification rather than regular expressions or physical-name guessing.

It checks:

- declared base tables and columns through aliases, CTEs, and subqueries;
- explicit projections rather than `SELECT *`;
- equality join predicates against declared relationships, including every
  composite key, and the caller's selected routes when supplied;
- declared keys for supported correlated `EXISTS` and membership subqueries;
- possible `SUM`/`AVG` fan-out along selected join paths using declared primary
  keys and explicit grouping/distinct keys in derived tables;
- canonical expression structure for the supplied `metric_names`, including
  embedded metric filters and arithmetic precedence.

Transparent CTE projections and pre-aggregated relationship keys are supported.
Separately aggregated populations may join on identical semantic grouping
dimensions when both sides have proven grouping/distinct uniqueness.
Independent scalar aggregate subqueries may be combined with a cross join.
Unsupported relationship lineage or correlation shapes produce repair feedback;
execution does not fall back to an ungrounded query.

The validator inspects a normalized copy and **does not rewrite the executed SQL**.
Receipts include the selected metrics, matched relationships, and grain warnings.
It does not prove natural-language correctness, infer missing business meaning,
verify declared uniqueness against source values, or detect every possible
aggregation error. Canonical expression checks require the specialist to name
the metrics used; arbitrary descriptive calculations remain supported.

Category value lookup remains a separate, bounded source operation. Metadata
research never performs source-value discovery automatically. Uploaded-file
conversations retain their separate saved-dataset path and do not gain warehouse
access or curated semantics.

## Validation and further improvements

`tests/test_semantic_grounding.py` covers the review's competing-concept queries,
wide tables, unknown bindings, physical expression expansion, relationship roles,
bounded browsing, CTEs, multi-hop fan-out, canonical metric checks, and validation
before execution. A small SQLite population verifies a line-revenue result at the
requested grain. Existing tests cover large catalogs, source isolation, caching,
approval replay, and the complete agent/report workflow.

The next evidence-driven retrieval experiment is a held-out question corpus with
expected semantic roles, required dependencies, reviewed SQL/results, and expected
clarifications. Measure necessary-entity recall, false readiness, final result
accuracy, cumulative tokens, calls, and latency. Compare lexical retrieval and
reformulation with hybrid embeddings under equal budgets. Add a vector index or
verified-query corpus only when curated examples and measured improvements
justify them; no new infrastructure is required by this implementation.
