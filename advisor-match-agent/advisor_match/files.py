"""Memory-only file values shared across the stateless request pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


class InvalidUploadError(ValueError):
    """The uploaded bytes or declared table format cannot be processed."""


@dataclass(frozen=True, slots=True)
class InMemoryFile:
    filename: str
    content: bytes
    content_type: str | None = None

    @property
    def suffix(self) -> str:
        return Path(self.filename).suffix.casefold()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def open(self) -> BytesIO:
        return BytesIO(self.content)

    def validate_table_type(self) -> None:
        if self.suffix not in {".csv", ".xlsx"}:
            raise InvalidUploadError(
                "Advisor Match accepts only CSV or XLSX files."
            )
