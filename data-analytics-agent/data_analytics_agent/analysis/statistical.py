"""Two-group estimation with explicit sample accounting and effect intervals."""

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import confint_proportions_2indep
from statsmodels.stats.weightstats import CompareMeans, DescrStatsW

from data_analytics_agent.analysis._frames import (
    decimal_number,
    numeric_values,
    require_columns,
    subtract_numbers,
)


def compare_groups(
    frame: pd.DataFrame,
    *,
    group: str,
    outcome: str,
    reference: str | int,
    comparison: str | int,
    kind: str = "numeric",
    confidence: float = 0.95,
    unit_id: str | None = None,
    unit: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Compare independent rows: comparison minus reference.

    Numeric outcomes use a Welch mean-difference interval and test, plus Hedges'
    g. Binary 0/1 outcomes use a Newcombe risk-difference interval and Fisher's
    exact test. Missing outcomes are excluded explicitly; no imputation occurs.
    Supplying ``unit_id`` detects repeated units. Without it, independence is a
    caller assumption. Results describe association, not an identified cause.
    Numeric inference is centered and scaled to avoid variance overflow or
    underflow; differences and bounds are restored to the supplied units.
    """
    if kind not in {"numeric", "binary"} or not 0 < confidence < 1:
        raise ValueError(
            "kind must be numeric/binary and confidence between zero and one"
        )
    require_columns(frame, [group, outcome] + ([unit_id] if unit_id else []))
    if pd.isna(reference) or pd.isna(comparison) or reference == comparison:
        raise ValueError("Two distinct nonmissing groups are required")
    selected = frame[group].isin([reference, comparison])
    if kind == "numeric":
        values = numeric_values(frame.loc[selected], outcome)
    else:
        values = pd.to_numeric(frame.loc[selected, outcome], errors="raise").astype(
            float
        )
        if np.isinf(values.dropna()).any():
            raise ValueError("Outcomes must be finite or missing")
    if kind == "binary" and not values.dropna().isin([0, 1]).all():
        raise ValueError("Binary outcomes must be zero or one")
    included = selected & frame[outcome].notna()
    if unit_id:
        units = frame.loc[included, unit_id]
        if units.isna().any() or units.duplicated().any():
            raise ValueError(
                "Independent comparison requires unique nonmissing unit IDs"
            )
    samples = []
    arrays = []
    center, scale = 0, 1.0
    if kind == "numeric" and values.notna().any():
        center = values.dropna().iloc[0]
        shifted = np.array(
            [float(subtract_numbers(item, center)) for item in values.dropna()]
        )
        if not np.isfinite(shifted).all():
            raise ValueError(
                "Numeric comparison exceeds finite range; rescale outcomes explicitly."
            )
        scale = float(np.max(np.abs(shifted))) or 1.0
    for label in [reference, comparison]:
        mask = frame[group].eq(label) & selected
        raw = frame.loc[mask, outcome].dropna()
        sample = (
            np.array([float(subtract_numbers(item, center)) / scale for item in raw])
            if kind == "numeric"
            else pd.to_numeric(raw, errors="raise").to_numpy(dtype=float)
        )
        arrays.append(sample)
        mean = (
            float(decimal_number(center) + decimal_number(float(sample.mean()) * scale))
            if kind == "numeric" and len(sample)
            else float(sample.mean())
            if len(sample)
            else np.nan
        )
        deviation = float(sample.std(ddof=1)) * scale if len(sample) > 1 else np.nan
        if (len(sample) and not np.isfinite(mean)) or (
            len(sample) > 1 and not np.isfinite(deviation)
        ):
            raise ValueError(
                "Numeric comparison exceeds finite range; rescale outcomes explicitly."
            )
        samples.append(
            {
                "group": label,
                "population_rows": int(mask.sum()),
                "analyzed_rows": len(sample),
                "missing_outcome_rows": int((mask & frame[outcome].isna()).sum()),
                "mean_or_rate": mean,
                "standard_deviation": deviation,
            }
        )
    ref, comp = arrays
    normalized_estimate = (
        float(comp.mean() - ref.mean()) if len(ref) and len(comp) else np.nan
    )
    estimate = normalized_estimate * scale
    lower = upper = pvalue = hedges_g = np.nan
    status = "insufficient_data"
    method = (
        "Welch t interval/test"
        if kind == "numeric"
        else "Newcombe risk-difference interval; Fisher exact test"
    )
    if kind == "binary" and len(ref) and len(comp):
        lower, upper = confint_proportions_2indep(
            int(comp.sum()),
            len(comp),
            int(ref.sum()),
            len(ref),
            method="newcomb",
            compare="diff",
            alpha=1 - confidence,
        )
        pvalue = stats.fisher_exact(
            [
                [int(comp.sum()), len(comp) - int(comp.sum())],
                [int(ref.sum()), len(ref) - int(ref.sum())],
            ]
        ).pvalue
        status = "assessed"
    elif kind == "numeric" and min(len(ref), len(comp)) >= 2:
        ref_var, comp_var = ref.var(ddof=1), comp.var(ddof=1)
        if ref_var + comp_var > 0:
            lower, upper = CompareMeans(
                DescrStatsW(comp), DescrStatsW(ref)
            ).tconfint_diff(alpha=1 - confidence, usevar="unequal")
            pvalue = stats.ttest_ind(comp, ref, equal_var=False).pvalue
            degrees = len(ref) + len(comp) - 2
            pooled = np.sqrt(
                ((len(ref) - 1) * ref_var + (len(comp) - 1) * comp_var) / degrees
            )
            hedges_g = (1 - 3 / (4 * degrees - 1)) * normalized_estimate / pooled
            lower, upper = lower * scale, upper * scale
            if not np.isfinite([estimate, lower, upper, pvalue, hedges_g]).all():
                raise ValueError(
                    "Numeric inference returned nonfinite results; rescale outcomes explicitly."
                )
            status = "assessed"
        else:
            status = "undefined_zero_variance"
    rows = pd.DataFrame(
        {
            "source_row": np.arange(len(frame)),
            "group": frame[group].to_numpy(),
            "outcome": frame[outcome].to_numpy(),
            "is_analyzed": included.to_numpy(),
            "exclusion_reason": np.where(
                ~selected,
                "outside_selected_groups",
                np.where(frame[outcome].isna(), "missing_outcome", ""),
            ),
        }
    )
    return {
        "group_comparison": pd.DataFrame(
            [
                {
                    "reference": reference,
                    "comparison": comparison,
                    "estimand": "risk_difference"
                    if kind == "binary"
                    else "mean_difference",
                    "direction": "comparison minus reference",
                    "estimate": estimate,
                    "ci_lower": float(lower),
                    "ci_upper": float(upper),
                    "confidence_level": confidence,
                    "p_value": float(pvalue),
                    "hedges_g": hedges_g,
                    "method": method,
                    "status": status,
                    "outcome_unit": "proportion"
                    if kind == "binary"
                    else unit or "unknown",
                    "interpretation": "Association; independent observations assumed",
                }
            ]
        ),
        "group_samples": pd.DataFrame(samples),
        "comparison_population": rows,
    }
