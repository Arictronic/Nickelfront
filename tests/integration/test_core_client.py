"""Интеграционные тесты для CORE API."""

import pytest
from parser.core.client import COREClient


class TestCOREClientIntegration:
    """Интеграционные тесты для CORE API клиента.

    Внимание: Эти тесты делают реальные запросы к CORE API.
    Для пропуска тестов используйте: pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_real_search(self):
        """Тест реального поиска в CORE."""
        client = COREClient()

        try:
            results = await client.search(
                query="nickel-based alloys",
                limit=5,
            )

            # Проверяем, что получили результаты
            assert isinstance(results, list)
            # CORE обычно возвращает результаты, но может быть пусто
            if len(results) > 0:
                assert "id" in results[0]
                assert "title" in results[0]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_real_search_full_text_only(self):
        """Тест реального поиска с фильтром полного текста."""
        client = COREClient()

        try:
            results = await client.search(
                query="superalloys",
                limit=5,
                full_text_only=True,
            )

            assert isinstance(results, list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_real_suggest(self):
        """Тест реальных подсказок."""
        client = COREClient()

        try:
            suggestions = await client.suggest(query="nickel", limit=5)

            assert isinstance(suggestions, list)
            # Проверяем, что подсказки содержат "nickel"
            if len(suggestions) > 0:
                assert any("nickel" in s.lower() for s in suggestions)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_real_get_article(self):
        """Тест получения реальной статьи."""
        client = COREClient()

        try:
            # Сначала ищем статью
            results = await client.search(query="nickel alloys", limit=1)

            if len(results) > 0:
                article_id = str(results[0]["id"])
                article = await client.get_article(article_id)

                assert article is not None
                assert article["id"] == int(article_id)
        finally:
            await client.close()
