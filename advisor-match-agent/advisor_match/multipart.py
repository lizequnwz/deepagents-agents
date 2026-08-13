"""Bounded multipart parsing that never spools request parts to disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

import python_multipart
from fastapi import Request
from python_multipart.multipart import parse_options_header

from advisor_match.files import InMemoryFile

_CONFIGURATION_LIMIT = 64 * 1024
_REQUEST_OVERHEAD_LIMIT = 1024 * 1024


class MultipartInputError(ValueError):
    pass


class UploadTooLarge(MultipartInputError):
    pass


class UnsupportedMultipartMediaType(MultipartInputError):
    pass


@dataclass(frozen=True, slots=True)
class MultipartPayload:
    file: InMemoryFile
    configuration: str | None = None


@dataclass(slots=True)
class _Part:
    name: str = ""
    filename: str | None = None
    content_type: str | None = None
    data: bytearray = field(default_factory=bytearray)
    header_name: bytearray = field(default_factory=bytearray)
    header_value: bytearray = field(default_factory=bytearray)
    headers: dict[bytes, bytes] = field(default_factory=dict)


async def parse_multipart_request(
    request: Request,
    *,
    max_upload_bytes: int,
    configuration_required: bool,
) -> MultipartPayload:
    content_type = request.headers.get("content-type", "")
    media_type, options = parse_options_header(content_type)
    if media_type != b"multipart/form-data" or b"boundary" not in options:
        raise UnsupportedMultipartMediaType(
            "Content-Type must be multipart/form-data."
        )

    request_limit = max_upload_bytes + _REQUEST_OVERHEAD_LIMIT
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > request_limit:
                raise UploadTooLarge("The multipart request exceeds the upload limit.")
        except ValueError as exc:
            raise MultipartInputError("Content-Length must be an integer.") from exc

    parts: dict[str, _Part] = {}
    current = _Part()

    def on_part_begin() -> None:
        nonlocal current
        current = _Part()

    def on_part_data(data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        limit = max_upload_bytes if current.filename is not None else _CONFIGURATION_LIMIT
        if len(current.data) + len(chunk) > limit:
            if current.filename is not None:
                raise UploadTooLarge("The uploaded file exceeds the configured limit.")
            raise MultipartInputError("The configuration part is too large.")
        current.data.extend(chunk)

    def on_part_end() -> None:
        if not current.name:
            raise MultipartInputError("Each multipart part must have a name.")
        if current.name in parts:
            raise MultipartInputError(f"Duplicate multipart part {current.name!r}.")
        parts[current.name] = current

    def on_header_field(data: bytes, start: int, end: int) -> None:
        current.header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        current.header_value.extend(data[start:end])

    def on_header_end() -> None:
        name = bytes(current.header_name).lower()
        value = bytes(current.header_value)
        current.headers[name] = value
        current.header_name.clear()
        current.header_value.clear()

    def on_headers_finished() -> None:
        disposition = current.headers.get(b"content-disposition", b"")
        _value, parameters = parse_options_header(disposition)
        raw_name = parameters.get(b"name")
        if raw_name is None:
            raise MultipartInputError("Multipart part is missing its name.")
        current.name = raw_name.decode("utf-8", errors="replace")
        raw_filename = parameters.get(b"filename")
        if raw_filename is not None:
            current.filename = _safe_filename(
                raw_filename.decode("utf-8", errors="replace")
            )
        raw_content_type = current.headers.get(b"content-type")
        if raw_content_type:
            current.content_type = raw_content_type.decode(
                "ascii", errors="replace"
            )

    callbacks: dict[str, Any] = {
        "on_part_begin": on_part_begin,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_end": lambda: None,
    }
    parser = python_multipart.MultipartParser(options[b"boundary"], callbacks)
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > request_limit:
                raise UploadTooLarge("The multipart request exceeds the upload limit.")
            parser.write(chunk)
        parser.finalize()
    except MultipartInputError:
        raise
    except Exception as exc:
        raise MultipartInputError(f"The multipart request is invalid: {exc}") from exc

    unknown = set(parts) - {"file", "configuration"}
    if unknown:
        raise MultipartInputError(
            f"Unsupported multipart part(s): {', '.join(sorted(unknown))}."
        )
    file_part = parts.get("file")
    if file_part is None or file_part.filename is None:
        raise MultipartInputError("A file part with a filename is required.")
    configuration_part = parts.get("configuration")
    if configuration_required and configuration_part is None:
        raise MultipartInputError("A configuration part is required.")
    if configuration_part is not None and configuration_part.filename is not None:
        raise MultipartInputError("The configuration part must be plain JSON text.")
    try:
        configuration = (
            bytes(configuration_part.data).decode("utf-8")
            if configuration_part is not None
            else None
        )
    except UnicodeError as exc:
        raise MultipartInputError("The configuration must be UTF-8 JSON.") from exc
    return MultipartPayload(
        file=InMemoryFile(
            filename=file_part.filename,
            content=bytes(file_part.data),
            content_type=file_part.content_type,
        ),
        configuration=configuration,
    )


def _safe_filename(value: str) -> str:
    normalized = value.replace("\\", "/")
    name = PurePath(normalized).name.strip()
    if not name or name in {".", ".."}:
        raise MultipartInputError("The uploaded filename is invalid.")
    return name
