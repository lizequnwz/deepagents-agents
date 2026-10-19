"""Small shared checks for analytical helpers over complete pandas inputs."""

from decimal import Decimal, localcontext
from datetime import date, datetime
from numbers import Integral, Real
from collections.abc import Sequence
import re

import numpy as np
import pandas as pd


_ISO_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?"
    r"(?:Z|[+-]\d{2}:\d{2})?)?"
)


def timestamp_values(
    values: pd.Series, *, label: str = "Dates", utc: bool = True
) -> pd.Series:
    """Parse typed dates or strict ISO text, retaining missing values.

    Numeric epochs and ambiguous date strings require explicit preparation.
    Empty strings/NaT text are not silently promoted to missing dates.
    UTC normalization is explicit by default; preparation may retain a consistent
    supplied timezone with utc=False instead of changing calendar labels.
    """
    for value in values:
        if value is None or value is pd.NA or value is pd.NaT:
            continue
        if isinstance(value, (float, np.floating)) and np.isnan(value):
            continue
        if isinstance(value, str):
            if _ISO_TIMESTAMP.fullmatch(value):
                continue
        elif isinstance(value, (date, datetime, pd.Timestamp, np.datetime64)):
            continue
        raise ValueError(
            f"{label} require typed dates/timestamps or strict ISO date text. "
            "Use explicit date-format preparation for ambiguous strings or numeric epochs."
        )
    return pd.to_datetime(values, errors="raise", utc=utc, format="ISO8601")


def timestamp_value(value, *, label: str = "Date") -> pd.Timestamp:
    """Scalar form of the same explicit timestamp contract."""
    return timestamp_values(pd.Series([value]), label=label).iloc[0]


def require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> list[str]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")
    if not frame.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    if isinstance(columns, str):
        raise ValueError("Supply column names as a sequence, not a string.")
    selected = list(columns)
    if len(set(selected)) != len(selected):
        raise ValueError("Selected column names must be unique.")
    if missing := [column for column in selected if column not in frame.columns]:
        raise ValueError(f"Unknown columns: {missing}.")
    return selected


def numeric_values(frame: pd.DataFrame, column: str) -> pd.Series:
    """Validate a measure without parsing text or discarding its missing values."""
    require_columns(frame, [column])
    series = frame[column]
    values = series.dropna()
    if pd.api.types.is_bool_dtype(series.dtype) or any(
        isinstance(value, (bool, np.bool_)) or not isinstance(value, (Real, Decimal))
        for value in values
    ):
        raise ValueError(
            f"Column {column!r} must contain numeric values, not text or booleans."
        )
    if any(not np.isfinite(float(value)) for value in values):
        raise ValueError(f"Column {column!r} contains nonfinite values.")
    return series


def is_numeric(series: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(series.dtype):
        return False
    if pd.api.types.is_numeric_dtype(series.dtype):
        return not pd.api.types.is_complex_dtype(series.dtype)
    values = series.dropna()
    return bool(len(values)) and all(
        isinstance(value, (Real, Decimal)) and not isinstance(value, (bool, np.bool_))
        for value in values
    )


def decimal_number(value) -> Decimal:
    """Represent supplied finite numeric values without an intermediate float.

    Decimal arithmetic uses the decimal representation of existing floats; it
    cannot recover precision already absent from a floating-point source.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Integral):
        return Decimal(int(value))
    return Decimal(str(value))


def _arithmetic_result(value: Decimal, operands):
    if any(isinstance(item, Decimal) for item in operands):
        return value
    if all(isinstance(item, Integral) for item in operands):
        integer = int(value)
        return integer if -(2**63) <= integer < 2**63 else value
    if any(isinstance(item, Integral) and abs(item) > 2**53 for item in operands):
        return value
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(
            "Numeric arithmetic exceeded finite output range; rescale the supplied values explicitly."
        )
    return result


def sum_numbers(values):
    """Avoid integer overflow and preserve Decimal precision in additive evidence."""
    values = list(values)
    with localcontext() as context:
        # Covers the IEEE float exponent span and bounded Arrow decimal inputs.
        context.prec = 1000
        result = sum((decimal_number(value) for value in values), Decimal(0))
        return _arithmetic_result(result, values)


def subtract_numbers(left, right):
    with localcontext() as context:
        context.prec = 1000
        return _arithmetic_result(
            decimal_number(left) - decimal_number(right), [left, right]
        )


def numbers_close(left, right, *, atol, rtol) -> bool:
    """Apply the declared absolute/relative tolerance without float rounding."""
    with localcontext() as context:
        context.prec = 1000
        left, right = decimal_number(left), decimal_number(right)
        tolerance = decimal_number(atol) + decimal_number(rtol) * abs(right)
        return abs(left - right) <= tolerance
