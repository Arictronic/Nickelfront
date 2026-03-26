"""
Модуль конфигурации приложения.

Содержит все настройки проекта: пути к файлам, параметры моделей,
настройки векторной базы данных и API.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Класс настроек приложения.

    Загружает переменные окружения из .env файла и предоставляет
    типизированный доступ к конфигурации проекта.
    """

    # === Настройки LLM API ===
    #: API ключ для доступа к LLM
    llm_api_key: str = ""
    #: Базовый URL API для LLM (OpenAI-compatible)
    llm_api_base_url: str = "https://api.openai.com/v1"
    #: Название модели LLM для генерации ответов
    llm_model_name: str = "gpt-3.5-turbo"

    # === Настройки эмбеддингов ===
    #: Название модели для создания эмбеддингов (легковесная)
    embedding_model_name: str = "all-MiniLM-L6-v2"
    #: Устройство для вычислений эмбеддингов (cpu/cuda)
    embedding_device: str = "cpu"

    # === Настройки ChromaDB ===
    #: Директория для постоянного хранения векторной базы
    chroma_persist_directory: str = "./data/db"

    # === Настройки сервера ===
    #: Хост для запуска FastAPI сервера
    host: str = "0.0.0.0"
    #: Порт для запуска FastAPI сервера
    port: int = 8000

    # === Лимиты и параметры обработки ===
    #: Максимальный размер загружаемого файла в МБ
    max_file_size_mb: int = 50
    #: Максимальный размер чанка текста (символов)
    max_chunk_size: int = 1000
    #: Перекрытие между чанками (символов)
    chunk_overlap: int = 200
    #: Количество документов для поиска при ответе на вопрос
    search_k: int = 4

    # === Пути к директориям ===
    #: Корневая директория проекта rag
    root_dir: Path = Path(__file__).parent.parent
    #: Директория для хранения данных (БД, загруженные файлы)
    data_dir: Path = Path(__file__).parent.parent / "data"
    #: Директория для загруженных файлов
    uploads_dir: Path = Path(__file__).parent.parent / "data" / "uploads"
    #: Директория для векторной базы данных
    db_dir: Path = Path(__file__).parent.parent / "data" / "db"

    class Config:
        """Конфигурация загрузки переменных окружения."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def __init__(self, **kwargs):
        """
        Инициализация настроек и создание необходимых директорий.

        После загрузки настроек автоматически создаются все необходимые
        директории для работы приложения.
        """
        super().__init__(**kwargs)
        self._create_directories()

    def _create_directories(self) -> None:
        """
        Создаёт необходимые директории для работы приложения.

        Создаёт директорию для данных, загрузок и векторной базы,
        если они ещё не существуют.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_file_size_bytes(self) -> int:
        """
        Возвращает максимальный размер файла в байтах.

        Returns:
            int: Максимальный размер файла в байтах.
        """
        return self.max_file_size_mb * 1024 * 1024


# Глобальный экземпляр настроек
settings = Settings()
