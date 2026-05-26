"""arXiv парсер научных статей."""

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "of", "for", "on", "with",
    "at", "to", "from", "by", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might",
    "this", "that", "these", "those", "it", "its",
    "we", "our", "you", "your", "they", "their",
    "using", "used", "use", "can", "study", "studies",
}


DOMAIN_KEYWORDS = {
    "nickel", "alloy", "alloys", "superalloy", "superalloys",
    "heat-resistant", "corrosion", "oxidation",
    "microstructure", "mechanical", "tensile", "creep",
    "inconel", "hastelloy", "waspaloy", "monel",
    "precipitation", "strengthening", "gamma", "prime",
    "turbine", "blade", "aerospace", "coating",
}


class ArxivParser(BaseParser):
    """Парсер для статей из arXiv."""

    def __init__(self):
        super().__init__(source="arXiv")

    async def parse_search_results(
        self,
        data: list[dict[str, Any]],
    ) -> list[Paper]:
        """Распарсить результаты поиска в список Paper."""
        papers = []

        for item in data:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(self.normalize_paper(paper))
            except Exception as e:
                logger.error(f"Error parsing arXiv article: {e}")
                continue

        logger.info(f"arXiv: распарсено {len(papers)} статей из {len(data)}")
        return papers

    def _parse_article(self, data: dict[str, Any]) -> Paper | None:
        """Распарсить одну статью."""
        try:

            publication_date = None
            if "published_date" in data and data["published_date"]:
                try:
                    pub_date_str = data["published_date"]
                    publication_date = datetime.fromisoformat(str(pub_date_str).replace("Z", "+00:00"))
                except Exception:
                    pass


            keywords = data.get("categories", [])

            return self.normalize_paper(Paper(
                title=data.get("title", "") or "Без названия",
                authors=data.get("authors", []) or [],
                publication_date=publication_date,
                journal="arXiv preprint",
                doi=None,
                abstract=data.get("abstract"),
                full_text=None,
                keywords=keywords,
                source="arXiv",
                source_id=data.get("arxiv_id", ""),
                url=data.get("url"),
                pdf_url=data.get("pdf_url"),
            ))

        except Exception as e:
            logger.error(f"Error parsing article data: {e}")
            return None

    async def parse_full_text(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> Paper:
        """Распарсить полный текст статьи."""
        papers = await self.parse_search_results([metadata])

        if papers:
            papers[0].full_text = text
            return self.normalize_paper(papers[0])

        return self.normalize_paper(Paper(
            title=metadata.get("title", "Без названия"),
            authors=metadata.get("authors", []),
            publication_date=metadata.get("publication_date") or metadata.get("published_date"),
            journal=metadata.get("journal"),
            doi=metadata.get("doi"),
            abstract=metadata.get("abstract"),
            full_text=text,
            keywords=metadata.get("keywords") or metadata.get("categories", []),
            source=metadata.get("source", "arXiv"),
            source_id=metadata.get("source_id") or metadata.get("arxiv_id"),
            url=metadata.get("url"),
            pdf_url=metadata.get("pdf_url"),
        ))

    async def extract_keywords(self, paper: Paper) -> list[str]:
        """Извлечь ключевые слова из статьи."""

        if paper.keywords:
            return paper.keywords


        if paper.abstract:
            return self._extract_keywords_from_abstract(paper.abstract)

        return []

    def _extract_keywords_from_abstract(
        self,
        abstract: str,
        max_keywords: int = 15,
    ) -> list[str]:
        """Извлечь ключевые слова из аннотации."""

        words = re.findall(r'\b[a-zA-Z]{3,}\b', abstract.lower())


        word_freq = {}
        for word in words:
            if word not in STOP_WORDS:
                word_freq[word] = word_freq.get(word, 0) + 1


        domain_keywords_found = {
            word: freq for word, freq in word_freq.items()
            if word in DOMAIN_KEYWORDS
        }


        sorted_domain = sorted(domain_keywords_found.items(), key=lambda x: x[1], reverse=True)
        sorted_other = sorted(
            [(w, f) for w, f in word_freq.items() if w not in DOMAIN_KEYWORDS],
            key=lambda x: x[1], reverse=True
        )


        domain_count = min(len(sorted_domain), max_keywords // 2)
        other_count = max_keywords - domain_count

        result = [word for word, _ in sorted_domain[:domain_count]]
        result += [word for word, _ in sorted_other[:other_count]]

        return result
