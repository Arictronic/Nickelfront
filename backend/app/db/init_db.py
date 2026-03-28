"""Скрипт для инициализации базы данных."""
import asyncio

from app.db.base import Base
from app.db.models import (
    RefreshToken,  # noqa: F401
    User,  # noqa: F401
)
from app.db.session import engine


async def init_db():
    """Создать все таблицы в БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("База данных инициализирована")


if __name__ == "__main__":
    asyncio.run(init_db())
