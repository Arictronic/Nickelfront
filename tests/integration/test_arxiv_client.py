"""Интеграционные тесты для arXiv API.

Внимание: Эти тесты делают реальные запросы к arXiv API.
"""

import pytest
from parsers_pkg.arxiv.client import ArxivClient


class TestArxivClientIntegration:
    """Интеграционные тесты для arXiv API клиента."""

    @pytest.mark.asyncio
    async def test_real_search(self):
        """Тест реального поиска в arXiv."""
        client = ArxivClient(rate_limit=False)

        try:
            results = await client.search(query="nickel-based alloys", limit=5)
            assert isinstance(results, list)
            if len(results) > 0:
                assert "arxiv_id" in results[0]
                assert "title" in results[0]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_real_search_with_categories(self):
        """Тест поиска с фильтром по категориям."""
        client = ArxivClient(rate_limit=False)

        try:
            results = await client.search(
                query="superalloys",
                limit=5,
                categories=["cond-mat.mtrl-sci"],
            )
            assert isinstance(results, list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_real_get_full_text_url(self):
        """Тест получения URL на PDF."""
        client = ArxivClient(rate_limit=False)

        try:
            results = await client.search(query="nickel alloys", limit=1)
            if len(results) > 0:
                pdf_url = await client.get_full_text(results[0]["arxiv_id"])
                assert pdf_url.startswith("https://arxiv.org/pdf/")
                assert pdf_url.endswith(".pdf")
        finally:
            await client.close()
