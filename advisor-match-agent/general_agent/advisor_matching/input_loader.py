"""Load mapped source rows while preserving original values and positions."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

from general_agent.advisor_matching.schemas import FieldBinding, InputMapping


def load_input(path: Path, mapping: InputMapping, *, max_rows: int) -> list[tuple[int, dict[str, object], dict[str, str]]]:
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(
            path, dtype=str, sep=_csv_separator(path),
            header=mapping.header_row - 1, nrows=max_rows + 1,
        )
    else:
        frame = pd.read_excel(
            path, sheet_name=mapping.sheet_name or 0, dtype=str,
            header=mapping.header_row - 1, nrows=max_rows + 1,
        )
    if len(frame) > max_rows:
        raise ValueError(f"Input contains {len(frame):,} rows; limit is {max_rows:,}.")
    results = []
    for offset, (_, row) in enumerate(frame.iterrows(), start=mapping.header_row + 1):
        source = {str(column): ("" if pd.isna(value) else value) for column, value in row.items()}
        mapped = {}
        for field in ("crd_number", "first_name", "last_name", "full_name", "firm_name", "email", "street_address", "city", "state", "zip_code"):
            binding = getattr(mapping, field)
            mapped[field] = _binding_value(row, binding) if binding else ""
        results.append((offset, source, mapped))
    return results


def _binding_value(row: pd.Series, binding: FieldBinding) -> str:
    values = []
    for reference in binding.columns:
        if reference.index >= len(row.index) or str(row.index[reference.index]) != reference.header:
            raise ValueError(f"Column mapping no longer matches index {reference.index}: {reference.header!r}.")
        value = row.iloc[reference.index]
        values.append("" if pd.isna(value) else str(value).strip())
    if binding.combine == "join_space":
        return " ".join(value for value in values if value)
    return next((value for value in values if value), "")


def _csv_separator(path: Path) -> str:
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        sample = handle.read(65_536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","
