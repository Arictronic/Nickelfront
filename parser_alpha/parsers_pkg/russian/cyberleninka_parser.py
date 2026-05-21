"""CyberLeninka parser for Russian scientific articles."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


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
            # Дата публикации
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
                authors=[a for a in (item.get("authors") or []) if a],
                publication_date=publication_date,
                journal=item.get("journal"),
                doi=item.get("doi"),
                abstract=item.get("abstract"),
                full_text=None,
                keywords=[k for k in (item.get("keywords") or []) if k],
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
            authors=metadata.get("authors", []),
            publication_date=metadata.get("publication_date") or metadata.get("published_date"),
            journal=metadata.get("journal"),
            doi=metadata.get("doi"),
            abstract=metadata.get("abstract"),
            full_text=text,
            keywords=metadata.get("keywords", []),
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
        
        # Извлечение ключевых слов из аннотации
        words = re.findall(r"\b[а-яА-Яa-zA-Z]{4,}\b", paper.abstract.lower())
        
        # Стоп-слова (русские и английские)
        stop_words = {
            "with", "from", "that", "this", "were", "been", "have", "into",
            "который", "которая", "которые", "является", "были", "было",
            "этот", "этого", "этой", "для", "как", "или", "также",
        }
        
        # Подсчет частоты
        freq: dict[str, int] = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        
        # Возврат топ-10 слов
        return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]]