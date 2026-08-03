"""Human-readable, metadata-only operational logging."""

from __future__ import annotations

import logging
import os
import re
import shlex
import traceback
from contextvars import ContextVar, Token
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from general_agent.config import Settings


_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
_HANDLER_MARKER = "_advisor_match_file_handler"


def configure_logging(settings: Settings) -> Path:
    """Configure the application logger with one rotating file handler."""

    settings.logs_root.mkdir(parents=True, exist_ok=True)
    application_logger = logging.getLogger("general_agent")
    _remove_managed_handlers(application_logger)

    handler = RotatingFileHandler(
        settings.api_log,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(settings.log_level)
    handler.setFormatter(HumanReadableFormatter(_secret_values()))
    application_logger.addHandler(handler)
    application_logger.setLevel(settings.log_level)
    application_logger.propagate = False
    return settings.api_log


def shutdown_logging() -> None:
    """Flush and close only handlers installed by this application."""

    application_logger = logging.getLogger("general_agent")
    _remove_managed_handlers(application_logger)
    if not application_logger.handlers:
        application_logger.setLevel(logging.NOTSET)
        application_logger.propagate = True


def set_request_id(request_id: str) -> Token[str | None]:
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Write one structured-but-readable operational event."""

    request_id = _REQUEST_ID.get()
    if request_id and "request_id" not in fields:
        fields = {"request_id": request_id, **fields}
    logger.log(
        level,
        event,
        extra={"event_name": event, "event_fields": fields},
        exc_info=exc_info,
    )


class HumanReadableFormatter(logging.Formatter):
    """Format safe metadata as compact key/value text with message-free traces."""

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
        event = str(getattr(record, "event_name", record.name))
        fields = getattr(record, "event_fields", {})
        rendered = [
            timestamp,
            f"{record.levelname:<5}",
            self._redact(event),
        ]
        if isinstance(fields, dict):
            rendered.extend(
                f"{key}={self._render_value(value)}"
                for key, value in fields.items()
            )
        line = " ".join(rendered)
        if record.exc_info:
            line += "\n" + self._safe_traceback(record.exc_info)
        return line

    def _render_value(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            value = ",".join(str(item) for item in value)
        text = self._redact(str(value)).replace("\r", "\\r").replace("\n", "\\n")
        if re.fullmatch(r"[A-Za-z0-9_./:{}@+-]+", text):
            return text
        return shlex.quote(text)

    def _safe_traceback(self, exc_info: Any) -> str:
        exc_type, _exc_value, exc_traceback = exc_info
        lines = ["Traceback (most recent call last):"]
        frames = traceback.extract_tb(exc_traceback)[-40:]
        for frame in frames:
            filename = self._redact(frame.filename)
            lines.append(
                f'  File "{filename}", line {frame.lineno}, in {frame.name}'
            )
        name = getattr(exc_type, "__name__", "Exception")
        lines.append(self._redact(name))
        return "\n".join(lines)

    def _redact(self, value: str) -> str:
        result = value
        for secret in self.secrets:
            result = result.replace(secret, "[REDACTED]")
        return result


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.flush()
            handler.close()


def _secret_values() -> tuple[str, ...]:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    values = {
        value
        for key, value in os.environ.items()
        if any(marker in key.upper() for marker in markers) and len(value) >= 7
    }
    return tuple(sorted(values, key=len, reverse=True))
