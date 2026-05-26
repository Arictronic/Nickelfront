"""CyberLeninka parser for Russian scientific articles."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


def _coerce_string_list(value: Any, *, split_commas: bool = True) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if not text:
            return []
        pattern = r"[;,]" if split_commas else r"[;\n]+"
        return [part.strip() for part in re.split(pattern, text) if part.strip()] or [text]
    if isinstance(value, dict):
        for key in ("name", "fullName", "displayName", "authorName", "value", "title", "text"):
            if key in value:
                extracted = _coerce_string_list(value.get(key), split_commas=split_commas)
                if extracted:
                    return extracted
        result: list[str] = []
        for item in value.values():
            result.extend(_coerce_string_list(item, split_commas=split_commas))
        return list(dict.fromkeys(result))
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_coerce_string_list(item, split_commas=split_commas))
        seen: set[str] = set()
        deduped: list[str] = []
        for item in result:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped
    text = " ".join(str(value).split()).strip()
    return [text] if text else []


class CyberLeninkaParser(BaseParser):
    """Парсер для статей из CyberLeninka."""

    def __init__(self):
        super().__init__(source="CyberLeninka")

    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        """
        Распарсить результаты поиска в список Paper.

        Args:
            data: Список словарей с метаданными статей

        Returns:
            Список объектов Paper
        """
        papers = []

        for item in data:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(self.normalize_paper(paper))
            except Exception as e:
                logger.error(f"{self.source} parser error: {e}")
                continue

        logger.info(f"{self.source}: parsed {len(papers)} papers from {len(data)}")
        return papers

    def _parse_article(self, item: dict[str, Any]) -> Paper | None:
        """Распарсить одну статью."""
        try:

            publication_date = None
            published = item.get("published_date") or item.get("publication_date")
            if published:
                raw_date = str(published).strip().replace("Z", "+00:00")
                try:
                    publication_date = datetime.fromisoformat(raw_date)
                except Exception:
                    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y"):
                        try:
                            publication_date = datetime.strptime(raw_date[:10] if fmt == "%Y-%m-%d" else raw_date, fmt)
                            break
                        except Exception:
                            continue

            return Paper(
                title=item.get("title") or "Без названия",
                authors=_coerce_string_list(item.get("authors"), split_commas=False),
                publication_date=publication_date,
                journal=item.get("journal"),
                doi=item.get("doi"),
                abstract=item.get("abstract"),
                full_text=None,
                keywords=_coerce_string_list(item.get("keywords")),
                source=self.source,
                source_id=item.get("source_id"),
                url=item.get("url"),
                pdf_url=item.get("pdf_url"),
            )
        except Exception as e:
            logger.error(f"{self.source}: failed to parse article: {e}")
            return None

    async def parse_full_text(self, text: str, metadata: dict[str, Any]) -> Paper:
        """Распарсить полный текст статьи."""
        papers = await self.parse_search_results([metadata])
        if papers:
            papers[0].full_text = text
            return self.normalize_paper(papers[0])

        return self.normalize_paper(Paper(
            title=metadata.get("title") or "Без названия",
            authors=_coerce_string_list(metadata.get("authors"), split_commas=False),
            publication_date=metadata.get("publication_date") or metadata.get("published_date"),
            journal=metadata.get("journal"),
            doi=metadata.get("doi"),
            abstract=metadata.get("abstract"),
            full_text=text,
            keywords=_coerce_string_list(metadata.get("keywords")),
            source=metadata.get("source", self.source),
            source_id=metadata.get("source_id"),
            url=metadata.get("url"),
            pdf_url=metadata.get("pdf_url"),
        ))

    async def extract_keywords(self, paper: Paper) -> list[str]:
        """Извлечь ключевые слова из статьи."""
        if paper.keywords:
            return paper.keywords

        if not paper.abstract:
            return []


        words = re.findall(r"\b[а-яА-Яa-zA-Z]{4,}\b", paper.abstract.lower())


        stop_words = {
            "with", "from", "that", "this", "were", "been", "have", "into",
            "который", "которая", "которые", "является", "были", "было",
            "этот", "этого", "этой", "для", "как", "или", "также",
        }


        freq: dict[str, int] = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1


        return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]]
