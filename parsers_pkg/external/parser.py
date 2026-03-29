"""Parser for normalized external-source rows."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


class ExternalParser(BaseParser):
    def __init__(self, source: str):
        super().__init__(source=source)

    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        papers: list[Paper] = []
        for item in data:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.error("{} parser error: {}", self.source, exc)
        logger.info("{}: parsed {} papers from {}", self.source, len(papers), len(data))
        return papers

    def _parse_article(self, item: dict[str, Any]) -> Paper | None:
        publication_date = None
        published = item.get("published_date")
        if published:
            try:
                publication_date = datetime.fromisoformat(str(published).replace("Z", ""))
            except Exception:
                publication_date = None

        return Paper(
            title=item.get("title") or "Untitled",
            authors=[a for a in (item.get("authors") or []) if a],
            publication_date=publication_date,
            journal=item.get("journal"),
            doi=item.get("doi"),
            abstract=item.get("abstract"),
            full_text=None,
            keywords=[k for k in (item.get("keywords") or []) if k],
            source=item.get("source") or self.source,
            source_id=item.get("source_id"),
            url=item.get("url"),
        )

    async def parse_full_text(self, text: str, metadata: dict[str, Any]) -> Paper:
        papers = await self.parse_search_results([metadata])
        if papers:
            papers[0].full_text = text
            return papers[0]

        return Paper(
            title=metadata.get("title") or "Untitled",
            authors=[],
            full_text=text,
            source=self.source,
        )

    async def extract_keywords(self, paper: Paper) -> list[str]:
        if paper.keywords:
            return paper.keywords
        if not paper.abstract:
            return []

        words = re.findall(r"\b[a-zA-Zа-яА-Я]{4,}\b", paper.abstract.lower())
        stop = {"with", "from", "that", "this", "were", "been", "have", "into", "и", "для", "это", "как"}
        freq: dict[str, int] = {}
        for w in words:
            if w in stop:
                continue
            freq[w] = freq.get(w, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]]
