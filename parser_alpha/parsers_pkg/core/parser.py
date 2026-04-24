"""CORE parser for scientific papers."""

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


class COREParser(BaseParser):
    """Parser for CORE papers."""

    def __init__(self):
        super().__init__(source="CORE")

    async def parse_search_results(
        self,
        data: list[dict[str, Any]],
    ) -> list[Paper]:
        papers = []

        for item in data:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(self.normalize_paper(paper))
            except Exception as e:
                logger.error(f"Error parsing CORE article: {e}")
                continue

        logger.info(f"CORE: parsed {len(papers)} papers from {len(data)}")
        return papers

    def _parse_article(self, data: dict[str, Any]) -> Paper | None:
        try:
            authors = []
            raw_authors = data.get("authors")
            if isinstance(raw_authors, list):
                for author in raw_authors:
                    if isinstance(author, dict):
                        name = author.get("name")
                        if name:
                            authors.append(str(name))
                    elif author:
                        authors.append(str(author))
            elif isinstance(raw_authors, str):
                authors = [raw_authors]

            publication_date = self._parse_publication_date(data)

            keywords = []
            if isinstance(data.get("topics"), list):
                keywords.extend(str(t) for t in data["topics"] if t)
            if isinstance(data.get("fieldOfStudy"), list):
                keywords.extend(str(t) for t in data["fieldOfStudy"] if t)
            keywords = list(dict.fromkeys(keywords))

            journal = None
            journals = data.get("journals")
            if isinstance(journals, list) and journals:
                first_journal = journals[0]
                if isinstance(first_journal, dict):
                    journal = first_journal.get("title") or first_journal.get("name")
                elif first_journal:
                    journal = str(first_journal)

            if not journal:
                publisher = data.get("publisher")
                if isinstance(publisher, str) and publisher.strip():
                    journal = publisher.strip()

            url = data.get("downloadUrl")
            if not url:
                source_urls = data.get("sourceFulltextUrls")
                if isinstance(source_urls, list) and source_urls:
                    url = source_urls[0]

            if not url:
                links = data.get("links")
                if isinstance(links, list):
                    for link in links:
                        if isinstance(link, dict) and link.get("type") in {"reader", "download"}:
                            url = link.get("url")
                            if url:
                                break

            return Paper(
                title=data.get("title", "") or "Untitled",
                authors=authors,
                publication_date=publication_date,
                journal=journal,
                doi=data.get("doi"),
                abstract=data.get("abstract"),
                full_text=None,
                keywords=keywords,
                source=self.source,
                source_id=str(data.get("id", "")) or None,
                url=url,
            )
        except Exception as e:
            logger.error(f"Error parsing article data: {e}")
            return None

    def _parse_publication_date(self, data: dict[str, Any]) -> datetime | None:
        date_candidates = [
            data.get("publishedDate"),
            data.get("acceptedDate"),
            data.get("depositedDate"),
            data.get("createdDate"),
        ]

        for value in date_candidates:
            if not value:
                continue
            raw = str(value).replace("Z", "")
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                pass

        year_published = data.get("yearPublished")
        if year_published:
            try:
                return datetime(int(year_published), 1, 1)
            except Exception:
                return None

        return None

    async def parse_full_text(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> Paper:
        papers = await self.parse_search_results([metadata])

        if papers:
            papers[0].full_text = self._clean_text(text) or None
            return self.normalize_paper(papers[0])

        return self.normalize_paper(Paper(
            title=metadata.get("title", "Untitled"),
            authors=metadata.get("authors", []),
            publication_date=metadata.get("publication_date"),
            journal=metadata.get("journal"),
            doi=metadata.get("doi"),
            abstract=metadata.get("abstract"),
            full_text=text,
            keywords=metadata.get("keywords", []),
            source=self.source,
            source_id=metadata.get("source_id"),
            url=metadata.get("url"),
        ))

    async def extract_keywords(self, paper: Paper) -> list[str]:
        if paper.keywords:
            return paper.keywords

        if paper.abstract:
            return self._extract_keywords_from_text(paper.abstract)

        return []

    def _extract_keywords_from_text(self, text: str, max_keywords: int = 10) -> list[str]:
        stop_words = {
            "the", "a", "an", "and", "or", "in", "of", "for", "on", "with",
            "и", "в", "на", "с", "для", "или", "а", "но",
        }

        words = re.findall(r"[a-zA-Zа-яА-Я]{3,}", text.lower())

        word_freq: dict[str, int] = {}
        for word in words:
            if word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:max_keywords]]
