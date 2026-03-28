import json
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import ClassVar, List, Optional

# Базовая директория проекта (Nickelfront)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

class Settings(BaseSettings):
    """Настройки приложения."""
    
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Игнорировать лишние переменные
    )
    
    DEFAULT_CORS_ORIGINS: ClassVar[List[str]] = ["http://localhost:3000", "http://localhost:5173"]

    DEFAULT_PARSE_QUERIES: ClassVar[List[str]] = [
        "nickel-based alloys",
        "superalloys",
        "heat resistant alloys",
    ]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5433/nickelfront"

    # Redis
    REDIS_URL: str = "redis://localhost:6380/0"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001
    DEBUG: bool = False

    # Security
    SECRET_KEY: Optional[str] = None
    _generated_secret_key: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # CORS
    CORS_ORIGINS: Optional[str] = None

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6380/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6380/0"

    # Flower (Celery monitoring)
    FLOWER_HOST: str = "http://localhost"
    FLOWER_PORT: int = 5555
    
    # Celery Beat - периодические задачи
    CELERY_BEAT_SCHEDULE_FILENAME: str = str(BASE_DIR / "celerybeat-schedule")
    
    # Парсинг по расписанию (в минутах)
    PARSE_SCHEDULE_INTERVAL: int = 60  # По умолчанию - каждый час
    PARSE_LIMIT_PER_RUN: int = 50  # Лимит статей на один запуск
    PARSE_QUERIES: Optional[str] = None

    # Vector Search
    CHROMA_DB_PATH: str = "./chroma_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_LOCAL_ONLY: bool = False
    EMBEDDING_CACHE_DIR: Optional[str] = "./models"

    # Qwen API (Alibaba Cloud)
    QWEN_TOKEN: Optional[str] = None
    QWEN_MODEL: str = "qwen-coder"
    QWEN_THINKING_ENABLED: bool = True
    QWEN_SEARCH_ENABLED: bool = True
    QWEN_AUTO_CONTINUE_ENABLED: bool = True
    QWEN_MAX_CONTINUES: int = 5
    QWEN_RATE_LIMIT_SECONDS: float = 2.0  # Мин. интервал между запросами
    QWEN_API_KEY: Optional[str] = None  # API ключ для защиты сервиса
    
    # Qwen Service (standalone HTTP сервис)
    QWEN_SERVICE_HOST: str = "127.0.0.1"
    QWEN_SERVICE_PORT: int = 8767

    # RAG Settings
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    RAG_SEARCH_K: int = 4  # Количество документов для поиска
    RAG_MAX_TOKENS: int = 1024

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on", "debug"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", "release", "prod", "production"}:
                return False
        return False

    def get_cors_origins(self) -> List[str]:
        """Parse CORS_ORIGINS from env (JSON array or CSV) with safe fallback."""
        return self._parse_list(self.CORS_ORIGINS, self.DEFAULT_CORS_ORIGINS)

    def get_parse_queries(self) -> List[str]:
        """Parse PARSE_QUERIES from env (JSON array or CSV) with safe fallback."""
        return self._parse_list(self.PARSE_QUERIES, self.DEFAULT_PARSE_QUERIES)

    @classmethod
    def _parse_list(cls, value: Optional[str], default: List[str]) -> List[str]:
        if value is None:
            return default
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return default
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
            return [item.strip() for item in raw.split(",") if item.strip()]
        return default

    def get_secret_key(self) -> str:
        """Получить SECRET_KEY или сгенерировать новый."""
        if self.SECRET_KEY:
            return self.SECRET_KEY
        if not self._generated_secret_key:
            self._generated_secret_key = secrets.token_urlsafe(32)
        return self._generated_secret_key

    def get_flower_url(self) -> str:
        """Сформировать URL Flower из FLOWER_HOST/FLOWER_PORT."""
        host = self.FLOWER_HOST.rstrip("/")
        host_tail = host.split("://", 1)[-1]
        if ":" in host_tail:
            return host
        return f"{host}:{self.FLOWER_PORT}"

    def resolve_path(self, value: str) -> str:
        """Преобразовать относительный путь в абсолютный от корня проекта."""
        if not value:
            return value
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str(BASE_DIR / path)


settings = Settings()
