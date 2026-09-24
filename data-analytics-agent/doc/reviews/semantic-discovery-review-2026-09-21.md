# Semantic discovery engineering review

Date: 21 September 2026. Scope: current repository implementation, metadata-only reproductions, and primary-source engineering references. No production data, warehouse queries, or live LLM evaluations were used. Runtime code is unchanged.

> Implementation note: this is the pre-change assessment. The current behavior is
> documented in [semantic discovery](../development/semantic-discovery.md), with
> regression coverage in `tests/test_semantic_grounding.py`. The saved probe output
> and script below preserve the original failure behavior.

## Recommendation

Keep the source-bound catalog and progressive discovery. Replace the current top-five search-to-context shortcut with **candidate retrieval → explicit semantic selection → dependency-complete context assembly → SQL grounding validation**. Implement this inside the existing SQL specialist and semantic modules. A larger prompt or a vector database alone would not correct the demonstrated failures.

The central issue is that `complete=true` currently means roughly “some selected definitions were serialized without a reference error.” It does not mean the question has adequate semantic coverage, its metric is resolved, or its joins are appropriate. Retrieval can omit essential definitions while reporting no omissions.

## What already works

- One immutable, source-bound catalog with source/model/dialect/projection-aware context caching.
- Business and physical projections; source execution remains with text-to-SQL.
- Exact definitions, global/dataset instructions, primary keys, and declared join keys are available.
- Multi-hop bridge discovery and explicit alternative-path diagnostics.
- A 12,000-character context budget; expressions and instructions are not cut mid-definition by the context builder.
- Paginated browsing and a separate governed category-value lookup.
- Inline exact context for small catalogs avoids needless discovery calls.

These are useful foundations. The weaknesses arise in selection, dependency resolution, relationship semantics, and the meaning of completeness.

## Findings

### 1. High: mixed top-five retrieval loses necessary concepts

`semantic_context.py:208–216` searches datasets, fields, and metrics together with a fixed limit of five. `semantic.py:625–730` uses lexical overlap; tied scores sort by entity kind and then names. Multiple fields from one dataset consume multiple slots before dataset deduplication. Search scores/reasons and excluded candidates are not returned in context.

Reproduced against the shipped Chinook catalog:

| Question | Actual context | Risk |
|---|---|---|
| revenue by country | `line_revenue`, customers, employees, invoices, invoice_lines; `complete=true`; no ambiguity | Canonical `total_revenue` is omitted; employee country becomes a candidate despite an unresolved billing-versus-customer-country choice. |
| monthly revenue by genre | No metrics; `complete=true` | The generator must recover the intended revenue definition and date from field/global instructions. |
| sales by artist | Empty definitions after exceeding the budget | Irrelevant matches and expansion consume the entire budget even in this small model. |

The global instructions partly mitigate these examples: they mention invoice and line revenue. They do not make the returned selection complete or guarantee correct SQL. These probes establish retrieval defects, not measured LLM answer error rates.

**Fix:** retrieve candidates separately for the requested measure, grouping dimensions, filters, and time role. Deduplicate/group candidates before applying limits; reserve space for metric candidates. Preserve qualified field identities and score/reason metadata. Use exact names and synonyms first, then lexical ranking with document-frequency weighting and parent diversity. Let the existing specialist reformulate missed concepts. Measure paraphrase recall before deciding whether embeddings help.

### 2. High: completeness conflates serialization and semantic readiness

`semantic_context.py:339` ignores `ambiguities` and `disconnected`; there is no question-coverage check. An exact dataset or metric selection also disables question search entirely (`:208`): specifying `dataset_names=["invoices"]` with “revenue by genre” returns invoices alone, no metric, and `complete=true`.

The opposite ambiguity error also occurs: every search selecting multiple metrics flags ambiguity, even when the question intentionally asks for several measures.

**Fix:** replace the overloaded flag with separate `definitions_complete`, requirement coverage, and `blocking_issues`. Exact selection should explicitly be a definition-resolution operation, not imply that the accompanying question is covered. Track each requested semantic role as resolved, ambiguous, or missing. Disconnection blocks a required join, not unrelated scalar queries; multiple explicitly requested metrics are not inherently ambiguous. Coverage is relative to the specialist's explicit interpretation, not proof of natural-language understanding.

### 3. High: self joins and relationship roles cannot be resolved through the tools

Join expansion uses pairs of distinct dataset names (`semantic_context.py:280`). The shipped `employees_to_managers` self relationship is never returned for targeted employee discovery. `browse_semantic_model` can list only datasets or fields (`semantic_tools.py:68–101`), so it cannot recover this relationship. There is no exact relationship-selection parameter.

For ordinary joins, `_paths` returns the shortest route plus the first distinct route found by depth-first traversal, not necessarily the next-shortest or business-relevant route. All returned routes expand into context. The 2,000-step cap is explicit, which is good, but arbitrary alternatives can introduce unnecessary tables and budget pressure. The caller cannot select an accepted path to remove alternatives.

