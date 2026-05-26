"""External source clients (OpenAlex, Crossref, Europe PMC)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from parsers_pkg.base import BaseAPIClient, RetryConfig, decide_for_exception, decide_for_status, normalize_doi
from parsers_pkg.errors import ParsingError, SourceUnavailableError


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).replace("Z", "")


def _strip_jats(text: Any) -> str | None:
    """Strip simple JATS/HTML markup from abstract-like API fields.

    Crossref normally returns ``abstract`` as a string, but malformed rows or
    fixtures can contain lists/objects.  Calling ``re.sub`` directly on those
    shapes raises TypeError and drops the whole record, so unwrap common text
    keys first and only stringify scalar fallbacks.
    """
    if text is None:
        return None
    if isinstance(text, (list, tuple, set)):
        for item in text:
            cleaned = _strip_jats(item)
            if cleaned:
                return cleaned
        return None
    if isinstance(text, dict):
        for key in ("abstract", "abstractText", "value", "text", "content"):
            cleaned = _strip_jats(text.get(key))
            if cleaned:
                return cleaned
        return None

    raw = " ".join(str(text).split()).strip()
    if not raw:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(cleaned.split()).strip() or None


def _date_parts_to_iso(parts: list[int] | None) -> str | None:
    if not parts:
        return None
    year = parts[0] if len(parts) >= 1 else 0
    month = parts[1] if len(parts) >= 2 else 1
    day = parts[2] if len(parts) >= 3 else 1
    try:
        year = int(year)
        month = int(month)
        day = int(day)
    except Exception:
        return None
    if year <= 0:
        return None
    if not 1 <= month <= 12:
        month = 1
    if day <= 0:
        day = 1
    try:
        return datetime(year, month, day).isoformat()
    except Exception:


        try:
            return datetime(year, month, 1).isoformat()
        except Exception:
            return None


def _collapse_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def _parse_dot_date(value: Any) -> str | None:
    if not value:
        return None
    raw = _first_text(value)
    if not raw:
        return None
    for fmt in (
        "%Y.%m.%d",
        "%Y.%m",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y",
    ):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except Exception:
            continue
    return None




def _first_text(value: Any, default: str | None = None) -> str | None:
    """Return the first non-empty text from scalar/list/object API fields.

    Crossref/OpenAlex-like APIs usually return fields such as ``title`` and
    ``container-title`` as lists, but source drift or mocked/manual rows may
    send a plain string or a small object like ``{"value": "..."}``.
    Indexing a string with ``[0]`` silently corrupts data into a single
    character, while ``str(dict)`` pollutes records with Python reprs, so keep
    this helper strict and explicit.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return _collapse_whitespace(value) or default
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = _first_text(item, default=None)
            if text:
                return text
        return default
    if isinstance(value, dict):
        for key in (
            "value",
            "text",
            "content",
            "title",
            "name",
            "display_name",
            "displayName",
            "fullName",
            "authorName",
            "url",
            "URL",
            "href",
            "id",
            "doi",
        ):
            if key in value:
                text = _first_text(value.get(key), default=None)
                if text:
                    return text
        for item in value.values():
            text = _first_text(item, default=None)
            if text:
                return text
        return default
    text = _collapse_whitespace(str(value))
    return text or default


def _safe_date_parts(value: Any) -> list[int] | None:
    """Normalize Crossref ``date-parts`` to [year, month, day]."""
    if value is None:
        return None
    candidate = value
    if isinstance(candidate, list) and candidate and isinstance(candidate[0], list):
        candidate = candidate[0]
    if not isinstance(candidate, (list, tuple)):
        candidate = [candidate]

    parts: list[int] = []
    for item in candidate[:3]:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        parts.append(number)
    return parts or None


def _parse_loose_date(value: Any) -> str | None:
    """Parse source date strings beyond strict ISO, preserving at least the year.

    EuropePMC commonly returns values such as ``2024 Apr 10`` or ``2024 Apr``;
    Crossref can expose date-time fields when ``date-parts`` are absent.  Passing
    those strings through unchanged makes the later Pydantic/backend date parser
    drop them, so normalize known public-API date shapes here.
    """
    raw = _first_text(value)
    if not raw:
        return None
    raw = raw.strip().replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(raw).isoformat()
    except Exception:
        pass

    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y %b %d",
        "%Y %B %d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%Y %b",
        "%Y %B",
        "%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except Exception:
            continue


    match = re.search(r"\b(18|19|20)\d{2}\b", raw)
    if match:
        try:
            return datetime(int(match.group(0)), 1, 1).isoformat()
        except Exception:
            return None
    return None


def _extract_crossref_publication_date(item: dict[str, Any]) -> str | None:
    """Return the best Crossref publication date from common date blocks."""
    for key in (
        "issued",
        "published-print",
        "published-online",
        "published",
        "posted",
        "accepted",
        "created",
        "deposited",
    ):
        value = item.get(key)
        block = _as_dict(value)
        date_parts = _safe_date_parts(block.get("date-parts") if block else value)
        parsed = _date_parts_to_iso(date_parts)
        if parsed:
            return parsed
        if block:
            parsed = _parse_loose_date(block.get("date-time") or block.get("date"))
            if parsed:
                return parsed
        parsed = _parse_loose_date(value)
        if parsed:
            return parsed
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a dict only when an API field is actually an object."""
    return value if isinstance(value, dict) else {}


def _extract_indexed_datetime(value: Any) -> str | None:
    indexed = _as_dict(value)
    return _collapse_whitespace(indexed.get("date-time"))


def _europepmc_result_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    result_list = _as_dict(data.get("resultList"))
    raw_results = result_list.get("result", [])
    if isinstance(raw_results, dict):
        raw_results = [raw_results]
    if not isinstance(raw_results, list):
        return []
    return [item for item in raw_results if isinstance(item, dict)]


def _split_author_string(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _collapse_whitespace(value)
        if not text:
            return []



        delimiter = r"[;\n]+" if re.search(r"[;\n]", text) else r","
        return [part.strip() for part in re.split(delimiter, text) if part.strip()] or [text]
    if isinstance(value, (list, tuple, set)):
        authors: list[str] = []
        for item in value:
            authors.extend(_split_author_string(item))
        return list(dict.fromkeys(authors))
    if isinstance(value, dict):
        direct = _coerce_text_list(value.get("fullName") or value.get("name") or value.get("authorName"))
        if direct:
            return direct
        authors: list[str] = []
        for item in value.values():
            authors.extend(_split_author_string(item))
        return list(dict.fromkeys(authors))
    text = _collapse_whitespace(str(value))
    return [text] if text else []

def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    """Return dict records from API fields that may be one object or a list."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, dict)]
    return []


