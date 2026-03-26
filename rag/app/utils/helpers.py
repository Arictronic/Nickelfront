"""
Модуль вспомогательных утилит.

Содержит функции для логирования, обработки файлов и другие утилиты.
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def get_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """
    Вычисляет хэш файла для проверки целостности.

    Args:
        file_path: Путь к файлу.
        algorithm: Алгоритм хеширования (md5, sha256, etc.).

    Returns:
        str: Шестнадцатеричная строка хэша.
    """
    hash_func = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)

    return hash_func.hexdigest()


def format_file_size(size_bytes: int) -> str:
    """
    Форматирует размер файла в человекочитаемый вид.

    Args:
        size_bytes: Размер в байтах.

    Returns:
        str: Форматированная строка (например, "1.5 MB").
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def ensure_directory(path: str) -> Path:
    """
    Гарантирует существование директории.

    Args:
        path: Путь к директории.

    Returns:
        Path: Объект Path созданной/существующей директории.
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def generate_unique_filename(
    original_filename: str,
    prefix: Optional[str] = None,
) -> str:
    """
    Генерирует уникальное имя файла с временной меткой.

    Args:
        original_filename: Исходное имя файла.
        prefix: Опциональный префикс.

    Returns:
        str: Уникальное имя файла.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(original_filename)

    if prefix:
        return f"{prefix}_{timestamp}_{path.name}"
    return f"{timestamp}_{path.name}"


class Timer:
    """
    Контекстный менеджер для замера времени выполнения кода.

    Example:
        >>> with Timer("Обработка файла"):
        ...     process_file()
    """

    def __init__(self, operation_name: str = "Операция"):
        """
        Инициализация таймера.

        Args:
            operation_name: Название операции для логирования.
        """
        self.operation_name = operation_name
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def __enter__(self) -> "Timer":
        """Начало замера времени."""
        self.start_time = datetime.now().timestamp()
        return self

    def __exit__(self, *args: Any) -> None:
        """Окончание замера времени и логирование результата."""
        self.end_time = datetime.now().timestamp()
        elapsed = self.end_time - self.start_time
        logger.debug(f"{self.operation_name} заняла {elapsed:.3f} сек")

    @property
    def elapsed(self) -> float:
        """Возвращает прошедшее время в секундах."""
        if self.start_time is None:
            return 0.0
        if self.end_time is None:
            return datetime.now().timestamp() - self.start_time
        return self.end_time - self.start_time
