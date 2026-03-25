"""Конфигурация тестов."""

import pytest
from typing import AsyncGenerator, Generator
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.db.session import AsyncSessionLocal


# Тестовая БД в памяти (SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    """Создать тестовый движок БД."""
    return create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture(scope="session")
async def test_db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Создать тестовую сессию БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def client(test_db) -> AsyncGenerator[AsyncClient, None]:
    """Создать тестовый HTTP клиент."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_paper_data():
    """Пример данных статьи для тестов."""
    return {
        "title": "Nickel-based superalloys for high temperature applications",
        "authors": ["John Smith", "Jane Doe"],
        "publication_date": "2024-01-15",
        "journal": "Journal of Materials Science",
        "doi": "10.1234/test.2024.001",
        "abstract": "This paper studies nickel-based superalloys...",
        "full_text": "Full text of the paper...",
        "keywords": ["nickel", "superalloys", "high temperature"],
        "source": "CORE",
        "source_id": "123456",
        "url": "https://example.com/paper",
    }


@pytest.fixture
def core_search_response():
    """Пример ответа CORE API для тестов."""
    return {
        "results": [
            {
                "id": 123456,
                "title": "Nickel-based superalloys for high temperature applications",
                "authors": [{"name": "John Smith"}, {"name": "Jane Doe"}],
                "published_date": "2024-01-15",
                "journal": {"name": "Journal of Materials Science"},
                "doi": "10.1234/test.2024.001",
                "abstract": "This paper studies nickel-based superalloys...",
                "topics": ["nickel", "superalloys", "high temperature"],
                "source_fulltext_url": "https://example.com/paper",
                "has_full_text": True,
            }
        ],
        "total": 1,
    }
