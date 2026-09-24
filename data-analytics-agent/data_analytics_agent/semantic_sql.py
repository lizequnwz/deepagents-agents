"""Scope-aware catalog grounding for source SQL; never rewrites executed SQL.

Checks declared base objects, equality joins, selected canonical expressions,
plus direct aggregate fan-out. It is not a proof of business correctness.
"""

from __future__ import annotations

from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.schema import MappingSchema

from data_analytics_agent.backends.validation import (
    SQLValidationError,
    validate_readonly_sql,
)
from data_analytics_agent.semantic_bindings import parse_expression


def _table_key(table):
    return tuple(p.name.casefold() for p in table.parts)


def _scalar(scope):
    node = scope.expression
    return (
        isinstance(node, exp.Select)
        and not node.args.get("group")
        and (
            not node.args.get("from_") or any(s.find(exp.AggFunc) for s in node.selects)
        )
        and not any(s.find(exp.Window) for s in node.selects)
    )


def validate_semantic_sql(query, catalog, *, metric_names=(), relationship_names=None):
    statement = validate_readonly_sql(query, dialect=catalog.dialect)
    if any(
        isinstance(s, exp.Star) or (isinstance(s, exp.Column) and s.is_star)
        for select in statement.find_all(exp.Select)
        for s in select.selects
    ):
        raise SQLValidationError("Select explicit declared fields instead of SELECT *.")
    metrics = list(dict.fromkeys(metric_names))
    unknown = set(metrics) - set(catalog.metrics)
    relationships = {r.name: r for r in catalog.relationships}
    unknown |= set(relationship_names or ()) - set(relationships)
    if unknown:
        raise SQLValidationError(
            f"Unknown exact semantic selections: {sorted(unknown)}"
        )
    allowed = (
        set(relationships) if relationship_names is None else set(relationship_names)
    )
    bindings = catalog.bindings
    tables = {}
    schema = MappingSchema(dialect=catalog.dialect)
    for dataset in catalog.datasets.values():
        table = exp.to_table(dataset.source)
        key = _table_key(table)
        tables.setdefault(key, []).append(dataset.name)
    for names in tables.values():
        schema.add_table(
            exp.to_table(catalog.datasets[names[0]].source),
            {c: "UNKNOWN" for name in names for c in bindings.columns[name]},
        )
    try:
        # Validate base objects before qualification can infer unknown schema.
        for scope in traverse_scope(statement):
            for source in scope.sources.values():
                if isinstance(source, exp.Table) and _table_key(source) not in tables:
                    raise SQLValidationError(
                        f"Undeclared physical source {source.sql()}; discover an exact catalog source."
                    )
        qualified = qualify(
            statement.copy(),
            dialect=catalog.dialect,
            schema=schema,
            infer_schema=False,
            expand_stars=False,
        )
        scopes = list(traverse_scope(qualified))
    except SqlglotError as exc:
        raise SQLValidationError(
            f"SQL field grounding failed: {exc}. Retrieve exact field definitions."
        ) from exc

    def origin(scope, column, seen=frozenset()):
        """Trace only transparent column projections; never guess computed lineage."""
        key = (id(scope), column.table, column.name)
        if key in seen:
            return None
        source = scope.sources.get(column.table)
        if source is None and scope.parent is not None:
            return origin(scope.parent, column, seen | {key})
        if isinstance(source, exp.Table):
            names = tables.get(_table_key(source), [])
            if len(names) != 1:
                names = [n for n in names if n.casefold() == column.table.casefold()]
            return (names[0], column.name.casefold()) if len(names) == 1 else None
        if isinstance(source, Scope) and isinstance(source.expression, exp.Select):
            for select in source.expression.selects:
                if select.alias_or_name.casefold() == column.name.casefold():
                    inner = select.this if isinstance(select, exp.Alias) else select
                    if isinstance(inner, exp.Column):
                        return origin(source, inner, seen | {key})
        return None

    def normalized(node, scope=None):
        copy = node.copy()
        for column in copy.find_all(exp.Column):
            resolved = origin(scope, column) if scope else (column.table, column.name)
            if resolved is None:
                return None
            column.set("table", exp.to_identifier(resolved[0].casefold()))
            column.set("this", exp.to_identifier(resolved[1].casefold()))
            column.set("db", None)
            column.set("catalog", None)
        # Compare normalized ASTs, preserving operator structure while ignoring
        # redundant parentheses introduced by safe field-expression expansion.
        for paren in list(copy.find_all(exp.Paren)):
            if paren is copy:
                copy = paren.this
            else:
                paren.replace(paren.this)
        return copy

    def match_pairs(pairs):
        matched = []
        for aliases, actual in pairs.items():
            for relation in relationships.values():
                if relation.name not in allowed:
                    continue
                expected = set()
                for f, t in zip(
                    relation.from_columns, relation.to_columns, strict=True
                ):
                    a = parse_expression(
                        bindings.fields[relation.from_dataset, f], catalog.dialect
                    )
                    b = parse_expression(
                        bindings.fields[relation.to_dataset, t], catalog.dialect
                    )
                    if not isinstance(a, exp.Column) or not isinstance(b, exp.Column):
                        break
                    expected.add(
                        (
                            (relation.from_dataset, a.name.casefold()),
                            (relation.to_dataset, b.name.casefold()),
                        )
                    )
                else:
                    for reverse in (False, True):
                        oriented = (
                            {(b, a) for a, b in expected} if reverse else expected
                        )
                        if oriented <= actual:
                            matched.append((aliases, relation, reverse))
        return matched

    def unique_source(scope, alias, parent, keys):
        source = scope.sources.get(alias)
        if isinstance(source, exp.Table):
            pk = catalog.datasets[parent].primary_key
            return bool(pk) and set(pk) <= set(keys)
        if not isinstance(source, Scope) or not isinstance(
            source.expression, exp.Select
        ):
            return False
        selected = source.expression
        join_origins = {
            (
                parent,
                parse_expression(
                    bindings.fields[parent, k], catalog.dialect
                ).name.casefold(),
            )
            for k in keys
        }
        group = selected.args.get("group")
        if group:
            origins = {
                origin(source, c) if isinstance(c, exp.Column) else None
                for c in group.expressions
            }
            return bool(origins) and None not in origins and origins <= join_origins
        if selected.args.get("distinct"):
            expressions = [
                c.this if isinstance(c, exp.Alias) else c for c in selected.selects
            ]
            origins = {
                origin(source, c) if isinstance(c, exp.Column) else None
                for c in expressions
            }
            return bool(origins) and None not in origins and origins <= join_origins
        if not selected.args.get("joins") and len(source.selected_sources) == 1:
            inner_alias = next(iter(source.selected_sources))
            return unique_source(source, inner_alias, parent, keys)
        return False

    used, warnings = set(), set()
    for scope in scopes:
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue
        transitions = {}
        joins = select.args.get("joins") or []
        for join in joins:
            right = join.this.alias_or_name
            predicate = join.args.get("on")
            if (
                predicate is None
                and join.args.get("kind") == "CROSS"
                and all(
                    isinstance(source, Scope) and _scalar(source)
                    for _, source in scope.selected_sources.values()
                )
            ):
                continue
            if predicate is None:
                raise SQLValidationError(
                    "Join needs an explicit ON predicate over declared relationship keys."
                )
            pairs = {}
            for condition in (
                predicate.flatten() if isinstance(predicate, exp.And) else [predicate]
            ):
                if not isinstance(condition, exp.EQ):
                    continue
                left, other = condition.this, condition.expression
                if (
                    not isinstance(left, exp.Column)
                    or not isinstance(other, exp.Column)
                    or left.table == other.table
                ):
                    continue
                if right not in (left.table, other.table):
                    continue
                if other.table != right:
                    left, other = other, left
                a, b = origin(scope, left), origin(scope, other)
                if a and b:
                    pairs.setdefault((left.table, other.table), set()).add((a, b))
            matched = match_pairs(pairs)
            if not matched:
                # Separately aggregated populations can share a grouping dimension
                # without requiring an invented self relationship in the catalog.
                for aliases, actual in pairs.items():
                    if not actual or any(a != b for a, b in actual):
                        continue
                    origins = {a for a, _ in actual}
                    parents = {parent for parent, _ in origins}
                    if len(parents) != 1 or not all(
                        isinstance(scope.sources.get(a), Scope) for a in aliases
                    ):
                        continue
                    parent = next(iter(parents))
                    keys = [
                        name
                        for name in catalog.datasets[parent].fields
                        if isinstance(
                            (
                                node := parse_expression(
                                    bindings.fields[parent, name], catalog.dialect
                                )
                            ),
                            exp.Column,
                        )
                        and (parent, node.name.casefold()) in origins
                    ]
                    if keys and all(
                        unique_source(scope, alias, parent, keys) for alias in aliases
                    ):
                        transitions.setdefault(aliases[0], []).append(
                            (aliases[1], True)
                        )
                        transitions.setdefault(aliases[1], []).append(
                            (aliases[0], True)
                        )
                        break
                else:
                    raise SQLValidationError(
                        "Join is not grounded in the selected declared relationships. Retrieve/select the correct relationship and all composite keys; computed join keys are unsupported."
                    )
            for aliases, relation, reverse in matched:
                used.add(relation.name)
                parents = (
                    (relation.to_dataset, relation.from_dataset)
                    if reverse
                    else (relation.from_dataset, relation.to_dataset)
                )
                keys = (
                    (relation.to_columns, relation.from_columns)
                    if reverse
                    else (relation.from_columns, relation.to_columns)
                )
                for index in (0, 1):
                    opposite = 1 - index
                    unique = unique_source(
                        scope, aliases[opposite], parents[opposite], keys[opposite]
                    )
                    transitions.setdefault(aliases[index], []).append(
                        (aliases[opposite], unique)
                    )
        # Check multiplicity along the whole selected route, not just the first hop.
        for aggregate in select.find_all(exp.Sum, exp.Avg):
            if aggregate.find_ancestor(exp.Select) is not select:
                continue
            for alias in {c.table for c in aggregate.find_all(exp.Column)}:
                pending, visited = [alias], set()
                while pending:
                    current = pending.pop()
                    visited.add(current)
                    for other, unique in transitions.get(current, []):
                        if other in visited:
                            continue
                        if not unique:
                            raise SQLValidationError(
                                "Aggregate can fan out across a join whose opposite keys are not declared unique. Aggregate at the required grain before joining, or use the appropriate line-level metric."
                            )
                        pending.append(other)
        if any(
            not unique for neighbors in transitions.values() for _, unique in neighbors
        ):
            warnings.add(
                "Join uniqueness is established from declared keys or grouping; verify output grain."
            )
        if scope.is_correlated_subquery:
            where = select.args.get("where")
            predicate = where.this if where else None
            pairs, covered = {}, set()
            for condition in (
                predicate.flatten() if isinstance(predicate, exp.And) else [predicate]
            ):
                if not isinstance(condition, exp.EQ):
                    continue
                a, b = condition.this, condition.expression
                if not isinstance(a, exp.Column) or not isinstance(b, exp.Column):
                    continue
                external = {c.table for c in scope.external_columns}
                if (a.table in external) == (b.table in external):
                    continue
                resolved = origin(scope, a), origin(scope, b)
                if all(resolved):
                    pairs.setdefault((a.table, b.table), set()).add(resolved)
            matched = match_pairs(pairs)
            for aliases, relation, reverse in matched:
                used.add(relation.name)
                for col in scope.external_columns:
                    if col.table in aliases:
                        covered.add(col.sql())
            if not matched or any(
                col.sql() not in covered for col in scope.external_columns
            ):
                raise SQLValidationError(
                    "Correlated subquery must use declared equality relationship keys in WHERE; rewrite unsupported correlations as explicit declared joins."
                )
        # IN subqueries are semi-joins too; do not allow them to bypass grounding.
        for predicate in select.find_all(exp.In):
            if predicate.find_ancestor(
                exp.Select
            ) is not select or not predicate.args.get("query"):
                continue
            inner = predicate.args["query"].this
            inner_scope = next((s for s in scopes if s.expression is inner), None)
            if (
                not inner_scope
                or len(inner.selects) != 1
                or not isinstance(predicate.this, exp.Column)
            ):
                raise SQLValidationError(
                    "Use EXISTS with declared equality keys for this subquery filter."
                )
            projection = inner.selects[0]
            projection = (
                projection.this if isinstance(projection, exp.Alias) else projection
            )
            if not isinstance(projection, exp.Column):
                raise SQLValidationError(
                    "Subquery membership must select a declared relationship key."
                )
            a, b = origin(scope, predicate.this), origin(inner_scope, projection)
            matched = match_pairs({("outer", "inner"): {(a, b)}}) if a and b else []
            if not matched:
                raise SQLValidationError(
                    "Subquery membership is not grounded in declared relationship keys."
                )
            used.update(relation.name for _, relation, _ in matched)
    active, pending = set(), [scopes[-1]] if scopes else []
    while pending:
        scope = pending.pop()
        if scope in active:
            continue
        active.add(scope)
        pending.extend(
            s for _, s in scope.selected_sources.values() if isinstance(s, Scope)
        )
        pending.extend(scope.subquery_scopes)
        pending.extend(scope.union_scopes)
    for name in metrics:
        expected = normalized(
            parse_expression(bindings.metrics[name].expression, catalog.dialect)
        )
        found = any(
            normalized(node, scope) == expected
            for scope in active
            for node in scope.expression.walk()
            if node.find_ancestor(exp.Select) is scope.expression
            or node is scope.expression
        )
        if not found:
            raise SQLValidationError(
                f"Selected metric {name!r} does not match its canonical expression. Retrieve its definition and preserve its aggregation and filters."
            )
    return {
        "metric_names": metrics,
        "relationship_names": sorted(used),
        "warnings": sorted(warnings),
    }
