"""Базовый класс для API клиентов."""

from abc import ABC, abstractmethod
from typing import Any

import httpx


class BaseAPIClient(ABC):
    """Базовый класс для API клиентов."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить HTTP клиент."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """Закрыть соединение."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Поиск статей."""
        pass

    @abstractmethod
    async def get_full_text(self, item_id: str) -> str | None:
        """Получить полный текст статьи."""
        pass
