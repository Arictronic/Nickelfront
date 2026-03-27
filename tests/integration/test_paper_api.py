"""Интеграционные тесты для API парсинга."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestPaperAPI:
    """Интеграционные тесты для Paper API."""

    @pytest.mark.asyncio
    async def test_get_papers_empty(self, client: AsyncClient):
        """Тест получения пустого списка статей."""
        response = await client.get("/api/v1/papers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_papers_count(self, client: AsyncClient):
        """Тест получения количества статей."""
        response = await client.get("/api/v1/papers/count")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data

    @pytest.mark.asyncio
    async def test_search_papers(self, client: AsyncClient):
        """Тест поиска статей."""
        response = await client.post(
            "/api/v1/papers/search",
            json={"query": "nickel", "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert "papers" in data
        assert "total" in data
        assert "query" in data

    @pytest.mark.asyncio
    async def test_get_paper_not_found(self, client: AsyncClient):
        """Тест получения несуществующей статьи."""
        response = await client.get("/api/v1/papers/id/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_paper_not_found(self, client: AsyncClient):
        """Тест удаления несуществующей статьи."""
        response = await client.delete("/api/v1/papers/id/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_start_parsing(self, client: AsyncClient):
        """Тест запуска парсинга."""
        response = await client.post(
            "/api/v1/papers/parse",
            params={"query": "nickel alloys", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "task_id" in data
        assert data["message"] == "Парсинг запущен"

    @pytest.mark.asyncio
    async def test_start_parsing_all(self, client: AsyncClient):
        """Тест запуска массового парсинга."""
        response = await client.post(
            "/api/v1/papers/parse-all",
            params={"limit_per_query": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "task_id" in data
        assert data["message"] == "Массовый парсинг запущен"

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Тест проверки здоровья API."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestPaperCRUD:
    """Тесты CRUD операций для статей."""

    @pytest.fixture
    def sample_paper_data(self):
        """Пример данных статьи."""
        return {
            "title": "Integration Test Paper",
            "authors": ["Test Author"],
            "publication_date": "2024-01-15T00:00:00",
            "journal": "Test Journal",
            "doi": "10.1234/integration.test",
            "abstract": "Test abstract for integration testing",
            "full_text": "Test full text",
            "keywords": ["test", "integration"],
            "source": "CORE",
            "source_id": "integration_001",
            "url": "https://example.com/test",
        }

    @pytest.mark.asyncio
    async def test_create_and_retrieve_paper(
        self,
        client: AsyncClient,
        sample_paper_data: dict,
        test_db: AsyncSession,
    ):
        """Тест создания и получения статьи."""
        # Сначала добавляем статью напрямую через БД (т.к. нет POST endpoint для создания)
        from app.db.models.paper import Paper
        from datetime import datetime

        paper = Paper(
            title=sample_paper_data["title"],
            authors=sample_paper_data["authors"],
            publication_date=datetime.fromisoformat(sample_paper_data["publication_date"]),
            journal=sample_paper_data["journal"],
            doi=sample_paper_data["doi"],
            abstract=sample_paper_data["abstract"],
            full_text=sample_paper_data["full_text"],
            keywords=sample_paper_data["keywords"],
            source=sample_paper_data["source"],
            source_id=sample_paper_data["source_id"],
            url=sample_paper_data["url"],
        )

        test_db.add(paper)
        await test_db.commit()
        await test_db.refresh(paper)

        # Получаем статью
        response = await client.get(f"/api/v1/papers/id/{paper.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == sample_paper_data["title"]
        assert data["doi"] == sample_paper_data["doi"]

    @pytest.mark.asyncio
    async def test_search_created_paper(
        self,
        client: AsyncClient,
        sample_paper_data: dict,
        test_db: AsyncSession,
    ):
        """Тест поиска созданной статьи."""
        # Добавляем статью
        from app.db.models.paper import Paper
        from datetime import datetime

        paper = Paper(
            title=sample_paper_data["title"],
            authors=sample_paper_data["authors"],
            publication_date=datetime.fromisoformat(sample_paper_data["publication_date"]),
            doi=sample_paper_data["doi"],
            abstract=sample_paper_data["abstract"],
            keywords=sample_paper_data["keywords"],
            source=sample_paper_data["source"],
            source_id=sample_paper_data["source_id"],
        )

        test_db.add(paper)
        await test_db.commit()

        # Ищем статью
        response = await client.post(
            "/api/v1/papers/search",
            json={"query": "Integration Test", "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(p["doi"] == sample_paper_data["doi"] for p in data["papers"])