def _coerce_text_list(value: Any) -> list[str]:
    """Normalize API text/list fields without iterating over string characters.

    Some APIs drift between strings, lists and small objects such as
    {"name": "Metallurgy"}.  Returning str(dict) pollutes keywords/authors
    with Python reprs, so prefer common semantic keys and only recurse through
    nested values as a fallback.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = _collapse_whitespace(value)
        return [text] if text else []
    if isinstance(value, dict):
        for key in (
            "name",
            "display_name",
            "displayName",
            "title",
            "label",
            "value",
            "subject",
            "term",
            "fullName",
            "authorName",
        ):
            if key in value:
                extracted = _coerce_text_list(value.get(key))
                if extracted:
                    return extracted
        output: list[str] = []
        for item in value.values():
            output.extend(_coerce_text_list(item))
        return list(dict.fromkeys(output))
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_coerce_text_list(item))
        return list(dict.fromkeys(output))
    text = _collapse_whitespace(str(value))
    return [text] if text else []


def _extract_crossref_authors(value: Any) -> list[str]:
    """Extract author names from Crossref rows with list/dict/string variants."""
    authors: list[str] = []
    for author in _coerce_dict_list(value):



        name = _first_text(author.get("name") or author.get("organization"))
        given = _first_text(author.get("given"))
        family = _first_text(author.get("family"))
        full = name or " ".join(part for part in [given, family] if part).strip()
        if full:
            authors.append(full)
    if not authors:
        authors.extend(_coerce_text_list(value))
    return list(dict.fromkeys(authors))


def _is_pdf_like_url(url: str | None, *, content_type: str | None = None) -> bool:
    text = _collapse_whitespace(url)
    if not text:
        return False
    parsed = urlparse(text)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    ctype = (content_type or "").lower()
    return (
        path.endswith(".pdf")
        or "/pdf" in path
        or "pdf" in ctype
        or "download=pdf" in query
        or "format=pdf" in query
        or "pdf=render" in query
    )


def _extract_crossref_pdf_url(item: dict[str, Any]) -> str | None:
    """Return the first real PDF/full-text link from Crossref's ``link`` field."""
    for link in _coerce_dict_list(item.get("link")):
        url = _first_text(link.get("URL") or link.get("url"))
        if url and _is_pdf_like_url(url, content_type=str(link.get("content-type") or "")):
            return url
    return None


