import secrets
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List

# Базовая директория проекта (Nickelfront)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    """Настройки приложения."""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/nickelfront"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    def get_secret_key(self) -> str:
        """Получить SECRET_KEY или сгенерировать новый."""
        if self.SECRET_KEY:
            return self.SECRET_KEY
        return secrets.token_urlsafe(32)

    class Config:
        env_file = BASE_DIR / "backend" / ".env"
        case_sensitive = True


settings = Settings()
