"""Explicit saved populations and source access for analytical turns."""

from datetime import date, datetime, timedelta
from calendar import monthrange

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlglot.lineage import lineage


class ScopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateRange(ScopeModel):
    column: str = Field(min_length=1)
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.end:
            raise ValueError("Start date must precede end date.")
        if self.end == date.max:
            raise ValueError("Choose an end date before the maximum supported date.")
        return self


class SavedScope(ScopeModel):
    base_result_id: str = Field(min_length=1)
    categories: dict[str, list[str | int | float | bool | None]] = Field(
        default_factory=dict, max_length=10
    )
    dates: DateRange | None = None

    @model_validator(mode="after")
    def bounded(self):
        if any(not values or len(values) > 100 for values in self.categories.values()):
            raise ValueError(
                "Select between one and 100 values for each categorical filter."
            )
        return self


class AnalyticalInput(ScopeModel):
    selected_result_id: str
    input_result_id: str
    label: str
    row_count: int
    snapshot_at: datetime
    grain: str
    scope: SavedScope | None = None


def selectable(result):
    return (
        not result.truncated
        and result.kind != "presentation"
        and (not result.upload_provenance or result.upload_provenance.schema_reviewed)
    )


def dataset_summary(result):
    return {
        "result_id": result.result_id,
        "label": result.short_label,
        "row_count": result.row_count,
        "columns": result.columns,
        "kind": result.kind,
        "complete": not result.truncated,
        "snapshot_at": result.created_at.isoformat(),
        "grain": result.upload_provenance.grain
        if result.upload_provenance and result.upload_provenance.grain
        else "Business grain must be checked against the saved question and calculation.",
        "question": result.originating_question,
        "parent_result_ids": result.parent_result_ids,
    }


def scope_options(result):
    """Bound choices from a complete population; no row preview is an input."""
    if not selectable(result):
        raise ValueError("Choose a complete, reviewed analytical dataset.")
    schema = pq.read_schema(result.parquet_path)
    categories, dates, bounds = {}, [], {}
    with duckdb.connect(config={"enable_external_access": False}) as db:
        db.register("selected", pq.read_table(result.parquet_path))
        for profile in result.profile.columns:
            column = profile.name
            physical = schema.field(column).type
            if pa.types.is_date(physical) or (
                pa.types.is_timestamp(physical) and physical.tz is None
            ):
                dates.append(column)
                name = exp.column(column, quoted=True).sql(dialect="duckdb")
                start, end = db.execute(
                    f"SELECT min({name}), max({name}) FROM selected"
                ).fetchone()
                if start is not None:
                    bounds[column] = {
                        "start": start.isoformat()[:10],
                        "end": end.isoformat()[:10],
                    }
            if profile.distinct_count <= 100 and (
                pa.types.is_string(physical) or pa.types.is_boolean(physical)
            ):
                name = exp.column(column, quoted=True).sql(dialect="duckdb")
                categories[column] = [
                    r[0]
                    for r in db.execute(
                        f"SELECT DISTINCT {name} FROM selected ORDER BY 1 NULLS LAST LIMIT 101"
                    ).fetchall()
                ]
    return {"categories": categories, "date_columns": dates, "date_bounds": bounds}


def _date_units(base, column, results, path=frozenset()):
    """Follow the selected date projection through SQL and saved dependencies."""
    if base.result_id in path:
        raise ValueError(
            "Saved date lineage contains a cycle; choose a verified dataset."
        )
    if not base.executed_sql:
        return set()
    try:
        tree = parse_one(base.executed_sql)
        target = next(
            (
                item
                for item in tree.selects
                if item.alias_or_name.casefold() == column.casefold()
            ),
            None,
        )
        identifier = (
            target.args.get("alias")
            if isinstance(target, exp.Alias)
            else target.this
            if isinstance(target, exp.Column)
            else None
        )
        root = lineage(
            exp.Column(this=identifier.copy()) if identifier is not None else column,
            tree,
        )
    except SqlglotError as exc:
        raise ValueError(
            "The saved date field's SQL lineage cannot be verified. Request a dataset with explicit date grain before filtering."
        ) from exc
    units = {
        trunc.args["unit"].name.lower()
        for node in root.walk()
        for trunc in node.expression.find_all(exp.DateTrunc)
    }
    if base.kind == "saved_sql":
        bindings = {alias.casefold(): key for alias, key in base.sql_bindings.items()}
        for node in root.walk():
            if node.downstream or not isinstance(node.expression, exp.Table):
                continue
            name = exp.to_column(node.name).name
            key = bindings.get(node.expression.name.casefold())
            if key is None:
                raise ValueError(
                    "The saved date field has no exact SQL input binding. Request a dataset with verified date lineage before filtering."
                )
            parent = results.get(key, base.thread_id, source_id=base.source_id)
            if name in parent.columns:
                units.update(
                    _date_units(parent, name, results, path | {base.result_id})
                )
    return units