def _openalex_location_dicts(item: dict[str, Any]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for key in ("primary_location", "best_oa_location"):
        locations.extend(_coerce_dict_list(item.get(key)))
    locations.extend(_coerce_dict_list(item.get("locations")))
    return locations


def _first_openalex_pdf_url(item: dict[str, Any]) -> str | None:
    for location in _openalex_location_dicts(item):
        pdf_url = _first_text(location.get("pdf_url"))
        if pdf_url:
            return pdf_url
    open_access = item.get("open_access") if isinstance(item.get("open_access"), dict) else {}
    oa_url = _first_text(open_access.get("oa_url"))
    if oa_url and _is_pdf_like_url(oa_url):
        return oa_url
    return None


def _first_openalex_landing_url(item: dict[str, Any]) -> str | None:
    for location in _openalex_location_dicts(item):
        landing = _first_text(location.get("landing_page_url"))
        if landing:
            return landing
    open_access = item.get("open_access") if isinstance(item.get("open_access"), dict) else {}
    oa_url = _first_text(open_access.get("oa_url"))
    return None if _is_pdf_like_url(oa_url) else oa_url


def _first_openalex_source_name(item: dict[str, Any]) -> str | None:
    for location in _openalex_location_dicts(item):
        source_raw = location.get("source")
        if isinstance(source_raw, dict):
            name = _first_text(source_raw.get("display_name") or source_raw.get("displayName") or source_raw.get("name"))
        else:
            name = _first_text(source_raw)
        if name:
            return name
    return None


def _openalex_work_id(value: Any) -> str | None:
    """Extract a stable OpenAlex work id from string/int/object API variants."""
    text = _first_text(value)
    if not text:
        return None
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or None


def _coerce_int_positions(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        output: list[int] = []
        for item in value:
            output.extend(_coerce_int_positions(item))
        return output
    try:
        pos = int(value)
    except (TypeError, ValueError):
        return []
    return [pos] if pos >= 0 else []


def _extract_rospatent_media_path(value: Any) -> str | None:
    """Return the first usable Rospatent media-list path from API drift shapes."""
    if value is None:
        return None
    if isinstance(value, str):
        return _collapse_whitespace(value)
    if isinstance(value, (int, float)):
        return _collapse_whitespace(str(value))
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidate = _extract_rospatent_media_path(item)
            if candidate:
                return candidate
        return None
    if isinstance(value, dict):
        for key in ("url", "href", "path", "media_path", "mediaPath", "ex_media_list"):
            candidate = _extract_rospatent_media_path(value.get(key))
            if candidate:
                return candidate
        for item in value.values():
            candidate = _extract_rospatent_media_path(item)
            if candidate:
                return candidate
    return None


def _coerce_europepmc_fulltext_links(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and "fullTextUrl" in value:
        value = value.get("fullTextUrl")
    return _coerce_dict_list(value)


def _count_cyrillic_chars(value: str) -> int:
    return sum(1 for ch in value if "\u0400" <= ch <= "\u04FF")


def _repair_mojibake_ru(value: str | None) -> str | None:
    """
    Recover text that looks like UTF-8 interpreted as CP1251
    (typical pattern: 'РЎРїР»Р°РІ ...').
    """
    raw = _collapse_whitespace(value)
    if not raw:
        return None


    suspect = sum(raw.count(marker) for marker in ("Р", "С", "Ð", "Ñ"))
    if suspect < 4:
        return raw

    try:
        repaired = raw.encode("cp1251", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return raw

    if _count_cyrillic_chars(repaired) >= _count_cyrillic_chars(raw):
        return repaired
    return raw


class _RetryingClient(BaseAPIClient):
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.5
    SOURCE_NAME = "External"

    def __init__(self, base_url: str, timeout: float = 30.0):
        super().__init__(base_url=base_url, timeout=timeout)
        self._retry_config = RetryConfig(
            max_retries=self.MAX_RETRIES,
            base_delay=self.RETRY_BASE_DELAY,
            backoff_base=2.0,
            jitter_max=0.0,
        )

    async def _request_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(path, params=params, headers=request_headers)
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source=self.SOURCE_NAME,
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        logger.warning(
                            "{} transient status {} (attempt {}/{}), retry in {:.1f}s",
                            self.SOURCE_NAME,
                            response.status_code,
                            attempt,
                            self.MAX_RETRIES,
                            decision.delay_seconds,
                        )
                        await asyncio.sleep(decision.delay_seconds)
                        continue
                    if decision.error is not None:
                        raise decision.error
                    response.raise_for_status()

                payload = response.json()
                if not isinstance(payload, dict):
                    raise ParsingError(
                        source=self.SOURCE_NAME,
                        message=f"Unexpected payload type: {type(payload).__name__}",
                    )
                return payload

            except ParsingError:
                raise

            except Exception as exc:
                decision = decide_for_exception(
                    source=self.SOURCE_NAME,
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source=self.SOURCE_NAME, message=f"Request failure: {exc}") from exc

        raise SourceUnavailableError(source=self.SOURCE_NAME, message="Request failed without a response")

    async def _request_json_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.post(path, json=payload, headers=request_headers)
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source=self.SOURCE_NAME,
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        await asyncio.sleep(decision.delay_seconds)
                        continue
                    if decision.error is not None:
                        raise decision.error
                    response.raise_for_status()

                payload_obj = response.json()
                if not isinstance(payload_obj, dict):
                    raise ParsingError(
                        source=self.SOURCE_NAME,
                        message=f"Unexpected payload type: {type(payload_obj).__name__}",
                    )
                return payload_obj
            except ParsingError:
                raise
            except Exception as exc:
                decision = decide_for_exception(
                    source=self.SOURCE_NAME,
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source=self.SOURCE_NAME, message=f"Request failure: {exc}") from exc

        raise SourceUnavailableError(source=self.SOURCE_NAME, message="POST request failed without a response")

    async def _request_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        client = await self._get_client()
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(path, params=params or {}, headers=request_headers)
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source=self.SOURCE_NAME,
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        await asyncio.sleep(decision.delay_seconds)
                        continue
                    if decision.error is not None:
                        raise decision.error
                    response.raise_for_status()

                return response.text
            except Exception as exc:
                decision = decide_for_exception(
                    source=self.SOURCE_NAME,
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source=self.SOURCE_NAME, message=f"Request failure: {exc}") from exc

        raise SourceUnavailableError(source=self.SOURCE_NAME, message="Text request failed without a response")


class OpenAlexClient(_RetryingClient):
    BASE_URL = "https://api.openalex.org"
    SOURCE_NAME = "OpenAlex"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(1, (offset // max(1, limit)) + 1)
        data = await self._request_json(
            "/works",
            {"search": query, "per-page": min(limit, 50), "page": page},
        )

        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

        results: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            authors = []
            for authorship in _coerce_dict_list(item.get("authorships")):
                author_obj = authorship.get("author")
                author = author_obj if isinstance(author_obj, dict) else {}
                name = _first_text(
                    author.get("display_name")
                    or author.get("displayName")
                    or authorship.get("author_display_name")
                    or authorship.get("raw_author_name")
                )
                if name:
                    authors.append(name)
            authors = list(dict.fromkeys(authors))

            concepts = []
            for concept in _coerce_dict_list(item.get("concepts"))[:8]:
                name = _first_text(concept.get("display_name") or concept.get("displayName") or concept.get("name"))
                if name:
                    concepts.append(name)
            concepts = list(dict.fromkeys(concepts))

            doi = normalize_doi(item.get("doi") or item.get("DOI"))
            pdf_url = _first_openalex_pdf_url(item)
            landing = _first_openalex_landing_url(item)
            work_id = _openalex_work_id(item.get("id"))
            source_name = _first_openalex_source_name(item)
            fallback_work_url = f"https://openalex.org/{work_id}" if work_id else None
            article_url = landing or (f"https://doi.org/{doi}" if doi else None) or fallback_work_url


            abstract = None
            abstract_inverted = item.get("abstract_inverted_index")
            if abstract_inverted and isinstance(abstract_inverted, dict):
                abstract = self._reconstruct_abstract(abstract_inverted)

            results.append(
                {
                    "title": _first_text(item.get("display_name"), default="Untitled") or "Untitled",
                    "authors": authors,
                    "published_date": _parse_iso_date(_first_text(item.get("publication_date") or item.get("publication_year"))),
                    "journal": source_name,
                    "doi": doi,
                    "abstract": abstract,
                    "keywords": concepts,
                    "source": "OpenAlex",
                    "source_id": work_id,
                    "url": article_url,
                    "pdf_url": pdf_url,
                }
            )

        return results

    def _reconstruct_abstract(self, inverted_index: dict[str, Any]) -> str | None:
        """Reconstruct abstract text from OpenAlex inverted index format."""
        try:
            positions_by_word: list[tuple[str, list[int]]] = []
            max_pos = -1
            for raw_word, raw_positions in inverted_index.items():
                word = _collapse_whitespace(str(raw_word))
                positions = _coerce_int_positions(raw_positions)
                if not word or not positions:
                    continue
                positions_by_word.append((word, positions))
                max_pos = max(max_pos, max(positions))

            if max_pos < 0:
                return None

            words = [""] * (max_pos + 1)
            for word, positions in positions_by_word:
                for pos in positions:
                    if 0 <= pos <= max_pos:
                        words[pos] = word

            abstract = " ".join(w for w in words if w).strip()
            return abstract if abstract else None
        except Exception:
            return None

    async def get_full_text(self, item_id: str) -> str | None:
        work_id = _openalex_work_id(item_id)
        if not work_id:
            return None
        data = await self._request_json(f"/works/{work_id}", {})
        if not isinstance(data, dict):
            return None
        return _first_openalex_pdf_url(data) or _first_openalex_landing_url(data)


class CrossrefClient(_RetryingClient):
    BASE_URL = "https://api.crossref.org"
    SOURCE_NAME = "Crossref"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        data = await self._request_json(
            "/works",
            {"query": query, "rows": min(limit, 50), "offset": max(offset, 0)},
        )

        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        items = message.get("items", [])
        if not isinstance(items, list):
            items = []
        results: list[dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            authors = _extract_crossref_authors(item.get("author"))

            publication_date = _extract_crossref_publication_date(item)

            results.append(
                {
                    "title": _first_text(item.get("title") or item.get("short-title"), default="Untitled") or "Untitled",
                    "authors": authors,
                    "published_date": publication_date,
                    "journal": _first_text(item.get("container-title")),
                    "doi": normalize_doi(item.get("DOI") or item.get("doi")),
                    "abstract": _strip_jats(item.get("abstract")),
                    "keywords": _coerce_text_list(item.get("subject")),
                    "source": "Crossref",
                    "source_id": normalize_doi(item.get("DOI") or item.get("doi")) or _extract_indexed_datetime(item.get("indexed")),
                    "url": _first_text(item.get("URL") or item.get("url")),
                    "pdf_url": _extract_crossref_pdf_url(item),
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        doi = normalize_doi(item_id)
        return f"https://doi.org/{doi}" if doi else None


class EuropePMCClient(_RetryingClient):
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    SOURCE_NAME = "EuropePMC"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(1, (offset // max(1, limit)) + 1)
        data = await self._request_json(
            "/search",
            {
                "query": query,
                "format": "json",
                "pageSize": min(limit, 50),
                "page": page,
                "resultType": "core",
            },
        )

        results: list[dict[str, Any]] = []
        for item in _europepmc_result_items(data):
            authors = _split_author_string(item.get("authorString") or item.get("authorList"))
            publication_date = _parse_loose_date(
                item.get("pubDate")
                or item.get("firstPublicationDate")
                or item.get("electronicPublicationDate")
                or item.get("printPublicationDate")
                or item.get("pubYear")
            )
            doi = normalize_doi(item.get("doi") or item.get("DOI"))

            pdf_url = None
            ft = _coerce_europepmc_fulltext_links(item.get("fullTextUrlList"))
            for link in ft:
                style = str(link.get("documentStyle", "")).lower()
                candidate_url = _first_text(link.get("url") or link.get("URL"))
                if candidate_url and (style == "pdf" or _is_pdf_like_url(candidate_url)):
                    pdf_url = candidate_url
                    break





            article_id = _first_text(item.get("id") or item.get("pmid") or item.get("pmcid"))
            source_db = _first_text(item.get("source"))
            source_ref = None
            if source_db and article_id:
                source_ref = f"{source_db}:{article_id}"
            europepmc_article_url = None
            if source_db and article_id:
                europepmc_article_url = f"https://europepmc.org/article/{source_db}/{article_id}"
            article_url = europepmc_article_url or (f"https://doi.org/{doi}" if doi else None)

            results.append(
                {
                    "title": _first_text(item.get("title"), default="Untitled") or "Untitled",
                    "authors": authors,
                    "published_date": publication_date,
                    "journal": _first_text(item.get("journalTitle")),
                    "doi": doi,
                    "abstract": _strip_jats(item.get("abstractText")),
                    "keywords": [],
                    "source": "EuropePMC",
                    "source_id": source_ref or (str(article_id) if article_id else None),
                    "url": article_url,
                    "pdf_url": pdf_url,
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        return None


class ELibraryClient(_RetryingClient):
    BASE_URL = "https://www.elibrary.ru"
    SOURCE_NAME = "eLibrary"
    PARSER_ALPHA_ROOT = Path(__file__).resolve().parents[2]
    SESSION_DIR = PARSER_ALPHA_ROOT / "session" / "elibrary"
    COOKIE_HEADER_FILE = SESSION_DIR / "cookie_header.txt"
    COOKIES_JSON_FILE = SESSION_DIR / "cookies.json"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)
        self._cookie_header = (
            self._load_cookie_header_from_session_files()
            or self._load_cookie_header_from_local_har()
        )

    def _request_headers(self, *, referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        if self._cookie_header:
            headers["Cookie"] = self._cookie_header
        return headers

    @staticmethod
    def _cookie_header_from_cookie_payload(payload: Any) -> str | None:
        """Build a Cookie header from common browser export shapes.

        Supported forms:
        - {"name": "value", ...}
        - [{"name": "...", "value": "...", "domain": "..."}, ...]
        - {"cookies": [{"name": "...", "value": "..."}, ...]}
        """
        if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
            payload = payload.get("cookies")

        parts: list[str] = []
        if isinstance(payload, dict):
            for key_raw, value_raw in payload.items():
                key = _collapse_whitespace(str(key_raw))
                value = _collapse_whitespace(str(value_raw))
                if key and value:
                    parts.append(f"{key}={value}")

        elif isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                domain = _collapse_whitespace(str(item.get("domain") or "")) or ""
                if domain and "elibrary.ru" not in domain.lower():
                    continue
                key = _collapse_whitespace(str(item.get("name") or ""))
                value = _collapse_whitespace(str(item.get("value") or ""))
                if key and value:
                    parts.append(f"{key}={value}")

        if not parts:
            return None
        return "; ".join(dict.fromkeys(parts))

    @staticmethod
    def _load_cookie_header_from_session_files() -> str | None:
        header_path = ELibraryClient.COOKIE_HEADER_FILE
        if header_path.exists():
            try:
                value = _collapse_whitespace(header_path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                value = None
            if value:
                return value

        cookies_json_path = ELibraryClient.COOKIES_JSON_FILE
        if cookies_json_path.exists():
            try:
                payload = json.loads(cookies_json_path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                payload = None
            value = ELibraryClient._cookie_header_from_cookie_payload(payload)
            if value:
                return value
        return None

    @staticmethod
    def _load_cookie_header_from_local_har() -> str | None:
        """
        Try to load eLibrary browser cookies from a local HAR archive dropped
        into the project root (e.g. 'www.elibrary.ru_Archive ... .har').
        """
        har_patterns = [
            ELibraryClient.SESSION_DIR / "latest.har",
        ]
        candidates: list[Path] = [p for p in har_patterns if p.exists()]
        candidates.extend(ELibraryClient.SESSION_DIR.glob("*.har"))
        candidates.extend(ELibraryClient.PARSER_ALPHA_ROOT.glob("www.elibrary.ru_Archive*.har"))
        candidates.extend(ELibraryClient.PARSER_ALPHA_ROOT.parent.glob("www.elibrary.ru_Archive*.har"))
        candidates = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None

        har_path = candidates[0]
        try:
            payload = json.loads(har_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None

        entries = ((payload.get("log") or {}).get("entries") or [])
        cookie_values: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            request = entry.get("request") or {}
            url = str(request.get("url") or "")
            if "elibrary.ru" not in url:
                continue
            for header in request.get("headers") or []:
                if not isinstance(header, dict):
                    continue
                if str(header.get("name") or "").lower() == "cookie":
                    value = _collapse_whitespace(header.get("value"))
                    if value:
                        cookie_values.append(value)

        if not cookie_values:
            return None

        return max(cookie_values, key=lambda v: (len(v), cookie_values.count(v)))

    @staticmethod
    def _is_captcha_page(html: str, final_url: str | None = None) -> bool:
        url_lower = (final_url or "").lower()
        html_lower = html.lower()
        if "page_captcha.asp" in url_lower:
            return True
        return "page_captcha.asp" in html_lower or "провер" in html_lower and "captcha" in html_lower

    @staticmethod
    def _extract_pdf_url_from_result_row(row: Any) -> str | None:
        if row is None:
            return None
        for anchor in row.select("a[href]"):
            href = _collapse_whitespace(anchor.get("href"))
            if not href:
                continue
            text = _collapse_whitespace(anchor.get_text(" ", strip=True)) or ""
            href_low = href.lower()
            text_low = text.lower()
            if ".pdf" in href_low or "download" in href_low or "full_text" in href_low or "pdf" in text_low:
                return urljoin("https://www.elibrary.ru", href)
        return None

    async def _resolve_pdf_url_from_item(self, item_id: str) -> str | None:
        if not item_id:
            return None

        client = await self._get_client()
        headers = self._request_headers(referer=f"{self.BASE_URL}/query_results.asp")
        try:
            item_response = await client.get(
                f"/item.asp?id={quote_plus(item_id)}",
                headers=headers,
                follow_redirects=True,
            )
            item_response.raise_for_status()
        except Exception:
            return None

        soup = BeautifulSoup(item_response.text, "html.parser")
        file_match = re.search(
            r"javascript:file_article\((\d+)\s*,\s*(\d+)\)",
            item_response.text,
            flags=re.IGNORECASE,
        )
        if not file_match:
            return None

        file_id, file_num = file_match.group(1), file_match.group(2)
        form = soup.find("form", attrs={"name": "results"})
        post_data: dict[str, str] = {}
        if form is not None:
            for field in form.find_all("input"):
                name = field.get("name")
                if not name:
                    continue
                field_type = (field.get("type") or "").lower()
                if field_type in {"checkbox", "radio"} and not field.has_attr("checked"):
                    continue
                post_data[name] = field.get("value", "")
        post_data["fileid"] = file_id
        post_data["filenum"] = file_num

        headers = self._request_headers(referer=str(item_response.url))
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            file_response = await client.post(
                "/file_article.asp",
                data=post_data,
                headers=headers,
                follow_redirects=False,
            )
        except Exception:
            return None

        location = file_response.headers.get("Location") or file_response.headers.get("location")
        if location:
            return urljoin(f"{self.BASE_URL}/", location)

        content_type = (file_response.headers.get("Content-Type") or "").lower()
        if "application/pdf" in content_type:
            return str(file_response.url)

        html = file_response.text or ""
        href_match = re.search(r'href="([^"]+\.pdf[^"]*)"', html, flags=re.IGNORECASE)
        if href_match:
            return urljoin(f"{self.BASE_URL}/", href_match.group(1))

        return None

    async def _submit_quick_search_form(self, query: str) -> tuple[str, str]:
        client = await self._get_client()
        request_headers = self._request_headers(referer=f"{self.BASE_URL}/querybox.asp")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        payload = {
            "where_fulltext": "on",
            "where_name": "on",
            "where_abstract": "on",
            "where_keywords": "on",
            "where_affiliation": "",
            "where_references": "",
            "type_article": "on",
            "type_disser": "on",
            "type_book": "on",
            "type_report": "on",
            "type_conf": "on",
            "type_patent": "on",
            "type_preprint": "on",
            "type_grant": "on",
            "type_dataset": "on",
            "search_freetext": "",
            "search_morph": "on",
            "search_fulltext": "",
            "search_open": "",
            "search_results": "",
            "titles_all": "",
            "authors_all": "",
            "rubrics_all": "",
            "queryboxid": "",
            "itemboxid": "",
            "begin_year": "",
            "end_year": "",
            "issues": "all",
            "orderby": "rank",
            "order": "rev",
            "changed": "1",
            "ftext": query,
        }


        try:
            await client.get("/querybox.asp", headers=request_headers, follow_redirects=True)
            response = await client.post(
                "/query_results.asp",
                data=payload,
                headers=request_headers,
                follow_redirects=True,
            )
        except httpx.TooManyRedirects as exc:
            raise SourceUnavailableError(
                source=self.SOURCE_NAME,
                message=(
                    "eLibrary session redirects looped (start_session/defaultx). "
                    "Likely bot-protection gate in current network."
                ),
            ) from exc
        response.raise_for_status()
        return response.text, str(response.url)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        if len((query or "").strip()) < 2:
            return []

        html, final_url = await self._submit_quick_search_form(query)
        if self._is_captcha_page(html, final_url):
            raise SourceUnavailableError(
                source=self.SOURCE_NAME,
                message=(
                    "eLibrary returned CAPTCHA page. Automated extraction is blocked; "
                    "need authenticated browser session/cookies or manual CAPTCHA solve."
                ),
            )

        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='item.asp?id=']")
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for link in links:
            href = link.get("href") or ""
            match = re.search(r"id=(\d+)", href)
            source_id = match.group(1) if match else href
            if source_id in seen:
                continue
            seen.add(source_id)

            title = _collapse_whitespace(link.get_text(" ", strip=True)) or "Untitled"
            title = _repair_mojibake_ru(title) or title
            row_text = _collapse_whitespace(link.find_parent("tr").get_text(" ", strip=True) if link.find_parent("tr") else "")
            row_text = _repair_mojibake_ru(row_text) or row_text
            year_match = re.search(r"\b(19|20)\d{2}\b", row_text or "")
            publication_date = f"{year_match.group(0)}-01-01T00:00:00" if year_match else None
            row = link.find_parent("tr")
            pdf_url = self._extract_pdf_url_from_result_row(row)
            if not pdf_url and source_id.isdigit():
                pdf_url = await self._resolve_pdf_url_from_item(source_id)

            results.append(
                {
                    "title": title,
                    "authors": [],
                    "published_date": publication_date,
                    "journal": "eLibrary",
                    "doi": None,
                    "abstract": None,
                    "keywords": [],
                    "source": "eLibrary",
                    "source_id": source_id,
                    "url": urljoin(self.BASE_URL, href),
                    "pdf_url": pdf_url,
                }
            )

            if len(results) >= limit:
                break

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        raw = _collapse_whitespace(item_id)
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"{self.BASE_URL}/item.asp?id={quote_plus(raw)}"


class FreePatentClient(_RetryingClient):
    BASE_URL = "https://yandex.ru"
    SOURCE_NAME = "FreePatent"
    _PATENT_PATH_RE = re.compile(r"^/(?:patents?|patent)/(?P<pid>\d+)(?:/|$)", re.IGNORECASE)

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    @classmethod
    def _extract_patent_id(cls, url: str) -> str | None:
        parsed = urlparse(url)
        if "freepatent.ru" not in parsed.netloc.lower():
            return None
        match = cls._PATENT_PATH_RE.match(parsed.path or "")
        if not match:
            return None
        return match.group("pid")

    @staticmethod
    def _is_mpk_url(url: str) -> bool:
        parsed = urlparse(url)
        if "freepatent.ru" not in parsed.netloc.lower():
            return False
        return (parsed.path or "").lower().startswith("/mpk/")

    @staticmethod
    def _build_patent_url(patent_id: str) -> str:
        return f"https://www.freepatent.ru/patents/{patent_id}"

    @staticmethod
    def _unwrap_yandex_result_url(url: str | None) -> str | None:
        """Return the real target URL from a Yandex result link when possible.

        Yandex SERP links are often relative ``/clck/jsredir?...&url=<encoded>``
        redirects. The previous parser skipped those rows because the href host was
        ``yandex.ru`` (or empty for relative links), so FreePatent could return zero
        results even though the encoded target was a valid freepatent.ru patent page.
        """
        raw = _collapse_whitespace(url)
        if not raw:
            return None

        absolute = urljoin("https://yandex.ru", raw)
        parsed = urlparse(absolute)
        if "yandex." not in parsed.netloc.lower():
            return absolute

        query = parse_qs(parsed.query)
        for key in ("url", "u", "target"):
            values = query.get(key)
            if not values:
                continue
            candidate = _collapse_whitespace(unquote(values[0]))
            if candidate and urlparse(candidate).scheme in {"http", "https"}:
                return candidate

        return absolute

    def _extract_patents_from_mpk_html(self, html: str, limit: int) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = _collapse_whitespace(anchor.get("href"))
            if not href:
                continue
            absolute = urljoin("https://www.freepatent.ru/", href)
            patent_id = self._extract_patent_id(absolute)
            if not patent_id or patent_id in seen_ids:
                continue
            seen_ids.add(patent_id)

            title_raw = _collapse_whitespace(anchor.get_text(" ", strip=True))
            title = _repair_mojibake_ru(title_raw) or f"Патент {patent_id}"
            records.append(
                {
                    "title": title,
                    "authors": [],
                    "published_date": None,
                    "journal": "FreePatent",
                    "doi": None,
                    "abstract": None,
                    "keywords": [],
                    "source": "FreePatent",
                    "source_id": f"patents/{patent_id}",
                    "url": self._build_patent_url(patent_id),
                    "pdf_url": None,
                }
            )
            if len(records) >= limit:
                break

        return records

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(0, offset // max(1, limit))
        html = await self._request_text(
            "/search/site/",
            params={
                "searchid": "2002563",
                "web": "0",
                "text": query,
                "p": str(page),
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        seen_mpk_urls: set[str] = set()

        for item in soup.select("li.b-serp-item"):
            link = item.select_one("a.b-serp-item__title-link")
            if link is None:
                continue

            url = self._unwrap_yandex_result_url(link.get("href"))
            if not url:
                continue
            parsed = urlparse(url)
            if "freepatent.ru" not in parsed.netloc.lower():
                continue

            patent_id = self._extract_patent_id(url)
            if patent_id:
                source_id = f"patents/{patent_id}"
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)

                title = _repair_mojibake_ru(_collapse_whitespace(link.get_text(" ", strip=True))) or "Untitled"
                abstract = _repair_mojibake_ru(
                    _collapse_whitespace((item.select_one("div.b-serp-item__text") or item).get_text(" ", strip=True))
                )
                results.append(
                    {
                        "title": title,
                        "authors": [],
                        "published_date": None,
                        "journal": "FreePatent",
                        "doi": None,
                        "abstract": abstract,
                        "keywords": [],
                        "source": "FreePatent",
                        "source_id": source_id,
                        "url": self._build_patent_url(patent_id),
                        "pdf_url": None,
                    }
                )
                if len(results) >= limit:
                    break
                continue

            if self._is_mpk_url(url):
                normalized_mpk_url = url.split("#", 1)[0]
                if normalized_mpk_url in seen_mpk_urls:
                    continue
                seen_mpk_urls.add(normalized_mpk_url)

                try:
                    category_html = await self._request_text(normalized_mpk_url)
                    expanded = self._extract_patents_from_mpk_html(category_html, limit=limit - len(results))
                except Exception:
                    expanded = []

                for record in expanded:
                    sid = record.get("source_id")
                    if not isinstance(sid, str) or sid in seen_source_ids:
                        continue
                    seen_source_ids.add(sid)
                    results.append(record)
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        raw = _collapse_whitespace(item_id)
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"https://www.freepatent.ru/{raw.lstrip('/')}"


class PatentScopeClient(_RetryingClient):
    BASE_URL = "https://patentscope.wipo.int"
    SOURCE_NAME = "PATENTSCOPE"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def _resolve_documents_pdf_url(self, doc_id: str) -> str | None:
        if not doc_id:
            return None

        try:
            html = await self._request_text(
                "/search/en/detail.jsf",
                params={"docId": doc_id, "tab": "DOCUMENTS"},
            )
        except Exception:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.select("a[href]"):
            href = _collapse_whitespace(anchor.get("href"))
            if not href:
                continue
            href_lower = href.lower()
            if ".pdf" in href_lower or "download" in href_lower:
                return urljoin(f"{self.BASE_URL}/search/en/", href)

        return None

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        query_expr = query if ":" in query else f"FP:({query})"
        client = await self._get_client()
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }
        response = await client.get(
            "/search/en/result.jsf",
            params={"query": query_expr},
            headers=request_headers,
            follow_redirects=True,
        )
        response.raise_for_status()
        html = response.text
        final_url = str(response.url)
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("tr.trans-result-list-row")
        results: list[dict[str, Any]] = []
        seen: set[str] = set()



        direct_match = re.search(r"[?&]docId=([^&]+)", final_url)
        if direct_match and not rows:
            doc_id = unquote(direct_match.group(1))
            title = _collapse_whitespace((soup.title.get_text(" ", strip=True) if soup.title else None)) or doc_id
            if "wipo - search" in title.lower():
                title = doc_id
            pdf_url = await self._resolve_documents_pdf_url(doc_id)
            return [
                {
                    "title": title,
                    "authors": [],
                    "published_date": None,
                    "journal": "PATENTSCOPE",
                    "doi": None,
                    "abstract": None,
                    "keywords": [],
                    "source": "PATENTSCOPE",
                    "source_id": doc_id,
                    "url": f"{self.BASE_URL}/search/en/detail.jsf?docId={quote_plus(doc_id)}",
                    "pdf_url": pdf_url,
                }
            ]

        for row in rows:
            link = row.select_one("a[href*='detail.jsf']")
            if link is None:
                continue

            href = link.get("href") or ""
            source_id_match = re.search(r"docId=([^&]+)", href)
            source_id = unquote(source_id_match.group(1)) if source_id_match else href
            if source_id in seen:
                continue
            seen.add(source_id)

            number = _collapse_whitespace(
                (row.select_one(".ps-patent-result--title--patent-number") or link).get_text(" ", strip=True)
            )
            title = _collapse_whitespace(
                (row.select_one(".ps-patent-result--title--title") or row).get_text(" ", strip=True)
            ) or "Untitled"

            label_map: dict[str, str] = {}
            for field in row.select(".ps-field"):
                label = _collapse_whitespace(
                    (field.select_one(".ps-field--label") or field).get_text(" ", strip=True)
                )
                value = _collapse_whitespace(
                    (field.select_one(".ps-field--value") or field).get_text(" ", strip=True)
                )
                if label and value:
                    label_map[label.lower()] = value

            publication_date = _parse_dot_date(
                label_map.get("publication date") or label_map.get("дата публикации")
            )
            abstract = _collapse_whitespace(label_map.get("abstract") or label_map.get("аннотация"))
            app_no = label_map.get("application number") or label_map.get("номер заявки")
            source_ref = _collapse_whitespace(source_id or app_no or number)
            detail_url = f"{self.BASE_URL}/search/en/detail.jsf?docId={quote_plus(source_ref)}" if source_ref else None
            pdf_url = await self._resolve_documents_pdf_url(source_ref) if source_ref else None

            results.append(
                {
                    "title": title,
                    "authors": [],
                    "published_date": publication_date,
                    "journal": "PATENTSCOPE",
                    "doi": None,
                    "abstract": abstract,
                    "keywords": [],
                    "source": "PATENTSCOPE",
                    "source_id": source_ref,
                    "url": detail_url or urljoin("https://patentscope.wipo.int/search/en/", href),
                    "pdf_url": pdf_url,
                }
            )

            if len(results) >= limit:
                break

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        if not item_id:
            return None
        raw = _collapse_whitespace(item_id)
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"https://patentscope.wipo.int/search/en/detail.jsf?docId={quote_plus(unquote(raw))}"




def _extract_rospatent_file_names(value: Any) -> list[str]:
    """Extract file names/URLs from Rospatent media-list payload variants."""
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = _collapse_whitespace(str(value))
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_extract_rospatent_file_names(item))
        return list(dict.fromkeys(output))
    if isinstance(value, dict):
        output: list[str] = []
        for key in ("file", "filename", "fileName", "name", "path", "url", "href"):
            if key in value:
                output.extend(_extract_rospatent_file_names(value.get(key)))
        for key in ("files", "items", "results", "result", "data", "documents", "media"):
            if key in value:
                output.extend(_extract_rospatent_file_names(value.get(key)))
        return list(dict.fromkeys(output))
    return []


def _normalize_rospatent_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    """Unwrap one Rospatent/Elasticsearch hit into the actual document body."""
    if not isinstance(hit, dict):
        return None

    source_body = hit.get("_source")
    if isinstance(source_body, dict):
        normalized = dict(source_body)
        if not normalized.get("id") and hit.get("_id") is not None:
            normalized["id"] = hit.get("_id")

        for key in ("highlight", "fields", "dataset", "index"):
            if key not in normalized and key in hit:
                normalized[key] = hit.get(key)
        return normalized

    return hit


def _extract_rospatent_hits(value: Any) -> list[dict[str, Any]]:
    """Extract Rospatent search hits from list and Elasticsearch-like payloads."""
    if isinstance(value, list):
        output: list[dict[str, Any]] = []
        for item in value:
            normalized = _normalize_rospatent_hit(item) if isinstance(item, dict) else None
            if normalized:
                output.append(normalized)
        return output
    if isinstance(value, dict):
        for key in ("hits", "results", "items", "data"):
            nested = value.get(key)
            extracted = _extract_rospatent_hits(nested)
            if extracted:
                return extracted
        normalized = _normalize_rospatent_hit(value)
        if not normalized:
            return []
        return [normalized] if normalized.get("id") or normalized.get("common") or normalized.get("snippet") else []
    return []


class RosPatentClient(_RetryingClient):
    BASE_URL = "https://searchplatform.rospatent.gov.ru"
    SOURCE_NAME = "Rospatent"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    @staticmethod
    def _is_non_patent_dataset(dataset: str | None) -> bool:
        normalized = (dataset or "").strip().lower()
        return normalized in {"copyrights_db", "related_rights_db", "programs", "topologies"}

    @staticmethod
    def _build_doc_url(source_id: str | None) -> str | None:
        if not source_id:
            return None
        return f"https://searchplatform.rospatent.gov.ru/doc/{quote_plus(source_id)}"

    @staticmethod
    def _hit_matches_query(hit: dict[str, Any], query: str) -> bool:
        q = _collapse_whitespace(query)
        if not q:
            return True

        common = _as_dict(hit.get("common"))
        snippet = _as_dict(hit.get("snippet"))
        biblio_ru = _as_dict(_as_dict(hit.get("biblio")).get("ru"))
        blob = " ".join(
            [
                str(hit.get("id") or ""),
                str(common.get("document_number") or ""),
                str(snippet.get("title") or ""),
                str(snippet.get("description") or ""),
                str(biblio_ru.get("title") or ""),
            ]
        ).lower()
        q_low = q.lower()
        if q_low in blob:
            return True

        tokens = [tok for tok in re.split(r"\W+", q_low) if len(tok) >= 2]
        if not tokens:
            return False
        return all(tok in blob for tok in tokens)

    async def _request_media_file_list(self, media_path: str) -> list[str]:
        client = await self._get_client()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
        }
        response = await client.get(media_path, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return _extract_rospatent_file_names(payload)

    async def _resolve_pdf_url_from_doc(self, doc_payload: dict[str, Any]) -> str | None:
        media_path_raw = _extract_rospatent_media_path(doc_payload.get("ex_media_list"))
        if not media_path_raw:
            for key in ("media_path", "mediaPath", "media", "files", "documents"):
                media_path_raw = _extract_rospatent_media_path(doc_payload.get(key))
                if media_path_raw:
                    break
        if not media_path_raw:
            return None

        media_path = media_path_raw if media_path_raw.startswith("/") else f"/{media_path_raw}"
        if urlparse(media_path_raw).scheme in {"http", "https"}:
            media_path = media_path_raw
        try:
            files = await self._request_media_file_list(media_path)
        except Exception:
            return None

        pdf_files = [name for name in files if str(name).lower().endswith(".pdf")]
        if not pdf_files:
            return None

        preferred = next((name for name in pdf_files if str(name).lower() == "main.pdf"), None)
        if preferred is None:
            preferred = next((name for name in pdf_files if "main" in str(name).lower()), None)
        chosen = preferred or pdf_files[0]
        chosen_text = str(chosen)
        if urlparse(chosen_text).scheme in {"http", "https"}:
            return chosen_text




        chosen_part = chosen_text.lstrip("/")
        if urlparse(media_path).scheme in {"http", "https"}:
            return urljoin(f"{media_path.rstrip('/')}/", chosen_part)
        media_path_part = str(media_path).strip("/")
        return urljoin(f"{self.BASE_URL}/", f"{media_path_part}/{chosen_part}")

    async def _fetch_doc_payload(self, source_id: str) -> dict[str, Any] | None:
        if not source_id:
            return None
        try:
            payload = await self._request_json(f"/docs/{source_id}", {})
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _extract_names(values: Any) -> list[str]:
        if not values:
            return []
        if isinstance(values, dict):
            for key in ("name", "fullName", "displayName", "value", "text"):
                name = _first_text(values.get(key))
                if name:
                    return [name]
            output: list[str] = []
            for item in values.values():
                output.extend(RosPatentClient._extract_names(item))
            return list(dict.fromkeys(output))
        if isinstance(values, list):
            output: list[str] = []
            for item in values:
                if isinstance(item, dict):
                    output.extend(RosPatentClient._extract_names(item))
                else:
                    text = _collapse_whitespace(str(item))
                    if text:
                        output.append(text)
            return list(dict.fromkeys(output))
        return [_collapse_whitespace(str(values))] if _collapse_whitespace(str(values)) else []

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(1, (offset // max(1, limit)) + 1)
        per_page = min(max(limit, 1), 100)

        primary_payload = {"qn": query, "page": page, "size": per_page}
        data = await self._request_json_post("/search", primary_payload)
        hits = _extract_rospatent_hits(data.get("hits") if isinstance(data, dict) else data)

        if not hits:
            secondary_payload = {"query": query, "page": page, "size": per_page}
            data = await self._request_json_post("/search", secondary_payload)
            hits = _extract_rospatent_hits(data.get("hits") if isinstance(data, dict) else data)

        results: list[dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            if not self._hit_matches_query(hit, query):
                continue

            common = _as_dict(hit.get("common"))
            biblio_ru = _as_dict(_as_dict(hit.get("biblio")).get("ru"))
            snippet = _as_dict(hit.get("snippet"))
            source_meta = _as_dict(_as_dict(hit.get("meta")).get("source"))
            dataset = _first_text(hit.get("dataset"))
            if self._is_non_patent_dataset(dataset):
                continue

            title = _first_text(snippet.get("title") or biblio_ru.get("title")) or "Untitled"
            abstract = _first_text(snippet.get("description"))
            publication_date = _parse_dot_date(_first_text(common.get("publication_date")))
            document_number = _first_text(common.get("document_number"))
            source_id = _first_text(hit.get("id") or source_meta.get("path") or document_number)
            inventors = self._extract_names(biblio_ru.get("inventor"))
            patentee_names = self._extract_names(biblio_ru.get("patentee"))
            authors = inventors if inventors else patentee_names

            doc_payload = await self._fetch_doc_payload(source_id) if source_id else None
            if doc_payload:
                doc_abstract = _first_text(
                    _as_dict(doc_payload.get("abstract")).get("ru")
                    or _as_dict(doc_payload.get("abstract")).get("en")
                )
                if doc_abstract:
                    abstract = doc_abstract
                doc_biblio_ru = _as_dict(_as_dict(doc_payload.get("biblio")).get("ru"))
                doc_inventors = self._extract_names(doc_biblio_ru.get("inventor"))
                doc_patentee_names = self._extract_names(doc_biblio_ru.get("patentee"))
                doc_authors = doc_inventors if doc_inventors else doc_patentee_names
                if doc_authors:
                    authors = doc_authors

            doc_url = self._build_doc_url(source_id)
            pdf_url = await self._resolve_pdf_url_from_doc(doc_payload) if doc_payload else None
            if not pdf_url:
                pdf_url = await self._resolve_pdf_url_from_doc(hit)

            results.append(
                {
                    "title": title,
                    "authors": authors,
                    "published_date": publication_date,
                    "journal": "Rospatent",
                    "doi": None,
                    "abstract": abstract,
                    "keywords": [
                        item
                        for item in [
                            dataset,
                            _first_text(hit.get("index")),
                            _first_text(common.get("kind")),
                        ]
                        if item
                    ],
                    "source": "Rospatent",
                    "source_id": source_id,
                    "url": doc_url or f"https://searchplatform.rospatent.gov.ru/patents?q={quote_plus(query)}",
                    "pdf_url": pdf_url,
                }
            )

            if len(results) >= limit:
                break

        return results
    async def get_full_text(self, item_id: str) -> str | None:
        raw = _collapse_whitespace(item_id)
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return self._build_doc_url(raw)


AVAILABLE_EXTERNAL_SOURCES = {
    "OpenAlex": OpenAlexClient,
    "Crossref": CrossrefClient,
    "EuropePMC": EuropePMCClient,
    "eLibrary": ELibraryClient,
    "Rospatent": RosPatentClient,
    "FreePatent": FreePatentClient,
    "PATENTSCOPE": PatentScopeClient,
}
