"""Базовый класс для парсеров."""

from abc import ABC, abstractmethod
from typing import Any, Optional
from shared.schemas.paper import Paper


class BaseParser(ABC):
    """Базовый класс для парсеров научных статей."""

    @abstractmethod
    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        """Распарсить результаты поиска в список Paper."""
        pass

    @abstractmethod
    async def parse_full_text(self, text: str, metadata: dict[str, Any]) -> Paper:
        """Распарсить полный текст статьи."""
        pass

    @abstractmethod
    async def extract_keywords(self, paper: Paper) -> list[str]:
        """Извлечь ключевые слова из статьи."""
        pass
