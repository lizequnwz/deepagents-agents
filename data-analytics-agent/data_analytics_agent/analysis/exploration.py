"""Full-population exploration and descriptive group comparisons.

These helpers describe the supplied population. They do not infer business meaning,
units, source completeness, independence, causality or a suitable statistical test.
Use them for an exploration request, not as a mandatory step for scalar questions.
Save returned tables as output_datasets; select compact previews separately.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from data_analytics_agent.analysis._frames import (
    is_numeric,
    numeric_values,
    require_columns,
)


def explore_dataset(
    frame: pd.DataFrame,
    *,
    columns: Sequence[str] | None = None,
    date_column: str | None = None,
    frequency: str | None = None,
    top_categories: int = 20,
) -> dict[str, pd.DataFrame]:
    """Describe all rows in explicitly selected columns (all columns by default).

    Numeric moments and pairwise correlations use finite observations and report
    their denominators. Categorical counts retain nulls; omitted categories have
    a separate remainder table. Dates are examined only when date_column names an
    already parsed datetime column. An optional pandas period frequency, e.g.
    ``"M"`` or ``"D"``, enables observed-period gaps; gaps do not establish missing
    source records or incomplete periods. No values are imputed or rows sampled.
    """
    selected = require_columns(
        frame, list(frame.columns) if columns is None else columns
    )
    if not selected:
        raise ValueError("Select at least one column to explore.")
    if (
        not isinstance(top_categories, int)
        or isinstance(top_categories, bool)
        or top_categories < 1
    ):
        raise ValueError("top_categories must be a positive integer.")
    if frequency and not date_column:
        raise ValueError("A frequency requires an explicit date_column.")
    if date_column:
        require_columns(frame, [date_column])
        if date_column not in selected:
            raise ValueError("date_column must be among the selected columns.")
        if not pd.api.types.is_datetime64_any_dtype(frame[date_column]):
            raise ValueError(
                "date_column must be explicitly parsed to a datetime dtype first."
            )

    data = frame[selected]
    row_count = len(data)
    profile_rows, numeric_rows, category_rows, remainder_rows = [], [], [], []
    numeric: dict[str, pd.Series] = {}
    for name in selected:
        series = data[name]
        numeric_kind = is_numeric(series)
        profile_rows.append(
            {
                "column": name,
                "dtype": str(series.dtype),
                "kind": "numeric"
                if numeric_kind
                else "datetime"
                if pd.api.types.is_datetime64_any_dtype(series)
                else "categorical",
                "row_count": row_count,
                "non_null_count": int(series.notna().sum()),
                "missing_count": int(series.isna().sum()),
                "missing_fraction": float(series.isna().mean())
                if row_count
                else np.nan,
                "distinct_non_null": int(series.nunique(dropna=True)),
            }
        )
        if numeric_kind:
            floats = pd.to_numeric(series, errors="raise").astype(float)
            finite = floats.where(np.isfinite(floats))
            numeric[name] = finite
            clean = finite.dropna()
            numeric_rows.append(
                {
                    "column": name,
                    "finite_count": len(clean),
                    "nonfinite_count": int(
                        (floats.notna() & ~np.isfinite(floats)).sum()
                    ),
                    "minimum": clean.min(),
                    "q25": clean.quantile(0.25),
                    "median": clean.median(),
                    "q75": clean.quantile(0.75),
                    "maximum": clean.max(),
                    "mean": clean.mean(),
                    "std": clean.std(ddof=1),
                }
            )
        elif not pd.api.types.is_datetime64_any_dtype(series):
            counts = series.value_counts(dropna=False, sort=True)
            head = counts.iloc[:top_categories]
            for category, count in head.items():
                missing = bool(pd.isna(category))
                category_rows.append(
                    {
                        "column": name,
                        "category": None if missing else str(category),
                        "category_type": type(category).__name__,
                        "is_missing": missing,
                        "count": int(count),
                        "population_fraction": int(count) / row_count
                        if row_count
                        else np.nan,
                    }
                )
            remainder_rows.append(
                {
                    "column": name,
                    "displayed_categories": len(head),
                    "omitted_categories": max(0, len(counts) - len(head)),
                    "omitted_rows": int(counts.iloc[top_categories:].sum()),
                    "population_count": row_count,
                }
            )

    correlation_rows = []
    names = list(numeric)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            pairs = pd.concat([numeric[left], numeric[right]], axis=1).dropna()
            estimable = (
                len(pairs) >= 2
                and pairs[left].nunique() > 1
                and pairs[right].nunique() > 1
            )
            correlation_rows.append(
                {
                    "left": left,
                    "right": right,
                    "pair_count": len(pairs),
                    "pearson": pairs[left].corr(pairs[right], method="pearson")
                    if estimable
                    else np.nan,
                    "spearman": pairs[left].corr(pairs[right], method="spearman")
                    if estimable
                    else np.nan,
                }
            )
    output = {
        "overview": pd.DataFrame(
            [
                {
                    "row_count": row_count,
                    "selected_column_count": len(selected),
                    "duplicate_rows": int(data.duplicated().sum()),
                    "duplicate_members": int(data.duplicated(keep=False).sum()),
                    "source_completeness": "unknown",
                }
            ]
        ),
        "columns": pd.DataFrame(profile_rows),
        "numeric_summary": pd.DataFrame(
            numeric_rows,
            columns=[
                "column",
                "finite_count",
                "nonfinite_count",
                "minimum",
                "q25",
                "median",
                "q75",
                "maximum",
                "mean",
                "std",
            ],
        ),
        "categorical_counts": pd.DataFrame(
            category_rows,
            columns=[
                "column",
                "category",
                "category_type",
                "is_missing",
                "count",
                "population_fraction",
            ],
        ),
        "categorical_remainder": pd.DataFrame(
            remainder_rows,
            columns=[
                "column",
                "displayed_categories",
                "omitted_categories",
                "omitted_rows",
                "population_count",
            ],
        ),
        "correlations": pd.DataFrame(
            correlation_rows,
            columns=["left", "right", "pair_count", "pearson", "spearman"],
        ),
    }
    if date_column:
        times = data[date_column].dropna()
        coverage = {
            "column": date_column,
            "observed_count": len(times),
            "missing_count": int(data[date_column].isna().sum()),
            "first_observed": times.min(),
            "last_observed": times.max(),
            "distinct_timestamps": times.nunique(),
            "duplicate_timestamps": int(times.duplicated().sum()),
            "frequency": frequency,
            "source_completeness": "unknown",
        }
        if frequency:
            # Preserve the displayed local calendar; do not shift timezone boundaries.
            calendar_times = (
                times.dt.tz_localize(None) if times.dt.tz is not None else times
            )
            periods = calendar_times.dt.to_period(frequency)
            expected = (
                pd.period_range(periods.min(), periods.max(), freq=frequency)
                if len(periods)
                else pd.PeriodIndex([], freq=frequency)
            )
            counts = periods.value_counts().reindex(expected, fill_value=0)
            output["time_periods"] = pd.DataFrame(
                {"period": expected.astype(str), "observed_rows": counts.to_numpy()}
            )
            output["time_gaps"] = (
                output["time_periods"]
                .loc[lambda d: d.observed_rows.eq(0)]
                .reset_index(drop=True)
            )
            coverage["unobserved_period_count"] = int(counts.eq(0).sum())
        output["time_coverage"] = pd.DataFrame([coverage])
    return output


def compare_groups(
    frame: pd.DataFrame,
    *,
    group: str,
    value: str,
    reference_group: object = None,
) -> dict[str, pd.DataFrame]:
    """Summarize a numeric value by group, retaining null group labels and values.

    Optional mean/median differences and mean ratios compare each group with an
    explicitly named non-null reference. These are descriptive effects, with no
    significance, independence or causal claim. A zero reference mean has no ratio.
    """
    require_columns(frame, [group, value])
    if group == value:
        raise ValueError("group and value must be distinct columns.")
    numeric_values(frame, value)
    rows = []
    for key, data in frame.groupby(group, dropna=False, observed=True, sort=False):
        observed = pd.to_numeric(data[value], errors="raise").astype(float).dropna()
        rows.append(
            {
                "group": key,
                "row_count": len(data),
                "observed_count": len(observed),
                "missing_count": int(data[value].isna().sum()),
                "mean": observed.mean(),
                "median": observed.median(),
                "std": observed.std(ddof=1),
                "minimum": observed.min(),
                "maximum": observed.max(),
            }
        )
    groups = pd.DataFrame(
        rows,
        columns=[
            "group",
            "row_count",
            "observed_count",
            "missing_count",
            "mean",
            "median",
            "std",
            "minimum",
            "maximum",
        ],
    )
    comparisons = groups.copy()
    if reference_group is not None:
        reference = groups.loc[groups["group"].eq(reference_group)]
        if len(reference) != 1:
            raise ValueError(
                "reference_group must identify an observed, non-null group."
            )
        reference = reference.iloc[0]
        comparisons["reference_group"] = reference_group
        comparisons["mean_difference"] = groups["mean"] - reference["mean"]
        comparisons["median_difference"] = groups["median"] - reference["median"]
        comparisons["mean_ratio"] = (
            groups["mean"] / reference["mean"]
            if pd.notna(reference["mean"]) and reference["mean"] != 0
            else np.nan
        )
    return {"groups": groups, "comparisons": comparisons}
