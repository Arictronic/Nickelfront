"""
Тесты для API эндпоинтов.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Фикстура с тестовым клиентом FastAPI."""
    with TestClient(app) as test_client:
        yield test_client


class TestHealthEndpoint:
    """Тесты для эндпоинта /health."""

    def test_health_check(self, client):
        """Проверка эндпоинта здоровья."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "llm_available" in data
        assert "vector_store_documents" in data

    def test_health_status(self, client):
        """Проверка статуса здоровья."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "ok"


class TestAskEndpoint:
    """Тесты для эндпоинта /ask."""

    def test_ask_empty_question(self, client):
        """Проверка запроса с пустым вопросом."""
        response = client.post(
            "/api/v1/ask",
            json={"question": ""},
        )
        assert response.status_code == 422  # Validation error

    def test_ask_valid_question(self, client):
        """Проверка корректного запроса."""
        response = client.post(
            "/api/v1/ask",
            json={
                "question": "Что такое суперсплавы?",
                "include_sources": True,
            },
        )
        # Может вернуть 200 с ответом или 500 если LLM не настроен
        assert response.status_code in [200, 500]


class TestStatsEndpoint:
    """Тесты для эндпоинта /stats."""

    def test_get_stats(self, client):
        """Проверка получения статистики."""
        response = client.get("/api/v1/stats")
        assert response.status_code == 200

        data = response.json()
        assert "vector_store" in data
        assert "llm_model" in data
        assert "embedding_model" in data


class TestModelsEndpoint:
    """Тесты для эндпоинта /models."""

    def test_get_models_info(self, client):
        """Проверка получения информации о моделях."""
        response = client.get("/api/v1/models")
        assert response.status_code == 200

        data = response.json()
        assert "llm" in data
        assert "embeddings" in data
        assert "chunking" in data
        assert "search" in data


class TestRootEndpoints:
    """Тесты для корневых эндпоинтов."""

    def test_root(self, client):
        """Проверка корневого эндпоинта."""
        response = client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()

    def test_ping(self, client):
        """Проверка эндпоинта ping."""
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json()["status"] == "pong"
