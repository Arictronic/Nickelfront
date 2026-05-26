"""Unit тесты для PaperService."""

import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.paper_service import PaperService
from shared.schemas.paper import PaperCreate
from app.db.models.paper import Paper


class TestPaperService:
    """Тесты для PaperService."""

    @pytest.fixture
    async def service(self, test_db: AsyncSession):
        """Создать сервис."""
        return PaperService(test_db)

    @pytest.fixture
    def sample_paper_create(self):
        """Пример данных для создания статьи."""
        return PaperCreate(
            title="Test Paper",
            authors=["Author One", "Author Two"],
            publication_date=datetime(2024, 1, 15),
            journal="Test Journal",
            doi="10.1234/test.2024.001",
            abstract="Test abstract",
            full_text="Test full text",
            keywords=["test", "paper"],
            source="CORE",
            source_id="123456",
            url="https://example.com/paper",
        )

    @pytest.mark.asyncio
    async def test_create_paper(self, service, sample_paper_create, test_db):
        """Тест создания статьи."""
        paper = await service.create_paper(sample_paper_create)

        assert paper.id is not None
        assert paper.title == "Test Paper"
        assert len(paper.authors) == 2
        assert paper.doi == "10.1234/test.2024.001"
        assert paper.source == "CORE"

    @pytest.mark.asyncio
    async def test_create_paper_duplicate_doi(self, service, sample_paper_create, test_db):
        """Тест создания дубликата статьи (по DOI)."""

        paper1 = await service.create_paper(sample_paper_create)


        paper2 = await service.create_paper(sample_paper_create)


        assert paper1.id == paper2.id

    @pytest.mark.asyncio
    async def test_get_by_id(self, service, sample_paper_create, test_db):
        """Тест получения статьи по ID."""

        created = await service.create_paper(sample_paper_create)


        retrieved = await service.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "Test Paper"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, service, test_db):
        """Тест получения несуществующей статьи."""
        paper = await service.get_by_id(99999)
        assert paper is None

    @pytest.mark.asyncio
    async def test_get_by_doi(self, service, sample_paper_create, test_db):
        """Тест получения статьи по DOI."""

        created = await service.create_paper(sample_paper_create)


        retrieved = await service.get_by_doi("10.1234/test.2024.001")

        assert retrieved is not None
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_source_id(self, service, sample_paper_create, test_db):
        """Тест получения статьи по source_id."""

        created = await service.create_paper(sample_paper_create)


        retrieved = await service.get_by_source_id("CORE", "123456")

        assert retrieved is not None
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_search_by_title(self, service, sample_paper_create, test_db):
        """Тест поиска по названию."""

        await service.create_paper(sample_paper_create)


        results = await service.search(query="Test Paper")

        assert len(results) >= 1
        assert results[0].title == "Test Paper"

    @pytest.mark.asyncio
    async def test_search_by_keyword(self, service, sample_paper_create, test_db):
        """Тест поиска по ключевому слову."""

        await service.create_paper(sample_paper_create)


        results = await service.search(query="test")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_all(self, service, sample_paper_create, test_db):
        """Тест получения всех статей."""

        await service.create_paper(sample_paper_create)

        sample_paper_create.doi = "10.1234/test.2024.002"
        sample_paper_create.source_id = "123457"
        await service.create_paper(sample_paper_create)


        papers = await service.get_all(limit=10)

        assert len(papers) >= 2

    @pytest.mark.asyncio
    async def test_get_total_count(self, service, sample_paper_create, test_db):
        """Тест получения общего количества."""

        await service.create_paper(sample_paper_create)


        count = await service.get_total_count()

        assert count >= 1

    @pytest.mark.asyncio
    async def test_update_paper(self, service, sample_paper_create, test_db):
        """Тест обновления статьи."""

        created = await service.create_paper(sample_paper_create)


        updated = await service.update_paper(
            created.id,
            title="Updated Title",
            abstract="Updated abstract",
        )

        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.abstract == "Updated abstract"

    @pytest.mark.asyncio
    async def test_update_paper_not_found(self, service, test_db):
        """Тест обновления несуществующей статьи."""
        updated = await service.update_paper(99999, title="Test")
        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_paper(self, service, sample_paper_create, test_db):
        """Тест удаления статьи."""

        created = await service.create_paper(sample_paper_create)


        deleted = await service.delete_paper(created.id)

        assert deleted is True


        retrieved = await service.get_by_id(created.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_paper_not_found(self, service, test_db):
        """Тест удаления несуществующей статьи."""
        deleted = await service.delete_paper(99999)
        assert deleted is False
