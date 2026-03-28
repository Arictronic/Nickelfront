"""Базовый класс для парсеров."""

from abc import ABC, abstractmethod
from typing import Any

from shared.schemas.paper import Paper


class BaseParser(ABC):
    """Базовый класс для парсеров научных статей."""

    def __init__(self, source: str = "unknown"):
        """
        Инициализация парсера.

        Args:
            source: Название источника (CORE, arXiv, etc.)
        """
        self.source = source

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

    def normalize_paper(self, paper: Paper) -> Paper:
        """
        Нормализовать данные статьи.

        Args:
            paper: Статья для нормализации

        Returns:
            Нормализованная статья
        """
        # Очистка заголовка
        if paper.title:
            paper.title = self._clean_text(paper.title)

        # Очистка авторов
        if paper.authors:
            paper.authors = [
                self._clean_text(author)
                for author in paper.authors
                if self._clean_text(author)
            ]

        # Очистка аннотации
        if paper.abstract:
            paper.abstract = self._clean_text(paper.abstract)

        # Очистка ключевых слов
        if paper.keywords:
            paper.keywords = [
                self._clean_text(kw)
                for kw in paper.keywords
                if self._clean_text(kw)
            ]

        # Установить источник
        if not paper.source:
            paper.source = self.source

        return paper

    def _clean_text(self, text: str) -> str:
        """
        Очистить текст.

        Args:
            text: Текст для очистки

        Returns:
            Очищенный текст
        """
        if not text:
            return ""

        # Удалить лишние пробелы
        text = " ".join(text.split())

        # Удалить control characters
        text = "".join(
            char for char in text
            if ord(char) >= 32 or char in '\n\r\t'
        )

        # Исправить распространённые проблемы с кодировкой
        text = text.replace('â€"', "'").replace('â€"', "'")
        text = text.replace('â€"', '"').replace('â€"', '"')
        text = text.replace('â€"', '-').replace('â€"', '-')

        return text.strip()

    def validate_paper(self, paper: Paper) -> tuple[bool, list[str]]:
        """
        Валидировать статью.

        Args:
            paper: Статья для валидации

        Returns:
            (is_valid, errors)
        """
        errors = []

        # Проверка обязательных полей
        if not paper.title:
            errors.append("Missing title")

        if not paper.source:
            errors.append("Missing source")

        # Проверка DOI (если есть)
        if paper.doi:
            import re
            pattern = r'^10\.\d{4,9}/[-._;()/:A-Z0-9]+$'
            if not re.match(pattern, paper.doi, re.IGNORECASE):
                errors.append(f"Invalid DOI format: {paper.doi}")

        return len(errors) == 0, errors
