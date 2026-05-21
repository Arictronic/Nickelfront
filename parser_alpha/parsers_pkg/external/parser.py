"""Parser for normalized external-source rows."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper


_TEXT_OBJECT_KEYS = (
    "name",
    "fullName",
    "displayName",
    "display_name",
    "authorName",
    "value",
    "text",
    "title",
    "label",
    "term",
    "subject",
    "url",
    "href",
)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in values:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _coerce_string_list(value: Any, *, split_commas: bool = True) -> list[str]:
    """Normalize source rows where list fields may arrive as strings/objects.

    A plain string is one author/keyword value, not an iterable of characters.
    Small objects like {"name": "Alice"} are text payloads, not strings to be
    represented as "{'name': 'Alice'}".
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if not text:
            return []
        # Author names often arrive as already-normalized strings in
        # "Family, Given" form.  Splitting those by comma creates fake authors
        # ("Smith", "John").  Keep comma splitting only for keyword-like fields;
        # semicolon/newline remain safe legacy delimiters for authors.
        delimiter = r"[;,\n]+" if split_commas else r"[;\n]+"
        parts = [part.strip() for part in re.split(delimiter, text) if part.strip()]
        return parts or [text]
    if isinstance(value, dict):
        for key in _TEXT_OBJECT_KEYS:
            if key in value:
                extracted = _coerce_string_list(value.get(key), split_commas=split_commas)
                if extracted:
                    return extracted
        output: list[str] = []
        for item in value.values():
            output.extend(_coerce_string_list(item, split_commas=split_commas))
        return _dedupe_strings(output)
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_coerce_string_list(item, split_commas=split_commas))
        return _dedupe_strings(output)
    text = " ".join(str(value).split()).strip()
    return [text] if text else []


def _first_string(value: Any) -> str | None:
    values = _coerce_string_list(value, split_commas=False)
    return values[0] if values else None




def _coerce_row_list(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, (list, tuple, set)):
        return [item for item in data if isinstance(item, dict)]
    return []

class ExternalParser(BaseParser):
    def __init__(self, source: str):
        super().__init__(source=source)

    async def parse_search_results(self, data: list[dict[str, Any]] | dict[str, Any] | Any) -> list[Paper]:
        rows = _coerce_row_list(data)
        papers: list[Paper] = []
        for item in rows:
            try:
                paper = self._parse_article(item)
                if paper:
                    papers.append(self.normalize_paper(paper))
            except Exception as exc:
                logger.error("{} parser error: {}", self.source, exc)
        logger.info("{}: parsed {} papers from {}", self.source, len(papers), len(rows))
        return papers

    def _parse_article(self, item: dict[str, Any]) -> Paper | None:
        publication_date = None
        published = _first_string(item.get("published_date"))
        if published:
            try:
                publication_date = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except Exception:
                raw_date = str(published).strip()
                for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y"):
                    try:
                        publication_date = datetime.strptime(raw_date[:10] if fmt == "%Y-%m-%d" else raw_date, fmt)
                        break
                    except Exception:
                        continue

        return Paper(
            title=_first_string(item.get("title")) or "Untitled",
            authors=_coerce_string_list(item.get("authors"), split_commas=False),
            publication_date=publication_date,
            journal=_first_string(item.get("journal")),
            doi=_first_string(item.get("doi")),
            abstract=_first_string(item.get("abstract")),
            full_text=None,
            keywords=_coerce_string_list(item.get("keywords"), split_commas=True),
            source=_first_string(item.get("source")) or self.source,
            source_id=_first_string(item.get("source_id")),
            url=_first_string(item.get("url")),
            pdf_url=_first_string(item.get("pdf_url")),
        )

    async def parse_full_text(self, text: str, metadata: dict[str, Any]) -> Paper:
        papers = await self.parse_search_results([metadata])
        if papers:
            papers[0].full_text = text
            return self.normalize_paper(papers[0])

        return self.normalize_paper(Paper(
            title=_first_string(metadata.get("title")) or "Untitled",
            authors=_coerce_string_list(metadata.get("authors"), split_commas=False),
            publication_date=_first_string(metadata.get("publication_date")) or _first_string(metadata.get("published_date")),
            journal=_first_string(metadata.get("journal")),
            doi=_first_string(metadata.get("doi")),
            abstract=_first_string(metadata.get("abstract")),
            full_text=text,
            keywords=_coerce_string_list(metadata.get("keywords"), split_commas=True),
            source=_first_string(metadata.get("source")) or self.source,
            source_id=_first_string(metadata.get("source_id")),
            url=_first_string(metadata.get("url")),
            pdf_url=_first_string(metadata.get("pdf_url")),
        ))

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
