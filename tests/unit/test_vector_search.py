"""
Тесты для векторного поиска.

Тестируемые endpoints:
- POST /api/v1/vector/search
- GET /api/v1/vector/stats
- POST /api/v1/vector/rebuild
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_vector_search_basic(client: AsyncClient, test_db: AsyncSession):
    """Тест базового векторного поиска."""
    search_data = {
        "query": "nickel-based superalloys",
        "limit": 10,
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    
    # Векторный поиск должен работать даже без эмбеддингов (fallback)
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    assert "search_type" in data


@pytest.mark.asyncio
async def test_vector_search_with_filters(client: AsyncClient, test_db: AsyncSession):
    """Тест векторного поиска с фильтрами."""
    search_data = {
        "query": "nickel alloys",
        "limit": 20,
        "source": "CORE",
        "date_from": "2020-01-01",
        "date_to": "2024-12-31",
        "search_type": "hybrid",
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert data["search_type"] in ["vector", "semantic", "hybrid", "text_fallback"]


@pytest.mark.asyncio
async def test_vector_search_different_types(client: AsyncClient, test_db: AsyncSession):
    """Тест различных типов поиска."""
    search_types = ["vector", "semantic", "hybrid", "text"]
    
    for search_type in search_types:
        search_data = {
            "query": "high temperature materials",
            "limit": 5,
            "search_type": search_type,
        }
        
        response = await client.post("/api/v1/vector/search", json=search_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "results" in data
        assert "total" in data


@pytest.mark.asyncio
async def test_vector_search_empty_query(client: AsyncClient, test_db: AsyncSession):
    """Тест поиска с пустым запросом."""
    search_data = {
        "query": "",
        "limit": 10,
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    
    # Пустой запрос должен возвращать ошибку или пустые результаты
    assert response.status_code in [200, 400]


@pytest.mark.asyncio
async def test_vector_search_limit_validation(client: AsyncClient, test_db: AsyncSession):
    """Тест валидации лимита поиска."""
    # Слишком большой лимит
    search_data = {
        "query": "test",
        "limit": 1001,  # Больше максимума
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    assert response.status_code == 422  # Ошибка валидации
    
    # Отрицательный лимит
    search_data = {
        "query": "test",
        "limit": -1,
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_vector_stats(client: AsyncClient, test_db: AsyncSession):
    """Тест получения статистики векторного поиска."""
    response = await client.get("/api/v1/vector/stats")
    
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "available" in data


@pytest.mark.asyncio
async def test_vector_rebuild(client: AsyncClient, test_db: AsyncSession):
    """Тест перестройки векторного индекса."""
    response = await client.post("/api/v1/vector/rebuild")
    
    # Перестройка должна работать даже без статей
    assert response.status_code == 200
    data = response.json()
    assert "message" in data


@pytest.mark.asyncio
async def test_vector_search_similarity_scores(client: AsyncClient, test_db: AsyncSession):
    """Тест проверки scores сходства в результатах."""
    search_data = {
        "query": "nickel superalloys",
        "limit": 10,
        "search_type": "vector",
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    
    if response.status_code == 200:
        data = response.json()
        if data["total"] > 0:
            # Проверяем, что результаты имеют scores
            for result in data["results"]:
                assert "similarity" in result or "score" in result


@pytest.mark.asyncio
async def test_vector_search_source_filter(client: AsyncClient, test_db: AsyncSession):
    """Тест фильтрации по источнику."""
    for source in ["CORE", "arXiv"]:
        search_data = {
            "query": "materials science",
            "limit": 10,
            "source": source,
        }
        
        response = await client.post("/api/v1/vector/search", json=search_data)
        assert response.status_code == 200
        
        data = response.json()
        # Все результаты должны быть из указанного источника
        for result in data.get("results", []):
            paper_source = result.get("paper", {}).get("source", "")
            assert paper_source == source or data["search_type"] == "text_fallback"


@pytest.mark.asyncio
async def test_vector_search_date_filter(client: AsyncClient, test_db: AsyncSession):
    """Тест фильтрации по датам."""
    search_data = {
        "query": "alloys",
        "limit": 20,
        "date_from": "2023-01-01",
        "date_to": "2023-12-31",
    }
    
    response = await client.post("/api/v1/vector/search", json=search_data)
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что результаты соответствуют диапазону дат
    for result in data.get("results", []):
        pub_date = result.get("paper", {}).get("publication_date", "")
        if pub_date:
            assert "2023" in pub_date
