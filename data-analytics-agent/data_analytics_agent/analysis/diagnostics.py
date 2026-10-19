"""Keyed reconciliation and additive change attribution over saved populations."""

from collections.abc import Sequence
from numbers import Integral

import numpy as np
import pandas as pd

from data_analytics_agent.analysis._frames import (
    subtract_numbers,
    decimal_number,
    sum_numbers,
    numbers_close,
    numeric_values,
    require_columns,
)


def _total(series: pd.Series):
    # A partial sum of known values must not be represented as a complete total.
    return pd.NA if series.isna().any() else sum_numbers(series)


def _aligned(current, baseline, keys, value, unmatched):
    keys = require_columns(current, keys)
    require_columns(baseline, keys)
    if not keys or value in keys:
        raise ValueError("Supply nonempty grouping keys distinct from value.")
    if set(keys) & {
        "current_value",
        "baseline_value",
        "presence",
        "difference",
        "matches",
        "relative_change",
        "contribution",
        "share_of_total_change",
    }:
        raise ValueError(
            "Grouping keys conflict with output column names; rename those keys first."
        )
    if unmatched not in {"unknown", "zero"}:
        raise ValueError("unmatched must be 'unknown' or explicitly 'zero'.")
    for label, data in [("current", current), ("baseline", baseline)]:
        numeric_values(data, value)
        if data.duplicated(keys).any():
            raise ValueError(
                f"{label} has duplicate grouping keys; aggregate explicitly before comparing."
            )
    # Object columns retain integers through an outer join: pandas otherwise
    # promotes missing integer cells to float and rounds values above 2**53.
    left = current[keys + [value]].copy()
    right = baseline[keys + [value]].copy()
    for data in (left, right):
        data[value] = pd.Series(
            [
                decimal_number(item)
                if isinstance(item, Integral) and not -(2**63) <= item < 2**63
                else item
                for item in data[value]
            ],
            index=data.index,
            dtype=object,
        )
    rows = left.rename(columns={value: "current_value"}).merge(
        right.rename(columns={value: "baseline_value"}),
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator="presence",
        sort=False,
    )
    rows["presence"] = (
        rows["presence"]
        .map(
            {"both": "both", "left_only": "current_only", "right_only": "baseline_only"}
        )
        .astype("string")
    )
    if unmatched == "zero":
        # Only an absent row becomes zero; an observed row with a null stays null.
        rows.loc[rows.presence.eq("baseline_only"), "current_value"] = 0
        rows.loc[rows.presence.eq("current_only"), "baseline_value"] = 0
    rows["difference"] = pd.Series(
        [
            pd.NA if pd.isna(left) or pd.isna(right) else subtract_numbers(left, right)
            for left, right in zip(rows.current_value, rows.baseline_value)
        ],
        dtype=object,
    )
    current_total, baseline_total = _total(current[value]), _total(baseline[value])
    change = (
        pd.NA
        if pd.isna(current_total) or pd.isna(baseline_total)
        else subtract_numbers(current_total, baseline_total)
    )
    metadata = {
        "current_rows": len(current),
        "baseline_rows": len(baseline),
        "matched_groups": int(rows.presence.eq("both").sum()),
        "current_only_groups": int(rows.presence.eq("current_only").sum()),
        "baseline_only_groups": int(rows.presence.eq("baseline_only").sum()),
        "current_missing_values": int(current[value].isna().sum()),
        "baseline_missing_values": int(baseline[value].isna().sum()),
        "unresolved_groups": int(rows.difference.isna().sum()),
        "current_total": current_total,
        "baseline_total": baseline_total,
        "total_difference": change,
        "unmatched_policy": unmatched,
        "null_key_policy": "Null grouping keys match null grouping keys.",
    }
    return rows, metadata


def reconcile_tables(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    keys: Sequence[str],
    value: str,
    unmatched: str = "unknown",
    atol: float = 1e-8,
    rtol: float = 1e-5,
) -> dict[str, pd.DataFrame]:
    """Align unique grouping keys and compare numeric values, retaining every group.

    Inputs must already be at the declared grain. Null keys match each other;
    duplicate keys fail. Missing measures stay unknown, including when both are
    missing. Absent groups are unknown unless the caller explicitly declares
    ``unmatched='zero'``. Units, time scope and measure equivalence are caller
    requirements: matching numbers cannot establish those business meanings.
    """
    if not all(np.isfinite(number) and number >= 0 for number in (atol, rtol)):
        raise ValueError("Tolerances must be finite nonnegative numbers.")
    rows, summary = _aligned(current, baseline, keys, value, unmatched)
    rows["matches"] = pd.array(
        [
            pd.NA
            if pd.isna(left) or pd.isna(right)
            else numbers_close(left, right, atol=atol, rtol=rtol)
            for left, right in zip(rows.current_value, rows.baseline_value)
        ],
        dtype="boolean",
    )
    summary.update(
        {
            "matching_groups": int(rows.matches.eq(True).sum()),
            "different_groups": int(rows.matches.eq(False).sum()),
            "unassessed_groups": int(rows.matches.isna().sum()),
            "all_groups_match": bool(rows.matches.notna().all() and rows.matches.all()),
            "atol": atol,
            "rtol": rtol,
        }
    )
    return {"rows": rows, "summary": pd.DataFrame([summary])}


def decompose_change(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    keys: Sequence[str],
    value: str,
    unmatched: str = "unknown",
) -> dict[str, pd.DataFrame]:
    """Attribute additive total change to disjoint groups at unique declared keys.

    This is arithmetic contribution, not causal attribution or a rate/mix
    decomposition. The caller must supply an additive value with the same units
    and population meaning in both inputs. Unknown groups/null measures remain
    visible. Set unmatched='zero' only when absent groups mean zero by definition.
    Shares and relative changes are undefined for zero denominators. Observed
    measures retain their numeric type; displayed ratios use floating point.
    """
    rows, summary = _aligned(current, baseline, keys, value, unmatched)
    rows = rows.rename(columns={"difference": "contribution"})
    rows["relative_change"] = [
        float(decimal_number(delta) / decimal_number(baseline))
        if pd.notna(delta) and pd.notna(baseline) and baseline != 0
        else np.nan
        for delta, baseline in zip(rows.contribution, rows.baseline_value)
    ]
    change = summary["total_difference"]
    rows["share_of_total_change"] = [
        float(decimal_number(delta) / decimal_number(change))
        if pd.notna(delta) and pd.notna(change) and change != 0
        else np.nan
        for delta in rows.contribution
    ]
    known = sum_numbers(rows.contribution.dropna())
    summary["known_contribution_sum"] = known
    summary["unallocated_difference"] = (
        pd.NA if pd.isna(change) else subtract_numbers(change, known)
    )
    summary["reconciled"] = bool(
        summary["unresolved_groups"] == 0
        and pd.notna(change)
        and numbers_close(change, known, atol=1e-8, rtol=1e-5)
    )
    return {"contributions": rows, "summary": pd.DataFrame([summary])}
