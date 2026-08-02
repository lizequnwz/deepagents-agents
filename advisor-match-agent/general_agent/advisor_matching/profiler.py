"""Bounded CSV/XLSX profiling and deterministic column suggestions."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

from general_agent.config import Settings

_ALIASES = {
    "crd_number": {"crd", "crd number", "finra crd", "advisor crd"},
    "first_name": {"first name", "firstname", "advisor first", "given name"},
    "last_name": {"last name", "lastname", "advisor last", "surname"},
    "full_name": {"name", "full name", "advisor name", "representative"},
    "firm_name": {"firm", "firm name", "company", "organization", "broker dealer"},
    "email": {"email", "email address", "e mail"},
    "street_address": {"street", "street address", "address", "address 1"},
    "city": {"city", "town"}, "state": {"state", "province"},
    "zip_code": {"zip", "zip code", "postal code", "postcode"},
}


def profile_advisor_file(path: Path, settings: Settings) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("Advisor matching accepts only CSV or XLSX files.")
    sheets: list[dict[str, Any]] = []
    if suffix == ".csv":
        frames = [(None, pd.read_csv(path, nrows=settings.max_inspect_rows, dtype=str, sep=_csv_separator(path)))]
    else:
        excel = pd.ExcelFile(path)
        frames = [(name, excel.parse(name, nrows=settings.max_inspect_rows, dtype=str)) for name in excel.sheet_names[: settings.max_inspect_sheets]]
    for name, frame in frames:
        columns = []
        suggestions: dict[str, list[dict[str, object]]] = {}
        for index, raw_header in enumerate(frame.columns[: settings.max_inspect_columns]):
            header = str(raw_header)
            normalized = " ".join(header.strip().casefold().replace("_", " ").split())
            series = frame.iloc[:, index]
            columns.append({"index": index, "header": header, "non_null": int(series.notna().sum()), "pattern": _pattern(series)})
            for field, aliases in _ALIASES.items():
                if normalized in aliases:
                    suggestions.setdefault(field, []).append({"index": index, "header": header})
        samples = frame.iloc[:3, : settings.max_inspect_columns].where(frame.notna(), None).to_dict(orient="records")
        sheets.append({"name": name, "columns": columns, "sample_rows": samples, "mapping_suggestions": suggestions})
    return {"input_virtual_path": f"/uploads/{path.name}", "format": suffix[1:], "sheets": sheets, "warnings": []}


def _pattern(series: pd.Series) -> str:
    values = [str(value).strip() for value in series.dropna().head(20) if str(value).strip()]
    if values and sum("@" in value for value in values) >= max(1, len(values) // 2):
        return "email"
    if values and all(value.replace(".0", "").isdigit() for value in values):
        return "numeric"
    return "text"


def _csv_separator(path: Path) -> str:
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        sample = handle.read(65_536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","
