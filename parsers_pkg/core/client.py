"""CORE API клиент.

CORE - агрегатор Open Access научных статей.
API документация: https://core.ac.uk/services/api
"""

from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient


class COREClient(BaseAPIClient):
    """Клиент для CORE API."""

    BASE_URL = "https://core.ac.uk/api-v2"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Инициализация клиента.

        Args:
            api_key: API ключ CORE (необязательно для базового поиска)
            timeout: Таймаут запросов в секундах
        """
        super().__init__(
            base_url=self.BASE_URL,
            api_key=api_key,
            timeout=timeout,
        )
        # CORE требует API ключ только для расширенного доступа
        # Базовый поиск доступен без ключа с лимитами

    async def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        full_text_only: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Поиск статей в CORE.

        Args:
            query: Поисковый запрос
            limit: Макс. количество результатов (1-100)
            offset: Смещение для пагинации
            full_text_only: Только статьи с полным текстом

        Returns:
            Список статей в формате CORE API
        """
        client = await self._get_client()

        params = {
            "q": query,
            "limit": min(limit, 100),
            "offset": offset,
        }

        if full_text_only:
            params["filter"] = "has_full_text:true"

        # Добавляем дополнительные параметры из kwargs
        params.update(kwargs)

        try:
            response = await client.get("/articles/search", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            logger.info(f"CORE: найдено {len(results)} статей по запросу '{query}'")

            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"CORE API error: {e}")
            if e.response is not None:
                logger.error(f"Response: {e.response.text}")

                # Явно сигнализируем о поломке/изменении API CORE,
                # чтобы задача не завершалась "успешно" с нулём результатов.
                if e.response.status_code == 404:
                    raise RuntimeError(
                        "CORE API endpoint недоступен (404). "
                        "Вероятно, API CORE изменился; используйте источник arXiv."
                    ) from e
            return []
        except httpx.HTTPError as e:
            logger.error(f"CORE API error: {e}")
            return []
        except Exception as e:
            logger.error(f"CORE search error: {e}")
            return []

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """
        Получить статью по ID.

        Args:
            article_id: ID статьи в CORE

        Returns:
            Данные статьи или None
        """
        client = await self._get_client()

        try:
            response = await client.get(f"/articles/{article_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"CORE get article error: {e}")
            return None
        except Exception as e:
            logger.error(f"CORE get article error: {e}")
            return None

    async def get_full_text(self, item_id: str) -> str | None:
        """
        Получить полный текст статьи.

        Args:
            item_id: ID статьи в CORE

        Returns:
            Полный текст или None
        """
        # CORE не предоставляет полный текст напрямую через API v2
        # Нужно использовать URL из метаданных статьи
        article = await self.get_article(item_id)

        if article and article.get("has_full_text"):
            # Возвращаем URL для скачивания полного текста
            return article.get("source_fulltext_url") or article.get("full_text")

        return None

    async def suggest(
        self,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        """
        Получить подсказки для поискового запроса.

        Args:
            query: Часть запроса
            limit: Макс. количество подсказок

        Returns:
            Список подсказок
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "/articles/suggest",
                params={"q": query, "limit": limit}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("suggestions", [])
        except Exception as e:
            logger.error(f"CORE suggest error: {e}")
            return []
