"""Unit тесты для CORE API клиента."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from parser.core.client import COREClient


class TestCOREClient:
    """Тесты для COREClient."""

    @pytest.fixture
    def client(self):
        """Создать клиент."""
        return COREClient()

    @pytest.fixture
    def mock_http_client(self):
        """Создать мок HTTP клиента."""
        client = MagicMock(spec=httpx.AsyncClient)
        return client

    @pytest.mark.asyncio
    async def test_search_basic(self, client, mock_http_client):
        """Тест базового поиска."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"id": 1, "title": "Test Paper"},
                {"id": 2, "title": "Another Paper"},
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            results = await client.search(query="nickel alloys", limit=10)

            assert len(results) == 2
            assert results[0]["id"] == 1
            assert results[1]["id"] == 2
            mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_full_text_filter(self, client, mock_http_client):
        """Тест поиска с фильтром полного текста."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            await client.search(query="test", full_text_only=True)

            # Проверяем, что параметр filter был передан
            call_args = mock_http_client.get.call_args
            assert call_args[1]["params"]["filter"] == "has_full_text:true"

    @pytest.mark.asyncio
    async def test_search_limit_clamped(self, client, mock_http_client):
        """Тест ограничения лимита (макс 100)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            await client.search(query="test", limit=150)

            call_args = mock_http_client.get.call_args
            assert call_args[1]["params"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_search_http_error(self, client, mock_http_client):
        """Тест обработки HTTP ошибки."""
        mock_http_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection error"))

        with patch.object(client, '_get_client', return_value=mock_http_client):
            results = await client.search(query="test")
            assert results == []

    @pytest.mark.asyncio
    async def test_get_article(self, client, mock_http_client):
        """Тест получения статьи по ID."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 123, "title": "Test Article"}
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            article = await client.get_article("123")

            assert article is not None
            assert article["id"] == 123
            mock_http_client.get.assert_called_with("/articles/123")

    @pytest.mark.asyncio
    async def test_get_article_not_found(self, client, mock_http_client):
        """Тест получения несуществующей статьи."""
        mock_http_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404)
        ))

        with patch.object(client, '_get_client', return_value=mock_http_client):
            article = await client.get_article("999")
            assert article is None

    @pytest.mark.asyncio
    async def test_get_full_text_available(self, client, mock_http_client):
        """Тест получения полного текста (доступен)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 123,
            "has_full_text": True,
            "source_fulltext_url": "https://example.com/fulltext",
        }
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            # Патчим get_article для возврата тестовых данных
            with patch.object(client, 'get_article', return_value=mock_response.json()):
                full_text = await client.get_full_text("123")
                assert full_text == "https://example.com/fulltext"

    @pytest.mark.asyncio
    async def test_get_full_text_not_available(self, client, mock_http_client):
        """Тест получения полного текста (недоступен)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 123,
            "has_full_text": False,
        }

        with patch.object(client, 'get_article', return_value=mock_response.json()):
            full_text = await client.get_full_text("123")
            assert full_text is None

    @pytest.mark.asyncio
    async def test_suggest(self, client, mock_http_client):
        """Тест получения подсказок."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "suggestions": ["nickel alloys", "nickel superalloys", "nickel based"]
        }
        mock_response.raise_for_status.return_value = None
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_http_client):
            suggestions = await client.suggest(query="nickel", limit=5)

            assert len(suggestions) == 3
            assert "nickel alloys" in suggestions

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Тест закрытия клиента."""
        # Создаём реальный клиент
        await client._get_client()
        assert client._client is not None

        await client.close()
        assert client._client is None or client._client.is_closed
