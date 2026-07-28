"""Bounded local logging for the FastAPI process."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class _UtcFormatter(logging.Formatter):
    converter = time.gmtime


def configure_api_logging(project_root: Path) -> Path:
    """Configure one concise console/file pipeline and return its log path."""

    log_directory = project_root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "api.log"

    formatter = _UtcFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, console_handler):
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        setattr(handler, "_data_analytics_api_handler", True)

    loggers = [
        logging.getLogger("data_analytics_agent"),
        logging.getLogger("uvicorn.error"),
    ]
    old_handlers: dict[int, logging.Handler] = {}
    for logger in loggers:
        for handler in list(logger.handlers):
            if getattr(handler, "_data_analytics_api_handler", False):
                logger.removeHandler(handler)
                old_handlers[id(handler)] = handler
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    for handler in old_handlers.values():
        handler.close()

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    return log_path
