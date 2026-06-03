"""Logging setup helpers for the standalone Qwen service."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO


def setup_qwen_logging(project_root: Path, *, stdout: TextIO | None = None) -> Path:
    """Configure qwen service logging to the shared project logs directory."""
    raw_log_file = (os.getenv("QWEN_SERVICE_LOG_FILE") or "").strip()
    if raw_log_file:
        configured = Path(raw_log_file)
        log_file = configured if configured.is_absolute() else project_root / configured
    else:
        log_file = project_root / "logs" / "qwen_service.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("NICKELFRONT_LOG_LEVEL", os.getenv("LOG_LEVEL", "DEBUG")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | qwen_service | pid=%(process)d | %(name)s:%(lineno)d - %(message)s"
    )

    stream_handler = logging.StreamHandler(stdout or sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=int(os.getenv("QWEN_SERVICE_LOG_MAX_BYTES", "5242880") or 5_242_880),
        backupCount=int(os.getenv("QWEN_SERVICE_LOG_BACKUP_COUNT", "5") or 5),
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    # Uvicorn has two different formatter types: a regular formatter for
    # server lifecycle logs and an AccessFormatter for HTTP access logs.  The
    # access formatter expects 5 arguments, so it crashes if it is accidentally
    # attached to messages like ``Started server process [%d]``.  Keep every
    # uvicorn logger on the same plain qwen formatter and disable propagation to
    # avoid duplicate console/file records.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = list(root_logger.handlers)
        uvicorn_logger.setLevel(level)
        uvicorn_logger.propagate = False

    logging.info("Qwen service logging initialized: %s", log_file)
    return log_file