def validate_aggregate_dates(base, dates, results):
    """Selecting known time buckets must preserve whole periods."""
    start, end = dates.start, dates.end
    for unit in _date_units(base, dates.column, results):
        if unit == "month":
            aligned = start.day == 1 and end.day == monthrange(end.year, end.month)[1]
        elif unit == "quarter":
            aligned = (
                start.day == 1
                and start.month in {1, 4, 7, 10}
                and end.month in {3, 6, 9, 12}
                and end.day == monthrange(end.year, end.month)[1]
            )
        elif unit == "year":
            aligned = (start.month, start.day) == (1, 1) and (end.month, end.day) == (
                12,
                31,
            )
        elif unit in {"day", "hour", "minute", "second", "millisecond", "microsecond"}:
            aligned = True
        else:
            raise ValueError(
                f"Calendar date controls do not support this saved {unit} grain. Request explicit date preparation before applying scope."
            )
        if not aligned:
            raise ValueError(
                f"This saved dataset contains {unit} aggregates. Select whole {unit} periods; finer date boundaries need a dataset with finer grain."
            )


def prepare_input(
    results, thread_id, source_id, selected_result_id, scope=None, *, refreshed=False
):
    base = results.get(selected_result_id, thread_id, source_id=source_id)
    if not selectable(base):
        raise ValueError(
            "Select a complete reviewed dataset; chart samples and incomplete populations cannot be analytical inputs."
        )
    input_result = base
    if scope is not None:
        if scope.base_result_id != selected_result_id:
            raise ValueError("Scope must refer to the selected dataset.")
        options = scope_options(base)
        predicates = []
        for column, values in scope.categories.items():
            if column not in options["categories"]:
                kind = (
                    pq.read_schema(base.parquet_path).field(column).type
                    if refreshed and column in base.columns
                    else None
                )
                if kind is None or not (
                    pa.types.is_string(kind) or pa.types.is_boolean(kind)
                ):
                    raise ValueError(
                        f"{column!r} is not a supported categorical filter. Ask for a saved-data analysis instead."
                    )
            allowed = options["categories"].get(column, [])
            if not refreshed and any(
                not any(type(v) is type(a) and v == a for a in allowed) for v in values
            ):
                raise ValueError(
                    "A selected category is absent from this snapshot. Reload the scope controls."
                )
            field = exp.column(column, quoted=True)
            ordinary = [v for v in values if v is not None]
            choices = []
            if ordinary:
                choices.append(
                    exp.In(
                        this=field.copy(),
                        expressions=[exp.convert(v) for v in ordinary],
                    )
                )
            if None in values:
                choices.append(exp.Is(this=field.copy(), expression=exp.Null()))
            predicates.append(exp.or_(*choices))
        if scope.dates:
            dates = scope.dates
            if dates.column not in options["date_columns"]:
                raise ValueError(
                    "Date filters require a typed date or a timestamp without timezone. Request explicit date preparation for this column."
                )
            validate_aggregate_dates(base, dates, results)
            field = exp.column(dates.column, quoted=True)
            predicates.extend(
                [
                    exp.GTE(
                        this=field.copy(),
                        expression=exp.cast(
                            exp.Literal.string(dates.start.isoformat()), "DATE"
                        ),
                    ),
                    exp.LT(
                        this=field.copy(),
                        expression=exp.cast(
                            exp.Literal.string(
                                (dates.end + timedelta(days=1)).isoformat()
                            ),
                            "DATE",
                        ),
                    ),
                ]
            )
        if predicates:
            query = (
                exp.select(*(exp.column(c, quoted=True) for c in base.columns))
                .from_("selected")
                .where(exp.and_(*predicates))
                .sql(dialect="duckdb")
            )
            with duckdb.connect(config={"enable_external_access": False}) as db:
                db.register("selected", pq.read_table(base.parquet_path))
                input_result = results.save_batches(
                    db.execute(query).to_arrow_reader(8192),
                    thread_id=thread_id,
                    source_id=source_id,
                    executed_sql=query,
                    originating_question=base.originating_question,
                    purpose="Selected scope: " + base.short_label,
                    kind="saved_sql",
                    parent_result_ids=[base.result_id],
                    sql_bindings={"selected": base.result_id},
                )
    summary = dataset_summary(base)
    return AnalyticalInput(
        selected_result_id=base.result_id,
        input_result_id=input_result.result_id,
        label=base.short_label,
        row_count=input_result.row_count,
        snapshot_at=base.created_at,
        grain=summary["grain"],
        scope=scope,
    )


