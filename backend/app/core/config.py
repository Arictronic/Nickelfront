import json
import secrets
from pathlib import Path
from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _strip_wrapping_quotes(value):
    if isinstance(value, str):
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            return normalized[1:-1].strip()
        return normalized
    return value


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    DEFAULT_CORS_ORIGINS: ClassVar[list[str]] = ["http://localhost:3000", "http://localhost:5173"]

    DEFAULT_PARSE_QUERIES: ClassVar[list[str]] = [
        "nickel-based alloys",
        "superalloys",
        "heat resistant alloys",
    ]


    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5433/nickelfront"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 15
    DB_CONNECT_TIMEOUT: int = 10


    REDIS_URL: str = "redis://localhost:6380/0"


    CORE_API_KEY: str | None = None
    CORE_API_TIMEOUT: float = 40.0
    OPENALEX_API_KEY: str | None = None
    SEMANTIC_SCHOLAR_API_KEY: str | None = None


    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001
    DEBUG: bool = False


    SECRET_KEY: str | None = None
    _generated_secret_key: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14




    REFRESH_TOKEN_REUSE_GRACE_SECONDS: int = 60


    CORS_ORIGINS: str | None = None


    CELERY_BROKER_URL: str = "redis://localhost:6380/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6380/0"



    CELERY_WORKERS: int = 1
    WORKER_CONCURRENCY: int = 5
    WORKER_POOL: str = "threads"
    WORKER_QUEUES: str = "celery"


    FLOWER_HOST: str = "http://localhost"
    FLOWER_PORT: int = 5555


    CELERY_BEAT_SCHEDULE_FILENAME: str = str(BASE_DIR / "celerybeat-schedule")


    PARSE_SCHEDULE_INTERVAL: int = 60
    PARSE_LIMIT_PER_RUN: int = 50
    PARSE_QUERIES: str | None = None


    CHROMA_DB_PATH: str = "./chroma_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_LOCAL_ONLY: bool = False
    EMBEDDING_CACHE_DIR: str | None = "./models"


    QWEN_TOKEN: str | None = None
    QWEN_MODEL: str = "qwen-coder"
    QWEN_USE_STANDALONE: bool = False
    QWEN_THINKING_ENABLED: bool = True
    QWEN_SEARCH_ENABLED: bool = True
    QWEN_AUTO_CONTINUE_ENABLED: bool = True
    QWEN_MAX_CONTINUES: int = 5
    QWEN_RATE_LIMIT_SECONDS: float = 2.0
    QWEN_API_KEY: str | None = None



    QWEN_CHAT_TIMEOUT_SECONDS: float = 300.0
    QWEN_CHAT_RETRY_ON_TIMEOUT: bool = True


    QWEN_SERVICE_HOST: str = "127.0.0.1"
    QWEN_SERVICE_PORT: int = 8767


    QWEN_QUEUE_ENABLED: bool = True
    QWEN_QUEUE_NAME: str = "qwen"
    QWEN_QUEUE_TIMEOUT: float = 360.0

    QWEN_QUEUE_TASK_RATE_LIMIT: str | None = None
    QWEN_QUEUE_WORKERS: int = 1
    QWEN_WORKER_CONCURRENCY: int = 5
    QWEN_WORKER_POOL: str = "threads"


    CONTENT_QUEUE_NAME: str = "content"
    CONTENT_WORKERS: int = 1
    CONTENT_WORKER_CONCURRENCY: int = 5
    CONTENT_WORKER_POOL: str = "threads"


    QWEN_MARKDOWN_PAGES_PER_REQUEST: int = 1
    QWEN_MARKDOWN_PAGE_CHARS: int = 14000


    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    RAG_SEARCH_K: int = 4
    RAG_MAX_TOKENS: int = 1024
    PAPER_PDF_DIR: str = "./storage/papers_pdf"


    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "./logs/app.log"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        value = _strip_wrapping_quotes(value)
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

    @field_validator(
        "QWEN_THINKING_ENABLED",
        "QWEN_SEARCH_ENABLED",
        "QWEN_AUTO_CONTINUE_ENABLED",
        "QWEN_USE_STANDALONE",
        "QWEN_CHAT_RETRY_ON_TIMEOUT",
        "QWEN_QUEUE_ENABLED",
        "EMBEDDING_LOCAL_ONLY",
        mode="before",
    )
    @classmethod
    def _strip_bool_quotes(cls, value):
        return _strip_wrapping_quotes(value)

    @field_validator(
        "QWEN_MAX_CONTINUES",
        "QWEN_QUEUE_WORKERS",
        "QWEN_WORKER_CONCURRENCY",
        "CONTENT_WORKERS",
        "CONTENT_WORKER_CONCURRENCY",
        "CELERY_WORKERS",
        "WORKER_CONCURRENCY",
        "API_PORT",
        "FLOWER_PORT",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_CONNECT_TIMEOUT",
        mode="before",
    )
    @classmethod
    def _strip_int_quotes(cls, value):
        return _strip_wrapping_quotes(value)

    def get_cors_origins(self) -> list[str]:
        """Parse CORS_ORIGINS from env (JSON array or CSV) with safe fallback."""
        return self._parse_list(self.CORS_ORIGINS, self.DEFAULT_CORS_ORIGINS)

    def get_parse_queries(self) -> list[str]:
        """Parse PARSE_QUERIES from env (JSON array or CSV) with safe fallback."""
        return self._parse_list(self.PARSE_QUERIES, self.DEFAULT_PARSE_QUERIES)

    @classmethod
    def _parse_list(cls, value: str | None, default: list[str]) -> list[str]:
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
