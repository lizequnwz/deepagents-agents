"""Bounded workbook inspection and explicit single-table selection."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import io
import re
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from pydantic import BaseModel, ConfigDict, Field
import pyarrow as pa


class ExcelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=200)
    cell_range: str = Field(min_length=3, max_length=40)
    use_cached_formulas: bool = False


def validate_workbook(content, settings):
    if not content or len(content) > settings.upload_max_bytes:
        raise ValueError("Workbook is empty or exceeds the upload byte limit.")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 10000
                or sum(e.file_size for e in entries) > settings.max_dataset_bytes
            ):
                raise ValueError("Decoded workbook exceeds the parsing byte limit.")
            if len({e.filename for e in entries}) != len(entries):
                raise ValueError("Workbook contains duplicate archive entries.")
            if any(e.flag_bits & 1 for e in entries):
                raise ValueError("Encrypted workbooks are not supported.")
    except BadZipFile as exc:
        raise ValueError("The file is not a readable .xlsx workbook.") from exc


def selected_merges(content, worksheet, bounds):
    # ReadOnlyWorksheet exposes its package part here; merged cells have no
    # public read-only API. Keep the package inspection confined to this helper.
    left, top, right, bottom = bounds
    with ZipFile(io.BytesIO(content)) as archive:
        with archive.open(worksheet._worksheet_path) as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag.endswith("}mergeCell"):
                    a, b, c, d = range_boundaries(element.attrib["ref"])
                    if a <= right and c >= left and b <= bottom and d >= top:
                        raise ValueError(
                            "Selected table contains merged cells. Select an unmerged rectangular table; cells will not be filled automatically."
                        )
                element.clear()


@contextmanager
def workbook(content, *, data_only):
    try:
        book = load_workbook(
            io.BytesIO(content), read_only=True, data_only=data_only, keep_links=False
        )
    except (ValueError, KeyError, OSError, ET.ParseError) as exc:
        raise ValueError(
            "The workbook could not be read. Supply a valid .xlsx file."
        ) from exc
    try:
        yield book
    finally:
        book.close()


def inspect_workbook(content, settings):
    validate_workbook(content, settings)
    with workbook(content, data_only=True) as book:
        return {
            "sheets": [
                {
                    "name": ws.title,
                    "range": ws.calculate_dimension(),
                    "preview": [
                        [str(c.value) if c.value is not None else None for c in row]
                        for row in ws.iter_rows(
                            max_row=min(ws.max_row or 10, 10),
                            max_col=min(ws.max_column or 20, 20),
                        )
                    ],
                }
                for ws in book.worksheets
            ]
        }


def read_excel_table(content, selection, settings):
    validate_workbook(content, settings)
    try:
        left, top, right, bottom = range_boundaries(selection.cell_range)
        if None in (left, top, right, bottom) or not (
            1 <= left <= right <= 16384 and 1 <= top < bottom <= 1048576
        ):
            raise ValueError
    except ValueError as exc:
        raise ValueError(
            "Select a rectangular range including one header row and data, for example A1:D100."
        ) from exc
    if right - left + 1 > 200 or bottom - top > settings.max_result_rows:
        raise ValueError("Selected table exceeds the column or dataset row limit.")
    warnings = [
        "All selected rows, including blanks, subtotals and footers, are retained. Source completeness and freshness are unknown."
    ]
    with (
        workbook(content, data_only=False) as formulas,
        workbook(content, data_only=True) as cached,
    ):
        if selection.sheet not in formulas.sheetnames:
            raise ValueError("Choose an existing worksheet.")
        ws, values = formulas[selection.sheet], cached[selection.sheet]
        selected_merges(content, ws, (left, top, right, bottom))
        args = dict(min_row=top, max_row=bottom, min_col=left, max_col=right)
        formula_rows, value_rows = ws.iter_rows(**args), values.iter_rows(**args)
        header = next(formula_rows)
        next(value_rows)
        if any(c.data_type == "f" or not isinstance(c.value, str) for c in header):
            raise ValueError(
                "The header must contain distinct nonempty text column names; select its exact row and columns."
            )
        names = [c.value for c in header]
        columns = [[] for _ in names]
        formula_count, padded = 0, set()
        estimated_bytes = 0
        for row, cached_row in zip(formula_rows, value_rows, strict=True):
            for index, (cell, cache) in enumerate(zip(row, cached_row, strict=True)):
                value = cell.value
                if cell.data_type == "f":
                    formula_count += 1
                    if not selection.use_cached_formulas:
                        raise ValueError(
                            "Selected table contains formulas. Explicitly accept stored formula values, or upload a recalculated values-only workbook."
                        )
                    if cache.value is None:
                        raise ValueError(
                            f"Formula {cell.coordinate} has no stored value. Recalculate and save in Excel, or supply a values-only workbook."
                        )
                    value = cache.value
                if cell.data_type == "e" or cache.data_type == "e":
                    raise ValueError(
                        f"Excel error in {cell.coordinate}; correct it before analysis."
                    )
                # Simple zero masks encode displayed identifiers. Other custom
                # formatting is not interpreted as business units.
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and re.fullmatch(r"0{2,}", cell.number_format)
                ):
                    value = f"{value:0{len(cell.number_format)}d}"
                    padded.add(names[index])
                if not isinstance(
                    value, (str, int, float, bool, date, datetime, type(None))
                ):
                    raise ValueError(f"Unsupported Excel value in {cell.coordinate}.")
                estimated_bytes += len(str(value).encode("utf-8")) + 8
                if estimated_bytes > settings.max_dataset_bytes:
                    raise ValueError("Decoded table exceeds the dataset byte limit.")
                columns[index].append(value)
        arrays = []
        for name, values in zip(names, columns):
            try:
                arrays.append(pa.array(values))
            except (pa.ArrowException, TypeError):
                arrays.append(
                    pa.array(
                        [
                            v.isoformat()
                            if isinstance(v, (date, datetime))
                            else str(v)
                            if v is not None
                            else None
                            for v in values
                        ],
                        type=pa.string(),
                    )
                )
                warnings.append(
                    f"{name}: mixed cell types retained as text; review the intended type."
                )
        table = pa.Table.from_arrays(arrays, names=names)
        if table.nbytes > settings.max_dataset_bytes:
            raise ValueError("Decoded table exceeds the dataset byte limit.")
        if padded:
            warnings.append(
                "Simple zero-padded number formats preserved as text in: "
                + ", ".join(sorted(padded))
            )
        if formula_count:
            warnings.append(
                f"{formula_count} formula cells use stored cached values. Formula freshness is unknown; no formulas were evaluated."
            )
        return table, warnings
