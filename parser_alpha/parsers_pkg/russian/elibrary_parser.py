"""
eLibrary.ru Parser

Парсер для обработки результатов поиска из eLibrary.ru (РИНЦ).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


class ELibraryParser(BaseParser):
    """Парсер для результатов поиска eLibrary.ru."""

    def __init__(self) -> None:
        super().__init__(source="eLibrary")
        self.source_name = "eLibrary"

    async def parse_search_results(self, results: list[dict[str, Any]]) -> list[Paper]:
        """Преобразовать сырые результаты поиска в схемы Paper."""
        papers: list[Paper] = []

        for result in results:
            try:
                paper = self._parse_single_result(result)
                if paper:
                    papers.append(self.normalize_paper(paper))
            except Exception as exc:
                logger.warning("eLibrary: ошибка парсинга результата: {}", exc)
                self.diagnostics.add(
                    stage="parse",
                    reason="parse_result_failed",
                    severity="warning",
                    details={"error": str(exc)},
                )
                continue

        return papers

    def _parse_single_result(self, result: dict[str, Any]) -> Paper | None:
        """Преобразовать один результат eLibrary в Paper."""
        title = str(result.get("title") or "").strip()
        source_id = str(result.get("elibrary_id") or result.get("source_id") or "").strip() or None
        url = str(result.get("url") or "").strip() or None

        if not title:
            return None
        if not url and source_id:
            url = f"https://www.elibrary.ru/item.asp?id={source_id}"
        if not url:
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
                result.get("source") if result.get("source") != self.source_name else None,
                result.get("journal"),
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
            publication_date=self._parse_date(
                result.get("published_date") or result.get("publication_date") or result.get("year")
            ),
            doi=str(result.get("doi") or "").strip() or None,
            pdf_url=str(result.get("pdf_url") or "").strip() or None,
            keywords=[str(keyword).strip() for keyword in [*keywords, *metadata_keywords] if str(keyword).strip()],
            source_id=source_id,
            journal=str(result.get("journal") or "").strip() or None,
        )

    def _parse_date(self, value: Any) -> datetime | None:
        """Преобразовать дату/год публикации в datetime."""
        if not value:
            return None

        raw = str(value).strip().replace("Z", "+00:00")
        if not raw:
            return None

        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y"):
            try:
                candidate = raw[:10] if fmt == "%Y-%m-%d" else raw
                parsed = datetime.strptime(candidate, fmt)
                if 1900 <= parsed.year <= datetime.now().year + 1:
                    return parsed
            except ValueError:
                continue

        return None

    async def parse_article_details(self, details: dict[str, Any]) -> Paper | None:
        """Преобразовать детальную карточку статьи."""
        paper = self._parse_single_result(details)
        return self.normalize_paper(paper) if paper else None

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

        if not paper.url and paper.source_id:
            paper.url = f"https://www.elibrary.ru/item.asp?id={paper.source_id}"

        if not paper.pdf_url and details.get("pdf_url"):
            paper.pdf_url = str(details["pdf_url"]).strip() or None

        return self.normalize_paper(paper)
