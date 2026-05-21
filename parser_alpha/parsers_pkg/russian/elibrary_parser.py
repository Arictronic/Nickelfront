"""
eLibrary.ru Parser

Парсер для обработки результатов поиска из eLibrary.ru (РИНЦ).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser, clean_text, normalize_authors, normalize_datetime, normalize_doi
from shared.schemas.paper import Paper


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _coerce_keywords(value: Any) -> list[str]:
    import json
    import re

    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("name", "value", "text", "title", "label", "term", "subject"):
            if key in value:
                extracted = _coerce_keywords(value.get(key))
                if extracted:
                    return extracted
        output: list[str] = []
        for item in value.values():
            output.extend(_coerce_keywords(item))
        return _dedupe_strings(output)
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_coerce_keywords(item))
        return _dedupe_strings(output)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list, tuple, set)):
                return _coerce_keywords(parsed)
        except Exception:
            pass
        return _dedupe_strings([part for part in re.split(r"[;,\n]+", text) if part.strip()])
    text = clean_text(value)
    return [text] if text else []


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
        title = clean_text(result.get("title"))
        source_id = clean_text(result.get("elibrary_id") or result.get("source_id"))
        url = clean_text(result.get("url"))

        if not title:
            return None
        if not url and source_id:
            url = f"https://www.elibrary.ru/item.asp?id={source_id}"
        if not url:
            return None

        authors = normalize_authors(result.get("authors"))
        keywords = _coerce_keywords(result.get("keywords"))

        metadata_keywords = _coerce_keywords([
            result.get("source") if clean_text(result.get("source")) != self.source_name else None,
            result.get("journal"),
            result.get("year"),
            f"цитирований: {result.get('citations')}" if result.get("citations") is not None else None,
        ])

        return Paper(
            title=title,
            authors=authors,
            abstract=clean_text(result.get("abstract")),
            url=url,
            source=self.source_name,
            publication_date=self._parse_date(
                result.get("published_date") or result.get("publication_date") or result.get("year")
            ),
            doi=normalize_doi(result.get("doi")) or clean_text(result.get("doi")),
            pdf_url=clean_text(result.get("pdf_url")),
            keywords=_dedupe_strings([*keywords, *metadata_keywords]),
            source_id=source_id,
            journal=clean_text(result.get("journal")),
        )

    def _parse_date(self, value: Any) -> datetime | None:
        """Преобразовать дату/год публикации в datetime."""
        parsed = normalize_datetime(value)
        if parsed is None:
            return None
        if 1900 <= parsed.year <= datetime.now().year + 1:
            return parsed.replace(tzinfo=None)
        return None

    async def parse_article_details(self, details: dict[str, Any]) -> Paper | None:
        """Преобразовать детальную карточку статьи."""
        paper = self._parse_single_result(details)
        return self.normalize_paper(paper) if paper else None

    def enrich_paper_with_details(self, paper: Paper, details: dict[str, Any]) -> Paper:
        """Обогатить Paper детальными данными, если они отсутствуют."""
        abstract = clean_text(details.get("abstract"))
        if not paper.abstract and abstract:
            paper.abstract = abstract

        if not paper.keywords and details.get("keywords"):
            paper.keywords = _coerce_keywords(details.get("keywords"))

        doi = normalize_doi(details.get("doi")) or clean_text(details.get("doi"))
        if not paper.doi and doi:
            paper.doi = doi

        source_id = clean_text(details.get("elibrary_id") or details.get("source_id"))
        if not paper.source_id and source_id:
            paper.source_id = source_id

        if not paper.url and paper.source_id:
            paper.url = f"https://www.elibrary.ru/item.asp?id={paper.source_id}"

        pdf_url = clean_text(details.get("pdf_url"))
        if not paper.pdf_url and pdf_url:
            paper.pdf_url = pdf_url

        return self.normalize_paper(paper)
