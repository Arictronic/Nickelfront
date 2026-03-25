"""Unit тесты для arXiv API клиента."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from parser.arxiv.client import ArxivClient


class TestArxivClient:
    """Тесты для ArxivClient."""

    @pytest.fixture
    def client(self):
        """Создать клиент."""
        return ArxivClient(rate_limit=False)

    @pytest.fixture
    def sample_xml_response(self):
        """Пример XML ответа от arXiv."""
        return """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2101.12345</id>
    <title>Nickel-based superalloys for high temperature applications</title>
    <published>2024-01-15T10:00:00Z</published>
    <summary>This paper studies nickel-based superalloys.</summary>
    <author><name>John Smith</name></author>
    <author><name>Jane Doe</name></author>
    <category term="cond-mat.mtrl-sci"/>
  </entry>
</feed>"""

    @pytest.mark.asyncio
    async def test_search_basic(self, client, sample_xml_response):
        """Тест базового поиска."""
        mock_response = MagicMock()
        mock_response.text = sample_xml_response
        mock_response.raise_for_status.return_value = None
        
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_client):
            results = await client.search(query="nickel alloys", limit=10)
            assert len(results) == 1
            assert results[0]["title"] == "Nickel-based superalloys for high temperature applications"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, client):
        """Тест поиска без результатов."""
        mock_response = MagicMock()
        mock_response.text = "<?xml version='1.0'?><feed></feed>"
        mock_response.raise_for_status.return_value = None
        
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(client, '_get_client', return_value=mock_client):
            results = await client.search(query="nonexistent")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_http_error(self, client):
        """Тест обработки HTTP ошибки."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Error"))

        with patch.object(client, '_get_client', return_value=mock_client):
            results = await client.search(query="test")
            assert results == []

    @pytest.mark.asyncio
    async def test_get_full_text_url(self, client):
        """Тест получения URL на PDF."""
        url = await client.get_full_text("2101.12345")
        assert url == "https://arxiv.org/pdf/2101.12345.pdf"

    @pytest.mark.asyncio
    async def test_parse_xml_malformed(self, client):
        """Тест обработки невалидного XML."""
        results = client._parse_xml_response("not xml")
        assert results == []

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Тест закрытия клиента."""
        await client._get_client()
        await client.close()
        assert client._client is None or client._client.is_closed
