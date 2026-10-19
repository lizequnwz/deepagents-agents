"""Explicit, auditable pandas preparation without destructive default policies."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from data_analytics_agent.analysis._frames import require_columns, timestamp_values


def prepare_dataset(
    frame: pd.DataFrame,
    *,
    conversions: Mapping[str, str] | None = None,
    date_formats: Mapping[str, str] | None = None,
    derived: Mapping[str, Callable[[pd.DataFrame], pd.Series]] | None = None,
    fill_values: Mapping[str, Any] | None = None,
    drop_missing: Sequence[str] | None = None,
    deduplicate_by: Sequence[str] | None = None,
    deduplicate_keep: str | bool = "first",
) -> dict[str, pd.DataFrame]:
    """Return an independent dataset plus an operation/row-count audit.

    Apply only requested operations, in this order: conversion, derived columns,
    missing-value fill, dropping missing rows, deduplication. Source data is never
    mutated. Conversion errors raise; no malformed value silently becomes null.

    conversions accepts pandas dtypes (e.g. 'Int64', 'Float64', 'string') or
    'numeric'/'integer'. Datetimes require date_formats with explicit strptime
    formats or 'ISO8601'; ambiguous day/month order is never guessed. Derived
    callables must return a Series with the same index and a new column name.
    Drops remove rows missing ANY named column. Deduplication requires explicit
    keys, with pandas keep='first', 'last' or False semantics. Null keys participate
    in deduplication, so the caller must decide whether that is appropriate.
    """
    require_columns(frame, [])
    result = frame.copy(deep=True)
    operations: list[dict[str, Any]] = []

    def record(operation, column, affected, before, detail):
        operations.append(
            {
                "operation": operation,
                "column": column,
                "affected_rows": int(affected),
                "rows_before": int(before),
                "rows_after": len(result),
                "detail": detail,
            }
        )

    conversions, date_formats = dict(conversions or {}), dict(date_formats or {})
    require_columns(result, list(dict.fromkeys([*conversions, *date_formats])))
    for column, dtype in conversions.items():
        if not isinstance(dtype, str):
            raise ValueError("Conversion types must be pandas dtype strings.")
        if dtype == "datetime" or pd.api.types.is_datetime64_any_dtype(dtype):
            if column not in date_formats:
                raise ValueError(
                    f"Datetime conversion for {column!r} requires an explicit date format."
                )
            continue
        if column in date_formats:
            raise ValueError(
                f"Choose either a numeric/text conversion or a date format for {column!r}."
            )
        missing_before = result[column].isna()
        if dtype in {"numeric", "integer"}:
            converted = pd.to_numeric(result[column], errors="raise")
            result[column] = (
                converted.astype("Int64") if dtype == "integer" else converted
            )
        elif dtype in {"str", "string"}:
            result[column] = result[column].astype("string")
        elif dtype in {"bool", "boolean"}:
            # pandas astype(bool) would turn the text 'False' into True.
            result[column] = result[column].astype("boolean")
        else:
            result[column] = result[column].astype(dtype, errors="raise")
        if not result[column].isna().equals(missing_before):
            raise ValueError(
                f"Conversion for {column!r} changes missingness; choose an explicit missing-value policy instead."
            )
        record("convert", column, len(result), len(result), dtype)
    for column, fmt in date_formats.items():
        if not isinstance(fmt, str) or not fmt.strip() or fmt == "mixed":
            raise ValueError(
                "Date conversion requires an explicit format or ISO8601, not mixed inference."
            )
        missing_before = result[column].isna()
        converted = (
            timestamp_values(result[column], utc=False)
            if fmt == "ISO8601"
            else pd.to_datetime(result[column], format=fmt, errors="raise")
        )
        if not converted.isna().equals(missing_before):
            raise ValueError(
                f"Date conversion for {column!r} changes missingness; choose an explicit missing-value policy instead."
            )
        result[column] = converted
        record("parse_datetime", column, len(result), len(result), fmt)
    for column, transform in (derived or {}).items():
        if (
            not isinstance(column, str)
            or not column.strip()
            or column in result.columns
        ):
            raise ValueError("Derived columns require a new, nonempty column name.")
        if not callable(transform):
            raise ValueError(
                "Derived transforms must be explicit callables returning a pandas Series."
            )
        values = transform(result.copy(deep=True))
        if not isinstance(values, pd.Series) or not values.index.equals(result.index):
            raise ValueError(
                "Derived transforms must preserve the input row index exactly."
            )
        result[column] = values
        record(
            "derive",
            column,
            len(result),
            len(result),
            "Explicit caller-supplied transform; original columns retained.",
        )
    for column, replacement in (fill_values or {}).items():
        require_columns(result, [column])
        affected = int(result[column].isna().sum())
        result[column] = result[column].fillna(replacement)
        record("fill_missing", column, affected, len(result), repr(replacement))
    if drop_missing is not None:
        selected = require_columns(result, drop_missing)
        if not selected:
            raise ValueError("drop_missing requires explicit nonempty column names.")
        before = len(result)
        result = result.dropna(subset=selected, how="any")
        record(
            "drop_missing",
            ", ".join(selected),
            before - len(result),
            before,
            "Drop rows missing any named column.",
        )
    if deduplicate_by is not None:
        selected = require_columns(result, deduplicate_by)
        if not selected:
            raise ValueError("deduplicate_by requires explicit nonempty key columns.")
        if deduplicate_keep not in {"first", "last", False}:
            raise ValueError("deduplicate_keep must be 'first', 'last' or False.")
        before = len(result)
        result = result.drop_duplicates(subset=selected, keep=deduplicate_keep)
        record(
            "deduplicate",
            ", ".join(selected),
            before - len(result),
            before,
            f"keep={deduplicate_keep!r}; null keys participate.",
        )
    return {
        "dataset": result,
        "operations": pd.DataFrame(
            operations,
            columns=[
                "operation",
                "column",
                "affected_rows",
                "rows_before",
                "rows_after",
                "detail",
            ],
        ),
    }
