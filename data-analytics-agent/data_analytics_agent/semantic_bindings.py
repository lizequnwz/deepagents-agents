"""Validated OSI expression bindings, shared by discovery and SQL validation.

Fields are scalar physical SQL over their dataset. Metrics reference declared
logical fields or unambiguous physical field names; metric composition and
relation-free metrics are rejected rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError


@dataclass(frozen=True)
class MetricBinding:
    dependencies: tuple[tuple[str, str], ...]
    expression: str


@dataclass(frozen=True)
class CatalogBindings:
    fields: Mapping[tuple[str, str], str]
    field_dependencies: Mapping[tuple[str, str], tuple[str, ...]]
    metrics: Mapping[str, MetricBinding]
    columns: Mapping[str, frozenset[str]]


def parse_expression(value, dialect):
    statements = parse(value, read=dialect)
    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Expected one SQL expression")
    expression = statements[0]
    if any(
        isinstance(n, (exp.Query, exp.Command, exp.DDL, exp.DML))
        for n in expression.walk()
    ):
        raise ValueError(
            "Subqueries and statements are not supported in semantic expressions"
        )
    return expression


def build_bindings(catalog):
    fields, columns, symbols, field_dependencies = {}, {}, {}, {}
    dialect = catalog.dialect
    for dataset in catalog.datasets.values():
        parsed = {}
        for field in dataset.fields.values():
            try:
                node = parse_expression(field.expression, dialect)
                if node.find(exp.AggFunc, exp.Window, exp.Star):
                    raise ValueError(
                        "Fields must be scalar physical SQL without aggregates or stars"
                    )
                parsed[field.name] = node
            except (ValueError, SqlglotError) as exc:
                raise ValueError(f"Field {dataset.name}.{field.name}: {exc}") from exc
        primitive = {
            node.name.casefold()
            for node in parsed.values()
            if isinstance(node, exp.Column)
        }
        for name, node in parsed.items():
            operands = {c.name.casefold() for c in node.find_all(exp.Column)}
            field_dependencies[dataset.name, name] = tuple(
                sorted(
                    n
                    for n, value in parsed.items()
                    if not isinstance(node, exp.Column)
                    and isinstance(value, exp.Column)
                    and value.name.casefold() in operands
                )
            )
        logical = {name.casefold(): name for name in dataset.fields}
        physical_columns = set()
        for name, node in parsed.items():
            for column in node.find_all(exp.Column):
                if column.table and ".".join(
                    p.name for p in column.parts[:-1]
                ).casefold() not in {
                    dataset.name.casefold(),
                    dataset.source.casefold(),
                    exp.to_table(dataset.source).name.casefold(),
                }:
                    raise ValueError(
                        f"Field {dataset.name}.{name}: reference outside its physical dataset"
                    )
                if (
                    column.name.casefold() in logical
                    and column.name.casefold() not in primitive
                ):
                    raise ValueError(
                        f"Field {dataset.name}.{name}: logical field composition is unsupported; "
                        "write the scalar physical expression explicitly"
                    )
                physical_columns.add(column.name)
            fields[dataset.name, name] = node.sql(dialect=dialect)
            keys = {name.casefold()}
            if isinstance(node, exp.Column):
                keys.add(node.name.casefold())
            for key in keys:
                symbols.setdefault((dataset.name, key), set()).add(name)
        columns[dataset.name] = frozenset(physical_columns)

    for relationship in catalog.relationships:
        for parent, keys in (
            (relationship.from_dataset, relationship.from_columns),
            (relationship.to_dataset, relationship.to_columns),
        ):
            for key in keys:
                if not isinstance(
                    parse_expression(fields[parent, key], dialect), exp.Column
                ):
                    raise ValueError(  # noqa: TRY004 - invalid catalog content, not a caller type error
                        f"Relationship {relationship.name}: join keys must be physical columns; computed keys are unsupported"
                    )

    # Index qualifiers once, including fully qualified physical source names.
    qualifiers = {}
    for dataset in catalog.datasets.values():
        for name in {dataset.name.casefold(), dataset.source.casefold()}:
            qualifiers.setdefault(name, set()).add(dataset.name)
    metrics = {}
    for metric in catalog.metrics.values():
        try:
            node = parse_expression(metric.expression, dialect)
            if node.find(exp.Window):
                raise ValueError(
                    "Window expressions are not supported in canonical metrics"
                )
            dependencies = set()
            for column in list(node.find_all(exp.Column)):
                qualifier = ".".join(part.name for part in column.parts[:-1]).casefold()
                parents = (
                    qualifiers.get(qualifier, set()) if qualifier else catalog.datasets
                )
                candidates = {
                    (parent, name)
                    for parent in parents
                    for name in symbols.get((parent, column.name.casefold()), ())
                }
                # An exact logical name binds before physical aliases.
                exact = {
                    (p, f)
                    for p, f in candidates
                    if f.casefold() == column.name.casefold()
                }
                candidates = exact or candidates
                if len(candidates) != 1:
                    raise ValueError(f"Unresolved or ambiguous field {column.sql()}")
                parent, field = next(iter(candidates))
                dependencies.add((parent, field))
                dependencies.update(
                    (parent, f) for f in field_dependencies[parent, field]
                )
                replacement = parse_expression(fields[parent, field], dialect)
                for physical in replacement.find_all(exp.Column):
                    physical.set("table", exp.to_identifier(parent))
                    physical.set("db", None)
                    physical.set("catalog", None)
                if column is node:
                    node = replacement
                else:
                    if isinstance(replacement, exp.Binary):
                        replacement = exp.Paren(this=replacement)
                    column.replace(replacement)
            if not dependencies:
                raise ValueError(
                    "Metric has no bound dataset; use a declared field, e.g. COUNT(dataset.id), instead of COUNT(*)"
                )
            metrics[metric.name] = MetricBinding(
                tuple(sorted(dependencies)), node.sql(dialect=dialect)
            )
        except (ValueError, SqlglotError) as exc:
            raise ValueError(f"Metric {metric.name}: {exc}") from exc
    return CatalogBindings(
        MappingProxyType(fields),
        MappingProxyType(field_dependencies),
        MappingProxyType(metrics),
        MappingProxyType(columns),
    )
