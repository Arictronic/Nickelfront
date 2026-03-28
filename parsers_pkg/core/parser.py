"""CORE парсер научных статей."""

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


class COREParser(BaseParser):
    """Парсер для статей из CORE."""

    def __init__(self):
        """Инициализация парсера."""
        pass

    async def parse_search_results(
        self,
        data: list[dict[str, Any]],
    ) -> list[Paper]:
        """
        Распарсить результаты поиска в список Paper.

        Args:
            data: Результаты поиска из CORE API

        Returns:
            Список объектов Paper
        """
        papers = []

        for item in data:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.error(f"Error parsing CORE article: {e}")
                continue

        logger.info(f"CORE: распарсено {len(papers)} статей из {len(data)}")
        return papers

    def _parse_article(self, data: dict[str, Any]) -> Paper | None:
        """
        Распарсить одну статью.

        Args:
            data: Данные статьи из CORE API

        Returns:
            Объект Paper или None
        """
        try:
            # Извлекаем авторов
            authors = []
            if "authors" in data:
                if isinstance(data["authors"], list):
                    authors = [
                        str(a.get("name", "")) if isinstance(a, dict) else str(a)
                        for a in data["authors"]
                        if a
                    ]
                elif isinstance(data["authors"], str):
                    authors = [data["authors"]]

            # Извлекаем дату публикации
            publication_date = None
            if "published_date" in data:
                try:
                    pub_date_str = data["published_date"]
                    if pub_date_str:
                        # CORE может возвращать дату в разных форматах
                        for fmt in ["%Y-%m-%d", "%Y-%m", "%Y"]:
                            try:
                                publication_date = datetime.strptime(
                                    str(pub_date_str)[:10], fmt
                                )
                                break
                            except ValueError:
                                continue
                except Exception:
                    pass

            # Извлекаем ключевые слова
            keywords = []
            if "topics" in data and isinstance(data["topics"], list):
                keywords = [str(t) for t in data["topics"] if t]

            # URL статьи
            url = data.get("source_fulltext_url") or data.get("journal_url")

            return Paper(
                title=data.get("title", "") or "Без названия",
                authors=authors,
                publication_date=publication_date,
                journal=data.get("journal", {}).get("name") if isinstance(
                    data.get("journal"), dict
                ) else data.get("journal"),
                doi=data.get("doi"),
                abstract=data.get("abstract"),
                full_text=None,  # Полный текст загружается отдельно
                keywords=keywords,
                source="CORE",
                source_id=str(data.get("id", "")),
                url=url,
            )

        except Exception as e:
            logger.error(f"Error parsing article data: {e}")
            return None

    async def parse_full_text(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> Paper:
        """
        Распарсить полный текст статьи.

        Args:
            text: Полный текст статьи
            metadata: Метаданные статьи

        Returns:
            Объект Paper с полным текстом
        """
        # Базовый парсинг уже выполнен в parse_search_results
        # Здесь можно добавить дополнительную обработку текста
        paper = await self.parse_search_results([metadata])

        if paper and len(paper) > 0:
            paper[0].full_text = text
            return paper[0]

        # Если парсинг не удался, создаём минимальный объект
        return Paper(
            title=metadata.get("title", "Без названия"),
            authors=[],
            full_text=text,
            source="CORE",
        )

    async def extract_keywords(self, paper: Paper) -> list[str]:
        """
        Извлечь ключевые слова из статьи.

        Использует уже существующие keywords из метаданных.
        При необходимости можно добавить ML-модель для извлечения ключевых слов.

        Args:
            paper: Объект статьи

        Returns:
            Список ключевых слов
        """
        # Если keywords уже есть, возвращаем их
        if paper.keywords:
            return paper.keywords

        # Если есть аннотация, можно извлечь ключевые слова из неё
        if paper.abstract:
            keywords = self._extract_keywords_from_text(paper.abstract)
            return keywords

        return []

    def _extract_keywords_from_text(self, text: str, max_keywords: int = 10) -> list[str]:
        """
        Извлечь ключевые слова из текста (простая эвристика).

        Args:
            text: Текст для анализа
            max_keywords: Макс. количество ключевых слов

        Returns:
            Список ключевых слов
        """
        # Простая реализация: извлекаем существительные после предлогов
        # В будущем можно заменить на ML-модель

        # Стоп-слова (русские и английские)
        stop_words = {
            "the", "a", "an", "and", "or", "in", "of", "for", "on", "with",
            "the", "и", "в", "на", "с", "для", "или", "а", "но"
        }

        # Разбиваем текст на слова
        words = re.findall(r'\b[a-zA-Zа-яА-Я]{3,}\b', text.lower())

        # Подсчитываем частоту слов
        word_freq = {}
        for word in words:
            if word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Сортируем по частоте
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

        # Возвращаем топ-N
        return [word for word, _ in sorted_words[:max_keywords]]
