import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from loguru import logger

from app.core.config import settings


def setup_logging(
    service_name: str = "backend_api",
    log_file: str | None = None,
    log_level: str | None = None,
) -> Path:
    """Configure unified logging (stdout + file) for a service."""
    level_name = (log_level or settings.LOG_LEVEL or ("DEBUG" if settings.DEBUG else "INFO")).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    if log_file:
        log_path = Path(settings.resolve_path(log_file))
    elif service_name == "backend_api" and settings.LOG_FILE:
        log_path = Path(settings.resolve_path(settings.LOG_FILE))
    else:
        log_path = Path(settings.resolve_path(f"./logs/{service_name}.log"))

    log_path.parent.mkdir(parents=True, exist_ok=True)

    # loguru handlers
    logger.remove()
    logger.add(
        sys.stdout,
        level=level_name,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        ),
    )
    logger.add(
        str(log_path),
        level=level_name,
        rotation="20 MB",
        retention="14 days",
        enqueue=True,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    # stdlib logging for uvicorn/celery/etc.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s")
    )

    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=20 * 1024 * 1024,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s")
    )

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    app_level_loggers = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "celery",
    )
    noisy_dependency_loggers = (
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.orm",
        "sqlalchemy.pool",
        "asyncpg",
        "httpx",
        "httpcore",
    )

    for logger_name in app_level_loggers:
        logging.getLogger(logger_name).setLevel(numeric_level)

    for logger_name in noisy_dependency_loggers:
        logging.getLogger(logger_name).setLevel(max(numeric_level, logging.WARNING))

    logger.info("Logging initialized for {} -> {}", service_name, log_path)
    return log_path
