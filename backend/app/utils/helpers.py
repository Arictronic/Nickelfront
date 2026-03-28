"""
Модуль вспомогательных утилит.

Содержит функции для логирования, обработки файлов и другие утилиты.
"""

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable, TypeVar
from functools import wraps
from loguru import logger

T = TypeVar('T')


def get_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """
    Вычисляет хэш файла для проверки целостности.

    Args:
        file_path: Путь к файлу.
        algorithm: Алгоритм хеширования (md5, sha256, etc.).

    Returns:
        str: Шестнадцатеричная строка хэша.

    Example:
        >>> get_file_hash("document.pdf")
        'd41d8cd98f00b204e9800998ecf8427e'
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

    Example:
        >>> format_file_size(1572864)
        '1.50 MB'
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

    Example:
        >>> ensure_directory("./data/uploads")
        PosixPath('/project/data/uploads')
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

    Example:
        >>> generate_unique_filename("document.pdf", prefix="upload")
        'upload_20260328_143022_document.pdf'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(original_filename)

    if prefix:
        return f"{prefix}_{timestamp}_{path.name}"
    return f"{timestamp}_{path.name}"


def retry_with_delay(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """
    Декоратор для повторного вызова функции при ошибке.

    Args:
        max_attempts: Максимальное количество попыток.
        delay: Начальная задержка в секундах.
        backoff: Множитель задержки.
        exceptions: Кортеж исключений для обработки.

    Returns:
        Декоратор для функции.

    Example:
        >>> @retry_with_delay(max_attempts=3, delay=1.0)
        ... def unstable_operation():
        ...     ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"Попытка {attempt + 1}/{max_attempts} не удалась: {e}. "
                        f"Следующая попытка через {current_delay:.1f} сек"
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff

            logger.error(f"Все {max_attempts} попыток не удались")
            raise last_exception  # type: ignore

        return wrapper
    return decorator


def measure_time(operation_name: str = "Операция"):
    """
    Декоратор для замера времени выполнения функции.

    Args:
        operation_name: Название операции для логирования.

    Returns:
        Декоратор для функции.

    Example:
        >>> @measure_time("Обработка файла")
        ... def process_file():
        ...     ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.debug(f"{operation_name} заняла {elapsed:.3f} сек")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"{operation_name} завершилась ошибкой через {elapsed:.3f} сек: {e}")
                raise

        return wrapper
    return decorator


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
        self.start_time = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        """Окончание замера времени и логирование результата."""
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time
        logger.debug(f"{self.operation_name} заняла {elapsed:.3f} сек")

    @property
    def elapsed(self) -> float:
        """Возвращает прошедшее время в секундах."""
        if self.start_time is None:
            return 0.0
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Обрезает текст до указанной длины.

    Args:
        text: Исходный текст.
        max_length: Максимальная длина.
        suffix: Суффикс для обрезанного текста.

    Returns:
        str: Обрезанный текст.

    Example:
        >>> truncate_text("Длинный текст", max_length=10)
        'Длинный...'
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def sanitize_filename(filename: str) -> str:
    """
    Очищает имя файла от недопустимых символов.

    Args:
        filename: Исходное имя файла.

    Returns:
        str: Очищенное имя файла.

    Example:
        >>> sanitize_filename("file/name?.txt")
        'file_name_.txt'
    """
    # Недопустимые символы в именах файлов Windows/Linux
    invalid_chars = '<>:"/\\|？*'

    sanitized = filename
    for char in invalid_chars:
        sanitized = sanitized.replace(char, "_")

    # Удаляем ведущие/замыкающие точки и пробелы
    sanitized = sanitized.strip(". ")

    return sanitized or "unnamed_file"
