from __future__ import annotations

import logging
from pathlib import Path

from data_analytics_agent.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_api_logging,
)


def test_api_logging_uses_one_rotating_file_and_disables_access_logs(
    tmp_path: Path,
) -> None:
    log_path = configure_api_logging(tmp_path)
    configure_api_logging(tmp_path)
    application_logger = logging.getLogger("data_analytics_agent.test")

    application_logger.info("run.completed run_id=test total_tokens=15")
    package_logger = logging.getLogger("data_analytics_agent")
    managed_handlers = [
        handler
        for handler in package_logger.handlers
        if getattr(handler, "_data_analytics_api_handler", False)
    ]
    for handler in managed_handlers:
        handler.flush()

    assert log_path == tmp_path / "logs" / "api.log"
    assert log_path.exists()
    assert "run.completed run_id=test total_tokens=15" in log_path.read_text(
        encoding="utf-8"
    )
    assert len(managed_handlers) == 2
    rotating = next(
        handler for handler in managed_handlers if hasattr(handler, "maxBytes")
    )
    assert rotating.maxBytes == LOG_MAX_BYTES
    assert rotating.backupCount == LOG_BACKUP_COUNT
    assert logging.getLogger("uvicorn.access").disabled is True
