import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from loguru import logger

from app.core.config import settings


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_service_name(service_name: str) -> str:
    explicit = (os.getenv("NICKELFRONT_SERVICE_NAME") or "").strip()
    if explicit:
        return explicit
    if _env_bool("QWEN_GATEWAY_WORKER", False):
        return "qwen_worker"
    return service_name


def _resolve_log_path(service_name: str, log_file: str | None) -> Path:
    service_env_map = {
        "backend_api": "BACKEND_API_LOG_FILE",
        "celery_worker": "CELERY_WORKER_LOG_FILE",
        "content_worker": "CONTENT_WORKER_LOG_FILE",
        "qwen_worker": "QWEN_WORKER_LOG_FILE",
    }
    service_env_name = service_env_map.get(service_name)
    if service_env_name:
        service_env_log_file = (os.getenv(service_env_name) or "").strip()
        if service_env_log_file:
            return Path(settings.resolve_path(service_env_log_file))
    env_log_file = (os.getenv("NICKELFRONT_LOG_FILE") or "").strip()
    if env_log_file:
        return Path(settings.resolve_path(env_log_file))
    if log_file:
        return Path(settings.resolve_path(log_file))
    if service_name == "backend_api" and settings.LOG_FILE:
        return Path(settings.resolve_path(settings.LOG_FILE))
    return Path(settings.resolve_path(f"./logs/{service_name}.log"))


def setup_logging(
    service_name: str = "backend_api",
    log_file: str | None = None,
    log_level: str | None = None,
) -> Path:
    """Configure readable process-aware logging for one Nickelfront service.

    Every Windows process gets its own service role name:
      - backend_api      -> logs/app.log, unless LOG_FILE overrides it
      - celery_worker    -> logs/celery_worker.log
      - qwen_worker      -> logs/qwen_worker.log
      - qwen_service     -> configured in qwen_service/service.py

    The qwen worker intentionally has a separate log file, so startup/import noise
    from regular parser/content workers is not mixed with the Qwen gateway queue.
    """
    service_name = _resolve_service_name(service_name)
    level_name = (log_level or os.getenv("NICKELFRONT_LOG_LEVEL") or settings.LOG_LEVEL or ("DEBUG" if settings.DEBUG else "INFO")).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    log_path = _resolve_log_path(service_name, log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    console_format = (
        f"<green>{{time:YYYY-MM-DD HH:mm:ss.SSS}}</green> | "
        f"<level>{{level: <8}}</level> | "
        f"{service_name} | pid=<cyan>{{process.id}}</cyan> | "
        f"<cyan>{{name}}</cyan>:<cyan>{{function}}</cyan>:<cyan>{{line}}</cyan> - "
        f"<level>{{message}}</level>"
    )
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        f"{service_name} | pid={{process.id}} | "
        "{name}:{function}:{line} - {message}"
    )


    logger.remove()
    logger.add(
        sys.stdout,
        level=level_name,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        format=console_format,
        colorize=True,
    )
    logger.add(
        str(log_path),
        level=level_name,
        rotation=os.getenv("NICKELFRONT_LOG_ROTATION", "20 MB"),
        retention=os.getenv("NICKELFRONT_LOG_RETENTION", "14 days"),
        enqueue=True,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        format=file_format,
        encoding="utf-8",
    )


    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)

    stdlib_format = logging.Formatter(
        f"%(asctime)s | %(levelname)-8s | {service_name} | pid=%(process)d | %(name)s:%(lineno)d - %(message)s"
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(stdlib_format)

    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=20 * 1024 * 1024,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(stdlib_format)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    app_level_loggers = (
        "app",
        "celery",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    )
    noisy_dependency_loggers = (
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.orm",
        "sqlalchemy.pool",
        "asyncpg",
        "httpx",
        "httpcore",
        "urllib3",
        "chromadb",
        "sentence_transformers",
    )

    for logger_name in app_level_loggers:
        logging.getLogger(logger_name).setLevel(numeric_level)

    for logger_name in noisy_dependency_loggers:
        logging.getLogger(logger_name).setLevel(max(numeric_level, logging.WARNING))


    for logger_name in ("celery.app.trace",):
        logging.getLogger(logger_name).propagate = True

    logger.info("Logging initialized: service={} file={}", service_name, log_path)
    return log_path
