"""Скрипт для инициализации базы данных."""
import asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.session import engine
from app.db.models import PatentTask  # импорт моделей для регистрации


async def init_db():
    """Создать все таблицы в БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("База данных инициализирована")


if __name__ == "__main__":
    asyncio.run(init_db())
