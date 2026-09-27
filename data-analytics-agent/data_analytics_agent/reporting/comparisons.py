"""Deterministic period comparisons over one complete, shared-scope snapshot.

These checks establish row/grain consistency, not correctness of arbitrary source
SQL. Catalog meaning and source completeness are separate evidence requirements.
"""

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PeriodComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    metric_ref: str = Field(
        min_length=1,
        description="Exact semantic metric name, or reviewed upload measure name.",
    )
    population: str = Field(
        min_length=1,
        description="Shared population and filters of this one saved snapshot.",
    )
    grain: list[str] = Field(
        min_length=1,
        description="Columns uniquely identifying each aggregate row, including the period column.",
    )
    period_column: str = Field(min_length=1)
    current_period: str = Field(min_length=1)
    baseline_period: str = Field(min_length=1)
    baseline_row_index: int = Field(ge=0)
    unit_column: str | None = Field(
        default=None,
        description="Saved unit/currency label column. Omit when units are unspecified; no currency will be inferred.",
    )
    numerator_column: str | None = None
    denominator_column: str | None = Field(
        default=None,
        description="For an already computed rate/share, name the saved denominator column; values are disclosed, never silently recomputed.",
    )
    rate_scale: Literal[1, 100] = 1
    completeness: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def distinct_periods(self):
        if bool(self.numerator_column) != bool(self.denominator_column):
            raise ValueError(
                "Rate comparisons require both numerator and denominator columns."
            )
        if self.current_period == self.baseline_period:
            raise ValueError("Current and baseline periods must differ.")
        if self.period_column not in self.grain or len(set(self.grain)) != len(
            self.grain
        ):
            raise ValueError(
                "Grain must contain distinct columns including the period column."
            )
        return self


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError(
            "Comparison values must be finite numbers, not missing values or booleans."
        )
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Comparison values must be numeric.") from exc
    if not result.is_finite():
        raise ValueError("Comparison values must be finite.")
    return result


def resolve_comparison(metric, result):
    spec = metric.comparison
    if result.truncated or result.kind == "presentation":
        raise ValueError(
            "A comparison requires complete analytical evidence, not a truncated or display dataset."
        )
    bound_metric = result.metric_columns.get(metric.column.casefold())
    if bound_metric and bound_metric != spec.metric_ref:
        raise ValueError(
            "Comparison metric_ref does not match the canonical metric bound to this saved column."
        )
    required = {*spec.grain, metric.column}
    if spec.unit_column:
        required.add(spec.unit_column)
    if spec.numerator_column:
        required.add(spec.numerator_column)
    if spec.denominator_column:
        required.add(spec.denominator_column)
    if not required <= set(result.columns):
        raise ValueError(
            f"Comparison columns are absent: {sorted(required - set(result.columns))}"
        )
    import duckdb

    quote = lambda name: '"' + name.replace('"', '""') + '"'
    with duckdb.connect() as db:
        db.read_parquet(result.parquet_path).create_view("evidence")
        keys = ",".join(map(quote, spec.grain))
        if db.execute(
            f"SELECT 1 FROM evidence GROUP BY {keys} HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone():
            raise ValueError(
                "Comparison grain is duplicated. Reshape or repair the source join before comparing."
            )
    current_rows = result.read_rows(1, metric.row_index)
    baseline_rows = result.read_rows(1, spec.baseline_row_index)
    if not current_rows or not baseline_rows:
        raise ValueError("Comparison row is outside the saved evidence.")
    current, baseline = current_rows[0], baseline_rows[0]
    unit = "source units"
    if spec.unit_column:
        unit = current[spec.unit_column]
        if (
            not isinstance(unit, str)
            or not unit.strip()
            or unit != baseline[spec.unit_column]
        ):
            raise ValueError("Current and baseline units are missing or different.")
    if metric.prefix or metric.suffix:
        raise ValueError(
            "Comparison units must come from unit_column; omit free-text prefix/suffix."
        )
    if (
        str(current[spec.period_column]) != spec.current_period
        or str(baseline[spec.period_column]) != spec.baseline_period
    ):
        raise ValueError("Comparison period labels do not match their saved rows.")
    dimensions = [key for key in spec.grain if key != spec.period_column]
    if any(current[key] != baseline[key] for key in dimensions):
        raise ValueError(
            "Comparison population/dimension mismatch between current and baseline rows."
        )
    if any(current[k] is None or baseline[k] is None for k in spec.grain):
        raise ValueError("Comparison grain contains missing keys.")
    value, previous = number(current[metric.column]), number(baseline[metric.column])
    delta = value - previous
    # Percentage change is undefined at zero; negative baselines use magnitude.
    percent = None if previous == 0 else delta / abs(previous) * 100
    denominator = None
    if spec.denominator_column:
        denominator = [
            number(current[spec.denominator_column]),
            number(baseline[spec.denominator_column]),
        ]
        if any(v <= 0 for v in denominator):
            raise ValueError("Rate/share denominators must be positive.")
        for row, actual, denom in zip(
            (current, baseline), (value, previous), denominator
        ):
            expected = number(row[spec.numerator_column]) / denom * spec.rate_scale
            if abs(actual - expected) > max(
                abs(expected) * Decimal("1e-8"), Decimal("1e-8")
            ):
                raise ValueError(
                    "Saved rate/share does not reconcile to its numerator and denominator. Use unrounded evidence."
                )
        if not spec.unit_column:
            unit = "percent" if spec.rate_scale == 100 else "ratio"
    return {
        "current": value,
        "baseline": previous,
        "delta": delta,
        "percentage_change": percent,
        "denominators": denominator,
        "reconciles": previous + delta == value,
        "units": unit,
        "metric_binding_verified": bound_metric == spec.metric_ref,
        "result_id": result.result_id,
        "column": metric.column,
        "current_row_index": metric.row_index,
        **spec.model_dump(),
    }