**Fix:** expose bounded relationship browsing and exact relationship selection, including self edges and role aliases. Return compact route candidates first; expand only selected routes. Use the selected measure's base grain to orient the path. Ask for business clarification only when the catalog and question cannot distinguish materially different roles. Do not infer that shortest means correct.

### 4. High: field projection is manual, and overflow discards useful progress

`semantic_context.py:310–330` includes every field unless the caller supplies a field list for that dataset. This includes datasets added solely for a metric or bridge. On overflow (`:350–363`), the response drops all definitions and the detailed ambiguity/reference diagnostics, returning a generic refinement instruction.

A synthetic invoice dataset with 80 unrelated documented fields causes a request for `total_revenue` alone to fail. The same request succeeds with `field_names={"invoices": []}`, which retains only `total` and `invoice_id` automatically. The necessary dependency information already exists; the default projection fails to use it.

**Fix:** default to selected fields plus transitive dependencies, join keys, primary keys, and applicable instructions. Bridge-only datasets usually need keys and relationship semantics, not every field. Keep optional candidate descriptions/examples outside the mandatory definition budget. If mandatory context still cannot fit, return a structured blocker, diagnostics, and a concrete refinement path. Never drop required definitions and proceed as if ready.

Browsing needs a serialized-size limit as well as an item count: 25 or 50 long field descriptions/expressions are not a bounded prompt. Preserve indivisible definitions, page them, and explicitly report any single definition that cannot fit. Measure actual model tokens as well as serialized characters and cumulative discovery volume; a per-call cap does not bound the conversation.

### 5. High: metric dependencies are inferred incompletely

`semantic_context.py:248–277` scans metric expression columns and compares their names with every field's logical name or entire expression text. It does not recursively resolve logical field expressions, derived metrics, expression scopes, or an explicit metric base relation. It does not compile logical expressions into physical SQL.

Synthetic probes demonstrate:

- `COUNT(*)` returns a metric with no dataset and `complete=true`.
- `SUM(invoices.adjusted)` with `adjusted = net_amount * 0.9` and logical `net_amount = Total` returns `adjusted` and the primary key, omits `net_amount`, and reports complete.

The second example exercises an undefined boundary: if field expressions are physical SQL only, the loader should reject that model; if logical field references are supported, they need recursive resolution. Silently accepting either interpretation is the defect. Similarly, `COUNT(*)` needs declared relation binding or a load-time diagnostic.

**Fix:** define and validate the supported expression grammar. Build exact logical/physical symbol indexes and dependency edges at catalog load time using existing SQLGlot AST facilities. Resolve references with scope and dialect awareness; detect ambiguous bindings and cycles. Require explicit base relation where expressions cannot establish one. Support declared composition correctly or reject it clearly, without heuristic fallback. Context assembly should traverse validated dependencies rather than rescan the entire catalog for every metric column.

### 6. High: SQL execution has no catalog-grounding check

`create_execute_sql_tool` receives no semantic catalog or selected context (`agents/text_to_sql/tools.py:85`). `backends/validation.py` checks structural read-only SQL, not declared objects, selected relationships, metric definitions, or aggregate grain. The specialist prompt says to avoid guessing and fan-out, but execution does not independently check these properties.

Consequently, missing discovery can produce executable SQL with the wrong business meaning. Backend syntax errors can repair unknown columns; they cannot detect an invoice total multiplied by line joins.

**Fix:** add scope-aware grounding validation at the source-execution boundary. Resolve base tables and columns through CTEs/aliases; check them against catalog bindings and the resolved selection. Check declared join predicates and metric expansion for the supported grammar. Return specific missing definitions or incompatible relationships to the specialist for repair. Validate the actual query after any human edit. A selected-context identifier, if needed across calls, should bind to source/model revision in existing assignment state; a new storage service is unnecessary.

Do not claim that an AST validator proves business correctness. Fan-out checks require declared/inferred uniqueness, measure grain, and supported aggregation patterns. Unknown cardinality must remain unknown. Multi-fact comparisons often need separate aggregation before combination; do not ban every one-to-many join, since some are intentional and valid at the requested grain.

### 7. Medium: curated semantics are partly lost or remain unstructured

`_ai_context` reads examples, but field/dataset/metric loading discards them. Catalog-level examples are retained but not rendered by the context/overview functions. String-form `ai_context` is ignored by the helper. The current dataclasses have no explicit metric base grain, default aggregation time, unit, or relationship cardinality. Some of this meaning exists in descriptions/instructions; `grain` in the context is simply a copy of `primary_key`, not a validated aggregation contract.

**Fix:** preserve the context forms supported by the project's declared OSI version and explicitly validate unsupported forms. Make selected examples retrievable. Keep question-only examples distinct from verified question/SQL pairs. Add structured semantics only for concrete compiler/validator needs, using the project's pinned OSI contract and a documented extension where necessary. Do not invent new standard fields or infer currency, temporal completeness, or verified uniqueness from names.

### 8. Medium: current tests establish structure, not retrieval sufficiency

