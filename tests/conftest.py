"""Test configuration."""

import pytest
from typing import AsyncGenerator
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.db.session import get_db

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    """Create test DB engine."""
    return create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
async def test_db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a clean test DB session per test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.services import vector_service as vs
    vs._vector_service = None
    try:
        import tempfile, shutil
        tmp_dir = tempfile.mkdtemp(prefix="test_chroma_")
        vs.ChromaVectorService.CHROMA_PERSIST_DIR = tmp_dir
    except Exception:
        tmp_dir = None
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    if tmp_dir:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@pytest.fixture
async def client(engine, test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with DB override."""
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sample_paper_data():
    """Sample paper data for tests."""
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
    """Sample CORE API response for tests."""
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
