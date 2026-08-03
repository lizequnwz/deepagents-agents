"""Advisor reference-source protocol and canonical synthetic implementation."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol

from general_agent.advisor_matching.schemas import AdvisorRecord, MASTER_COLUMNS


class AdvisorReferenceSource(Protocol):
    source_kind: str
    schema_version: str

    def iter_records(self) -> Iterable[AdvisorRecord]: ...


class SyntheticAdvisorReferenceSource:
    source_kind = "synthetic"
    schema_version = "1"

    def __init__(self, path: Path) -> None:
        self.path = path

    def iter_records(self) -> Iterator[AdvisorRecord]:
        with self.path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            available = tuple(reader.fieldnames or ())
            if any(column not in available for column in MASTER_COLUMNS):
                raise ValueError(
                    "Synthetic advisor schema is missing one or more canonical columns."
                )
            for row in reader:
                crd = str(row["CRD_NUMBER"] or "").strip()
                if not crd:
                    raise ValueError(
                        f"Master advisor CRD is missing: {crd!r}."
                    )
                if not str(row["FIRST_NAME"] or "").strip() or not str(row["LAST_NAME"] or "").strip():
                    raise ValueError(f"Master advisor {crd} is missing a required first or last name.")
                yield AdvisorRecord(**{column.lower(): str(row[column] or "").strip() for column in MASTER_COLUMNS})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