The large-catalog test uses an exact metric name among unrelated datasets. It does not exercise competing synonyms, common field names, paraphrases, wide tables, role-playing dates, self joins, or multi-fact aggregation. Existing tests correctly check bridge inclusion, budgets, and caching but allow the failures above.

The focused suite passed: **34 tests** across semantic discovery, semantic loading, and SQL safety. Ten additional metadata probes reproduced current behavior, including a successful narrow-projection control. These probes are review evidence, not regression assertions for the desired implementation.

## Proposed end-to-end design

1. **Interpret the assignment inside text-to-SQL.** Identify the requested measures, dimensions, population/filters, time role/window, and output grain. Reuse the coordinator's business brief; do not add a new agent or repeat its work.
2. **Search compact candidates by role.** Return logical IDs, short descriptions, match reasons, and ambiguity/missing indicators. Do not expand all matching datasets.
3. **Resolve exact selections and relationships.** The specialist chooses catalog definitions; application code computes dependency closure and suitable declared routes. Missing business meaning returns to the existing clarification flow.
4. **Assemble one bounded SQL context.** Include selected physical expressions, binding information, required fields, selected joins, grain/aggregation rules, and applicable instructions. Retrieve small relevant verified examples only when available and useful.
5. **Generate and validate SQL.** Check supported structural and semantic constraints against the resolved selection, repair with precise diagnostics, then execute through existing approval and result-saving paths.

The complete catalog stays in application memory/indexes. Only candidates and the selected dependency closure enter model context. Keep the small-catalog inline optimization, subject to the same semantic validity checks.

## Implementation order

**First increment — correct progressive discovery.** Add adversarial regression fixtures; separate definition completeness from question coverage; fix candidate diversity and metric starvation; expose metrics/relationships through bounded browsing; support self relationships and chosen paths; default to narrow dependency projection; preserve overflow diagnostics. Keep the current agent topology and dependencies.

**Second increment — dependable binding and execution.** Define the expression contract, build indexed dependencies during loading, reject unresolved/cyclic bindings, and add source-bound SQL grounding validation. Start with the expression and join patterns the shipped models actually use, with explicit diagnostics for unsupported forms. This is a durable supported contract, not a second heuristic path.

**Third increment — measured retrieval improvements.** Evaluate lexical retrieval, query reformulation, and hybrid retrieval on the same held-out questions under equal context budgets. Add semantic embeddings only if they improve necessary-entity recall and final answer accuracy enough to justify indexing/versioning costs. Retrieve verified examples by source and relevant semantic objects; do not promote unreviewed successful executions into ground truth.

## Evaluation and release criteria

Build a curated question set with expected metric, dimension/time roles, valid join paths, mandatory dependency sets, and expected result or expected clarification. Include unrelated schema growth and deliberately similar names/descriptions.

Measure separately:

- Necessary-entity recall before selection, and precision/size after selection.
- Missing required dependencies and false readiness on ambiguous or unsupported cases.
- Total semantic tokens, discovery calls, overflow recovery, and latency.
- Executable SQL rate and result equivalence to reviewed SQL; executable alone is insufficient.
- Correct clarification for materially ambiguous meanings.

Use deterministic fixture databases to make wrong grain, incorrect dates, missing filters, and fan-out produce different results. Compare results rather than SQL strings. Keep verified-example training cases separate from held-out evaluation. Require all deterministic dependency/readiness regression cases to pass and no small-model regression. Set statistical accuracy/latency targets after measuring the baseline; this review does not establish an overall accuracy percentage.

## Established approaches informing the recommendation

- [AWS/Cisco enterprise NL-to-SQL](https://aws.amazon.com/blogs/machine-learning/enterprise-grade-natural-language-to-sql-generation-using-llms-balancing-accuracy-latency-and-scale/) scopes prompts to a relevant data domain with descriptions, rules, join hints, and examples. Apply this principle within the already selected source; a new cross-source router is unnecessary here.
- [dbt MetricFlow join logic](https://docs.getdbt.com/docs/build/join-logic) uses an entity graph and entity types to govern joins and avoid fan-out/chasm problems. Adopt explicit relationship/grain reasoning; do not substitute undirected connectivity for correctness or assume MetricFlow directly consumes this OSI implementation.
- [Snowflake verified query repository](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository) retrieves relevant reviewed question/SQL pairs. This supports a small governed example corpus and evaluation set, rather than placing all examples in every prompt.

These are architectural precedents, not performance evidence for this repository. Full semantic-engine adoption would need a separate compatibility and product-scope evaluation; it is larger than the changes needed to address the demonstrated discovery gaps.

## Reproduction

- [Probe script](semantic-discovery-probes-2026-09-21.py)
- [Recorded metadata results](semantic-discovery-probes-2026-09-21.json)

From the repository root:

```sh
.venv/bin/python -m pytest tests/test_semantic_discovery.py tests/test_semantic_model.py tests/test_sql_safety.py
PYTHONPATH=. .venv/bin/python doc/reviews/semantic-discovery-probes-2026-09-21.py
```

The script asserts the reviewed failure behavior and should be replaced or updated once those behaviors change. Synthetic catalogs are created in memory; source files and data are not modified.
