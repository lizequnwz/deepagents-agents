"""Deterministic what-if calculations over explicit assumptions."""

from collections.abc import Callable, Mapping, Sequence
from itertools import product
from math import prod

import numpy as np
import pandas as pd


def scenario_grid(
    assumptions: Mapping[str, Sequence[float]],
    formula: Callable[..., float],
    *,
    formula_description: str,
    outcome: str = "outcome",
    unit: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Evaluate every assumption combination without assigning probabilities.

    ``formula`` receives named scalar assumptions. Undefined arithmetic remains
    a saved scenario with a missing outcome and explicit status. Ranges describe
    supplied scenarios only; they are neither confidence nor prediction bounds.
    """
    if not assumptions or not formula_description.strip():
        raise ValueError("Named assumptions and a formula description are required")
    if (
        not outcome
        or outcome in assumptions
        or outcome in {"scenario_id", "status", "reason"}
    ):
        raise ValueError("Outcome name must be distinct from inputs and metadata")
    names = list(assumptions)
    if any(
        not isinstance(name, str)
        or not name
        or name in {"scenario_id", "status", "reason"}
        for name in names
    ):
        raise ValueError("Assumption names must be nonempty and distinct from metadata")
    candidates = []
    for name in names:
        values = list(assumptions[name])
        if not values or any(
            not np.isscalar(value) or not np.isfinite(float(value)) for value in values
        ):
            raise ValueError("Assumptions must contain nonempty finite numeric values")
        candidates.append([float(value) for value in values])
    if prod(map(len, candidates)) > 10_000:
        raise ValueError("Scenario grid exceeds 10,000 combinations")
    rows = []
    for index, values in enumerate(product(*candidates)):
        inputs = dict(zip(names, values, strict=True))
        result, status, reason = np.nan, "assessed", ""
        try:
            result = float(formula(**inputs))
            if not np.isfinite(result):
                result, status, reason = np.nan, "undefined", "nonfinite outcome"
        except (
            ZeroDivisionError,
            ValueError,
            OverflowError,
            FloatingPointError,
        ) as exc:
            status, reason = "undefined", type(exc).__name__
        rows.append(
            {
                "scenario_id": index,
                **inputs,
                outcome: result,
                "status": status,
                "reason": reason,
            }
        )
    scenarios = pd.DataFrame(rows)
    assessed = scenarios.loc[scenarios["status"].eq("assessed"), outcome]
    return {
        "scenarios": scenarios,
        "scenario_summary": pd.DataFrame(
            [
                {
                    "formula": formula_description,
                    "outcome": outcome,
                    "unit": unit or "unknown",
                    "scenario_count": len(scenarios),
                    "assessed_scenarios": len(assessed),
                    "undefined_scenarios": len(scenarios) - len(assessed),
                    "minimum": assessed.min() if len(assessed) else np.nan,
                    "maximum": assessed.max() if len(assessed) else np.nan,
                    "range_meaning": "Deterministic supplied scenarios; no probability coverage assigned",
                }
            ]
        ),
    }
