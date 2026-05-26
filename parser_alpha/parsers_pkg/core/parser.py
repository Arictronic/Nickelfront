"""CORE parser for scientific papers."""

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper

def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, dict)]
    return []


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        return [text] if text else []
    if isinstance(value, dict):
        for key in ("name", "title", "url", "downloadUrl", "value", "text", "id", "doi"):
            if value.get(key):
                return _coerce_text_list(value.get(key))
        output: list[str] = []
        for item in value.values():
            output.extend(_coerce_text_list(item))
        return list(dict.fromkeys(output))
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_coerce_text_list(item))
        return list(dict.fromkeys(output))
    text = " ".join(str(value).split()).strip()
    return [text] if text else []


def _first_text(value: Any) -> str | None:
    values = _coerce_text_list(value)
    return values[0] if values else None

def _is_probable_pdf_url(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return lowered.endswith(".pdf") or "/download/" in lowered or "download=pdf" in lowered or "format=pdf" in lowered


def _is_http_url(value: str | None) -> bool:
    return bool(value and value.lower().startswith(("http://", "https://")))


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
            for author in _coerce_dict_list(raw_authors):
                name = _first_text(author.get("name") or author.get("displayName") or author.get("fullName"))
                if name:
                    authors.append(name)
            if not authors:
                authors = _coerce_text_list(raw_authors)

            publication_date = self._parse_publication_date(data)

            keywords = []
            keywords.extend(_coerce_text_list(data.get("topics")))
            keywords.extend(_coerce_text_list(data.get("fieldOfStudy")))
            keywords = list(dict.fromkeys(keywords))

            journal = None
            journals = data.get("journals")
            journal_records = _coerce_dict_list(journals)
            if journal_records:
                journal = _first_text(journal_records[0].get("title") or journal_records[0].get("name"))
            if not journal:
                journal = _first_text(journals)

            if not journal:
                journal = _first_text(data.get("journal"))

            if not journal:
                journal = _first_text(data.get("publisher"))

            pdf_url = _first_text(data.get("downloadUrl"))
            full_text_value = _first_text(data.get("fullText"))
            full_text = None if _is_http_url(full_text_value) else full_text_value

            url = _first_text(data.get("source_fulltext_url"))
            source_urls = _coerce_text_list(data.get("sourceFulltextUrls"))
            if source_urls:
                for source_url in source_urls:
                    if _is_probable_pdf_url(source_url):
                        pdf_url = pdf_url or source_url
                    else:
                        url = url or source_url

            links = _coerce_dict_list(data.get("links"))
            for link in links:
                link_type = str(link.get("type") or "").lower()
                link_url = _first_text(link.get("url"))
                if not link_url:
                    continue
                if link_type == "download" or _is_probable_pdf_url(link_url):
                    pdf_url = pdf_url or link_url
                    continue
                if link_type in {"reader", "fulltext", "full_text"}:
                    url = link_url
                    break

            return Paper(
                title=_first_text(data.get("title")) or "Без названия",
                authors=authors,
                publication_date=publication_date,
                journal=journal,
                doi=_first_text(data.get("doi")),
                abstract=_first_text(data.get("abstract")),
                full_text=full_text,
                keywords=keywords,
                source=self.source,
                source_id=_first_text(data.get("id")),
                url=url,
                pdf_url=pdf_url,
            )
        except Exception as e:
            logger.error(f"Error parsing article data: {e}")
            return None

    def _parse_publication_date(self, data: dict[str, Any]) -> datetime | None:
        date_candidates = [
            data.get("published_date"),
            data.get("publishedDate"),
            data.get("accepted_date"),
            data.get("acceptedDate"),
            data.get("deposited_date"),
            data.get("depositedDate"),
            data.get("created_date"),
            data.get("createdDate"),
        ]

        for value in date_candidates:
            if not value:
                continue
            raw = (_first_text(value) or "").replace("Z", "")
            if not raw:
                continue
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                pass
            try:
                return datetime.strptime(raw[:7], "%Y-%m")
            except ValueError:
                pass
            try:
                return datetime.strptime(raw[:4], "%Y")
            except ValueError:
                pass

        year_published = data.get("yearPublished")
        if year_published:
            try:
                return datetime(int(_first_text(year_published) or year_published), 1, 1)
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
            title=metadata.get("title", "Без названия"),
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
            pdf_url=metadata.get("pdf_url"),
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

        words = re.findall(r"\b[a-zA-Zа-яА-Я]{3,}\b", text.lower())

        word_freq: dict[str, int] = {}
        for word in words:
            if word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:max_keywords]]
