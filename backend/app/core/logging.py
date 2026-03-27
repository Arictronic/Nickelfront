import sys
from pathlib import Path
from loguru import logger

from app.core.config import settings


def setup_logging():
    """Настроить логирование приложения."""
    logger.remove()  # Удалить стандартный обработчик

    log_level = (settings.LOG_LEVEL or "INFO").upper()
    log_file_raw = settings.LOG_FILE or "./logs/app.log"
    log_file_path = Path(settings.resolve_path(log_file_raw))
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    if "{time" in log_file_path.name:
        log_file_pattern = str(log_file_path)
    else:
        log_file_pattern = str(
            log_file_path.with_name(
                f"{log_file_path.stem}_{{time:YYYY-MM-DD}}{log_file_path.suffix}"
            )
        )
    
    # Добавляем консольный вывод
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
    )
    
    # Добавляем запись в файл
    logger.add(
        log_file_pattern,
        rotation="00:00",
        retention="7 days",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