def descends_from(results, result_id, root_id, thread_id, source_id, seen=None):
    seen = set() if seen is None else seen
    if result_id in seen:
        return False
    seen.add(result_id)
    item = results.get(result_id, thread_id, source_id=source_id)
    return result_id == root_id or any(
        descends_from(results, parent, root_id, thread_id, source_id, seen)
        for parent in item.parent_result_ids
    )


def _within_inputs(
    results, result_id, roots, thread_id, source_id, memo, path=frozenset()
):
    if result_id in path:
        return False
    if result_id in memo:
        return memo[result_id]
    item = results.get(result_id, thread_id, source_id=source_id)
    within = (
        result_id in roots
        or bool(item.parent_result_ids)
        and all(
            _within_inputs(
                results, parent, roots, thread_id, source_id, memo, path | {result_id}
            )
            for parent in item.parent_result_ids
        )
    )
    memo[result_id] = within
    return within


def check_inputs(results, runs, run_id, result_ids):
    """Enforce selected populations at execution, including edited code bindings."""
    run = runs.get(run_id)
    roots = (
        runs.fresh_results(run_id)
        if run.fresh_source_required
        else (
            [run.analytical_input.input_result_id]
            if run.analytical_input and not run.source_expansion_allowed
            else []
        )
    )
    if run.fresh_source_required and not roots:
        raise ValueError(
            "This is a fresh run. Execute source SQL before using saved inputs."
        )
    if roots:
        memo, allowed = {}, set(roots)
        for key in result_ids:
            if not _within_inputs(
                results, key, allowed, run.thread_id, run.source_id, memo
            ):
                raise ValueError(
                    "This dataset lies outside the explicitly selected population. Ask the coordinator to request source expansion before retrieving broader or newer data."
                )


def require_refreshed_input(runs, run_id):
    run = runs.get(run_id)
    if (
        run.fresh_source_required
        and run.analytical_input
        and run.analytical_input.input_result_id not in runs.fresh_results(run_id)
    ):
        raise ValueError(
            "Regenerate the selected dataset, then call bind_refreshed_input to reapply its scope before publishing."
        )


def scope_description(value: AnalyticalInput):
    text = f"Selected saved dataset: {value.label or value.selected_result_id}. Supplied population: {value.row_count:,} rows. Snapshot saved: {value.snapshot_at.isoformat()}. Grain: {value.grain.rstrip('.')}."
    if value.scope:
        filters = [
            f"{column}: {', '.join('missing' if v is None else str(v) for v in values)}"
            for column, values in value.scope.categories.items()
        ]
        if value.scope.dates:
            dates = value.scope.dates
            filters.append(
                f"{dates.column}: {dates.start.isoformat()} through {dates.end.isoformat()} (inclusive)"
            )
        if filters:
            text += " Applied filters: " + "; ".join(filters) + "."
    return (
        text
        + " Source cutoff/completeness is unknown unless explicitly declared; snapshot save time is not a source cutoff."
    )
