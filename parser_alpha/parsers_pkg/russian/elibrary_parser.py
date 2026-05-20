"""
eLibrary.ru Parser

Парсер для обработки результатов поиска из eLibrary.ru (РИНЦ).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shared.schemas.paper import Paper


class ELibraryParser:
    """Парсер для результатов поиска eLibrary.ru."""

    def __init__(self) -> None:
        self.source_name = "eLibrary"

    async def parse_search_results(self, results: list[dict[str, Any]]) -> list[Paper]:
        """Преобразовать сырые результаты поиска в схемы Paper."""
        papers: list[Paper] = []

        for result in results:
            try:
                paper = self._parse_single_result(result)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                print(f"Ошибка парсинга результата eLibrary: {exc}")
                continue

        return papers

    def _parse_single_result(self, result: dict[str, Any]) -> Paper | None:
        """Преобразовать один результат eLibrary в Paper."""
        title = str(result.get("title") or "").strip()
        url = str(result.get("url") or "").strip()
        if not title or not url:
            return None

        authors = result.get("authors") or []
        if not isinstance(authors, list):
            authors = [str(authors)]

        keywords = result.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = [str(keywords)]

        metadata_keywords = [
            str(item).strip()
            for item in [
                result.get("source"),
                result.get("year"),
                f"цитирований: {result.get('citations')}" if result.get("citations") is not None else None,
            ]
            if item
        ]

        return Paper(
            title=title,
            authors=[str(author).strip() for author in authors if str(author).strip()],
            abstract=str(result.get("abstract") or "").strip() or None,
            url=url,
            source=self.source_name,
            publication_date=self._parse_date(result.get("year")),
            doi=str(result.get("doi") or "").strip() or None,
            pdf_url=None,
            keywords=[str(keyword).strip() for keyword in [*keywords, *metadata_keywords] if str(keyword).strip()],
            source_id=str(result.get("elibrary_id") or "").strip() or None,
        )

    def _parse_date(self, year: Any) -> datetime | None:
        """Преобразовать год публикации в datetime."""
        if not year:
            return None

        try:
            year_int = int(str(year).strip())
        except (ValueError, TypeError):
            return None

        if 1900 <= year_int <= datetime.now().year:
            return datetime(year_int, 1, 1)
        return None

    async def parse_article_details(self, details: dict[str, Any]) -> Paper | None:
        """Преобразовать детальную карточку статьи."""
        return self._parse_single_result(details)

    def enrich_paper_with_details(self, paper: Paper, details: dict[str, Any]) -> Paper:
        """Обогатить Paper детальными данными, если они отсутствуют."""
        if not paper.abstract and details.get("abstract"):
            paper.abstract = str(details["abstract"]).strip() or None

        if not paper.keywords and details.get("keywords"):
            raw_keywords = details.get("keywords") or []
            if not isinstance(raw_keywords, list):
                raw_keywords = [str(raw_keywords)]
            paper.keywords = [str(keyword).strip() for keyword in raw_keywords if str(keyword).strip()]

        if not paper.doi and details.get("doi"):
            paper.doi = str(details["doi"]).strip() or None

        if not paper.source_id and details.get("elibrary_id"):
            paper.source_id = str(details["elibrary_id"]).strip() or None

        return paper
