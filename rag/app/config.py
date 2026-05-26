"""
Модуль конфигурации приложения.

Содержит все настройки проекта: пути к файлам, параметры моделей,
настройки векторной базы данных и API.
"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Класс настроек приложения.

    Загружает переменные окружения из .env файла и предоставляет
    типизированный доступ к конфигурации проекта.
    """



    llm_api_key: str = ""

    llm_api_base_url: str = "https://api.openai.com/v1"

    llm_model_name: str = "gpt-3.5-turbo"



    embedding_model_name: str = "all-MiniLM-L6-v2"

    embedding_device: str = "cpu"



    chroma_persist_directory: str = "./data/db"



    host: str = "0.0.0.0"

    port: int = 8000



    max_file_size_mb: int = 50

    max_chunk_size: int = 1000

    chunk_overlap: int = 200

    search_k: int = 4



    root_dir: Path = Path(__file__).parent.parent

    data_dir: Path = Path(__file__).parent.parent / "data"

    uploads_dir: Path = Path(__file__).parent.parent / "data" / "uploads"

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



settings = Settings()
