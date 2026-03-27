"""
Тесты для аналитики и метрик.

Тестируемые endpoints:
- GET /api/v1/analytics/metrics/summary
- GET /api/v1/analytics/metrics/trend
- GET /api/v1/analytics/metrics/top
- GET /api/v1/analytics/metrics/source-distribution
- GET /api/v1/analytics/metrics/quality-report
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_analytics_summary(client: AsyncClient, test_db: AsyncSession):
    """Тест получения сводной статистики."""
    response = await client.get("/api/v1/analytics/metrics/summary")
    
    assert response.status_code == 200
    data = response.json()
    assert "total_papers" in data
    assert "papers_by_source" in data
    assert "papers_with_embedding" in data
    assert "avg_quality_score" in data


@pytest.mark.asyncio
async def test_analytics_summary_with_source_filter(client: AsyncClient, test_db: AsyncSession):
    """Тест сводной статистики с фильтром по источнику."""
    for source in ["CORE", "arXiv", "all"]:
        response = await client.get(
            "/api/v1/analytics/metrics/summary",
            params={"source": source}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_papers" in data


@pytest.mark.asyncio
async def test_analytics_trend(client: AsyncClient, test_db: AsyncSession):
    """Тест получения тренда публикаций."""
    response = await client.get(
        "/api/v1/analytics/metrics/trend",
        params={"group_by": "month", "limit": 12}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "trend" in data
    assert "group_by" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_analytics_trend_grouping(client: AsyncClient, test_db: AsyncSession):
    """Тест группировки тренда."""
    for group_by in ["day", "week", "month", "year"]:
        response = await client.get(
            "/api/v1/analytics/metrics/trend",
            params={"group_by": group_by, "limit": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["group_by"] == group_by


@pytest.mark.asyncio
async def test_analytics_top_journals(client: AsyncClient, test_db: AsyncSession):
    """Тест получения топ журналов."""
    response = await client.get(
        "/api/v1/analytics/metrics/top",
        params={"item_type": "journals", "limit": 10}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "item_type" in data
    assert "items" in data
    assert data["item_type"] == "journals"


@pytest.mark.asyncio
async def test_analytics_top_authors(client: AsyncClient, test_db: AsyncSession):
    """Тест получения топ авторов."""
    response = await client.get(
        "/api/v1/analytics/metrics/top",
        params={"item_type": "authors", "limit": 10}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["item_type"] == "authors"
    assert "items" in data


@pytest.mark.asyncio
async def test_analytics_top_keywords(client: AsyncClient, test_db: AsyncSession):
    """Тест получения топ ключевых слов."""
    response = await client.get(
        "/api/v1/analytics/metrics/top",
        params={"item_type": "keywords", "limit": 20}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["item_type"] == "keywords"


@pytest.mark.asyncio
async def test_analytics_top_invalid_type(client: AsyncClient, test_db: AsyncSession):
    """Тест получения топ с невалидным типом."""
    response = await client.get(
        "/api/v1/analytics/metrics/top",
        params={"item_type": "invalid", "limit": 10}
    )
    
    assert response.status_code == 400  # Ошибка


@pytest.mark.asyncio
async def test_analytics_source_distribution(client: AsyncClient, test_db: AsyncSession):
    """Тест получения распределения по источникам."""
    response = await client.get("/api/v1/analytics/metrics/source-distribution")
    
    assert response.status_code == 200
    data = response.json()
    assert "distribution" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_analytics_quality_report(client: AsyncClient, test_db: AsyncSession):
    """Тест получения отчёта о качестве."""
    response = await client.get("/api/v1/analytics/metrics/quality-report")
    
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "completeness" in data
    assert "averages" in data
    assert "quality_score" in data


@pytest.mark.asyncio
async def test_analytics_quality_report_with_filter(client: AsyncClient, test_db: AsyncSession):
    """Тест отчёта о качестве с фильтром."""
    for source in ["CORE", "arXiv", None]:
        params = {}
        if source:
            params["source"] = source
            
        response = await client.get(
            "/api/v1/analytics/metrics/quality-report",
            params=params
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data


@pytest.mark.asyncio
async def test_analytics_empty_database(client: AsyncClient, test_db: AsyncSession):
    """Тест аналитики на пустой базе."""
    # Все endpoints должны работать на пустой базе
    endpoints = [
        "/api/v1/analytics/metrics/summary",
        "/api/v1/analytics/metrics/trend",
        "/api/v1/analytics/metrics/top?item_type=journals",
        "/api/v1/analytics/metrics/source-distribution",
        "/api/v1/analytics/metrics/quality-report",
    ]
    
    for endpoint in endpoints:
        response = await client.get(endpoint)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_analytics_trend_limit(client: AsyncClient, test_db: AsyncSession):
    """Тест лимита тренда."""
    response = await client.get(
        "/api/v1/analytics/metrics/trend",
        params={"group_by": "month", "limit": 100}
    )
    
    assert response.status_code == 200
    data = response.json()
    # Лимит должен соблюдаться
    assert len(data["trend"]) <= 100


@pytest.mark.asyncio
async def test_analytics_response_structure(client: AsyncClient, test_db: AsyncSession):
    """Тест структуры ответов analytics endpoints."""
    # Проверяем, что все ответы имеют generated_at
    endpoints = [
        "/api/v1/analytics/metrics/summary",
        "/api/v1/analytics/metrics/trend",
        "/api/v1/analytics/metrics/source-distribution",
        "/api/v1/analytics/metrics/quality-report",
    ]
    
    for endpoint in endpoints:
        response = await client.get(endpoint)
        data = response.json()
        assert "generated_at" in data
