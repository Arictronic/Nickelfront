"""External source clients (OpenAlex, Crossref, Europe PMC)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from parsers_pkg.base import BaseAPIClient, RetryConfig, decide_for_exception, decide_for_status
from parsers_pkg.errors import ParsingError, SourceUnavailableError


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).replace("Z", "")


def _strip_jats(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"<[^>]+>", " ", text).strip()


def _date_parts_to_iso(parts: list[int] | None) -> str | None:
    if not parts:
        return None
    year = parts[0] if len(parts) >= 1 else 1
    month = parts[1] if len(parts) >= 2 else 1
    day = parts[2] if len(parts) >= 3 else 1
    try:
        return datetime(year, month, day).isoformat()
    except Exception:
        return None


def _collapse_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def _parse_dot_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = _collapse_whitespace(value)
    if not raw:
        return None
    for fmt in ("%Y.%m.%d", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except Exception:
            continue
    return None


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

    # Heuristic: typical mojibake markers in Russian text.
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

        results: list[dict[str, Any]] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in item.get("authorships", [])
                if isinstance(a, dict)
            ]
            authors = [a for a in authors if a]

            concepts = [
                c.get("display_name", "")
                for c in item.get("concepts", [])[:8]
                if isinstance(c, dict)
            ]
            concepts = [c for c in concepts if c]

            doi = (item.get("doi") or "").replace("https://doi.org/", "") or None
            primary_raw = item.get("primary_location")
            primary = primary_raw if isinstance(primary_raw, dict) else {}
            pdf_url = primary.get("pdf_url")
            landing = primary.get("landing_page_url")
            work_id = (item.get("id") or "").split("/")[-1]
            source_raw = primary.get("source")
            source_info = source_raw if isinstance(source_raw, dict) else {}
            fallback_work_url = f"https://openalex.org/{work_id}" if work_id else None
            article_url = landing or (f"https://doi.org/{doi}" if doi else None) or fallback_work_url
            
            # Extract abstract from inverted index if available
            abstract = None
            abstract_inverted = item.get("abstract_inverted_index")
            if abstract_inverted and isinstance(abstract_inverted, dict):
                abstract = self._reconstruct_abstract(abstract_inverted)

            results.append(
                {
                    "title": item.get("display_name") or "Untitled",
                    "authors": authors,
                    "published_date": _parse_iso_date(item.get("publication_date")),
                    "journal": source_info.get("display_name"),
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
    
    def _reconstruct_abstract(self, inverted_index: dict[str, list[int]]) -> str | None:
        """Reconstruct abstract text from OpenAlex inverted index format."""
        try:
            # Create a list to hold words at their positions
            max_pos = max(max(positions) for positions in inverted_index.values() if positions)
            words = [""] * (max_pos + 1)
            
            # Place each word at its positions
            for word, positions in inverted_index.items():
                for pos in positions:
                    if 0 <= pos <= max_pos:
                        words[pos] = word
            
            # Join words and clean up
            abstract = " ".join(w for w in words if w).strip()
            return abstract if abstract else None
        except Exception:
            return None

    async def get_full_text(self, item_id: str) -> str | None:
        data = await self._request_json(f"/works/{item_id}", {})
        primary = data.get("primary_location") or {}
        return primary.get("pdf_url") or primary.get("landing_page_url")


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

        items = (data.get("message") or {}).get("items", [])
        results: list[dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            authors = []
            for author in item.get("author", []) or []:
                if isinstance(author, dict):
                    given = (author.get("given") or "").strip()
                    family = (author.get("family") or "").strip()
                    full = " ".join([p for p in [given, family] if p]).strip()
                    if full:
                        authors.append(full)

            date_parts = ((item.get("issued") or {}).get("date-parts") or [[]])[0]
            publication_date = _date_parts_to_iso(date_parts)

            results.append(
                {
                    "title": (item.get("title") or ["Untitled"])[0],
                    "authors": authors,
                    "published_date": publication_date,
                    "journal": ((item.get("container-title") or [None])[0]),
                    "doi": item.get("DOI"),
                    "abstract": _strip_jats(item.get("abstract")),
                    "keywords": item.get("subject") or [],
                    "source": "Crossref",
                    "source_id": item.get("DOI") or str(item.get("indexed", {}).get("date-time", "")),
                    "url": item.get("URL"),
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        return f"https://doi.org/{item_id}" if item_id else None


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
        for item in (data.get("resultList") or {}).get("result", []):
            if not isinstance(item, dict):
                continue
            authors = [a.strip() for a in (item.get("authorString") or "").split(",") if a.strip()]
            year = item.get("pubYear")
            publication_date = f"{year}-01-01T00:00:00" if year else None
            doi = item.get("doi")

            pdf_url = None
            ft = ((item.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
            for link in ft:
                if isinstance(link, dict) and str(link.get("documentStyle", "")).lower() == "pdf":
                    pdf_url = link.get("url")
                    break

            article_id = item.get("id") or doi or item.get("source")
            source_db = item.get("source")
            source_ref = None
            if source_db and article_id:
                source_ref = f"{source_db}:{article_id}"
            europepmc_article_url = None
            if source_db and article_id:
                europepmc_article_url = f"https://europepmc.org/article/{source_db}/{article_id}"
            article_url = europepmc_article_url or (f"https://doi.org/{doi}" if doi else None)

            results.append(
                {
                    "title": item.get("title") or "Untitled",
                    "authors": authors,
                    "published_date": publication_date,
                    "journal": item.get("journalTitle"),
                    "doi": doi,
                    "abstract": item.get("abstractText"),
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
    SESSION_DIR = Path("session/elibrary")
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
            if isinstance(payload, dict):
                parts = []
                for k, v in payload.items():
                    key = _collapse_whitespace(str(k))
                    val = _collapse_whitespace(str(v))
                    if key and val:
                        parts.append(f"{key}={val}")
                if parts:
                    return "; ".join(parts)
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
        candidates.extend(Path(".").glob("www.elibrary.ru_Archive*.har"))
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
        # HAR usually repeats the same browser cookie per request.
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

        # Warm up session and cookies from querybox before submit.
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
        if not item_id:
            return None
        return f"{self.BASE_URL}/item.asp?id={item_id}"


class FreePatentClient(_RetryingClient):
    BASE_URL = "https://yandex.ru"
    SOURCE_NAME = "FreePatent"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

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

        for item in soup.select("li.b-serp-item"):
            link = item.select_one("a.b-serp-item__title-link")
            if link is None:
                continue

            url = _collapse_whitespace(link.get("href"))
            if not url:
                continue
            parsed = urlparse(url)
            if "freepatent.ru" not in parsed.netloc:
                continue

            title = _collapse_whitespace(link.get_text(" ", strip=True)) or "Untitled"
            abstract = _collapse_whitespace(
                (item.select_one("div.b-serp-item__text") or item).get_text(" ", strip=True)
            )
            source_id = parsed.path.strip("/") or parsed.netloc

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
                    "url": url,
                    "pdf_url": None,
                }
            )

            if len(results) >= limit:
                break

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        if not item_id:
            return None
        return f"https://www.freepatent.ru/{item_id.lstrip('/')}"


class PatentScopeClient(_RetryingClient):
    BASE_URL = "https://patentscope.wipo.int"
    SOURCE_NAME = "PATENTSCOPE"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def _resolve_documents_pdf_url(self, doc_id: str) -> str | None:
        if not doc_id:
            return None

        documents_tab_url = f"{self.BASE_URL}/search/en/detail.jsf?docId={quote_plus(doc_id)}&tab=DOCUMENTS"
        try:
            html = await self._request_text(
                "/search/en/detail.jsf",
                params={"docId": doc_id, "tab": "DOCUMENTS"},
            )
        except Exception:
            return documents_tab_url

        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.select("a[href]"):
            href = _collapse_whitespace(anchor.get("href"))
            if not href:
                continue
            href_lower = href.lower()
            if ".pdf" in href_lower or "download" in href_lower:
                return urljoin(f"{self.BASE_URL}/search/en/", href)

        return documents_tab_url

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

        # Exact identifiers may redirect directly to a detail card instead of
        # rendering a result table.
        direct_match = re.search(r"[?&]docId=([^&]+)", final_url)
        if direct_match and not rows:
            doc_id = direct_match.group(1)
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
            source_id = source_id_match.group(1) if source_id_match else href
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
            source_ref = source_id or app_no or number
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
        return f"https://patentscope.wipo.int/search/en/detail.jsf?docId={quote_plus(item_id)}"


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

        common = hit.get("common") or {}
        snippet = hit.get("snippet") or {}
        biblio_ru = ((hit.get("biblio") or {}).get("ru") or {})
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
        if isinstance(payload, list):
            return [str(x) for x in payload if isinstance(x, (str, int, float))]
        return []

    async def _resolve_pdf_url_from_doc(self, doc_payload: dict[str, Any]) -> str | None:
        media_path_raw = _collapse_whitespace(doc_payload.get("ex_media_list"))
        if not media_path_raw:
            return None

        media_path = media_path_raw if media_path_raw.startswith("/") else f"/{media_path_raw}"
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
        return urljoin(f"{self.BASE_URL}/", f"{media_path.lstrip('/')}{chosen}")

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
        if isinstance(values, list):
            output: list[str] = []
            for item in values:
                if isinstance(item, dict):
                    name = _collapse_whitespace(item.get("name"))
                    if name:
                        output.append(name)
                else:
                    text = _collapse_whitespace(str(item))
                    if text:
                        output.append(text)
            return output
        return [_collapse_whitespace(str(values))] if _collapse_whitespace(str(values)) else []

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(1, (offset // max(1, limit)) + 1)
        per_page = min(max(limit, 1), 100)

        primary_payload = {"qn": query, "page": page, "size": per_page}
        data = await self._request_json_post("/search", primary_payload)
        hits = data.get("hits", [])
        if not isinstance(hits, list):
            return []

        if not hits:
            secondary_payload = {"query": query, "page": page, "size": per_page}
            data = await self._request_json_post("/search", secondary_payload)
            hits = data.get("hits", [])
        if not isinstance(hits, list):
            return []

        results: list[dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            if not self._hit_matches_query(hit, query):
                continue

            common = hit.get("common") or {}
            biblio_ru = ((hit.get("biblio") or {}).get("ru") or {})
            snippet = hit.get("snippet") or {}
            source_meta = (hit.get("meta") or {}).get("source") or {}
            dataset = _collapse_whitespace(hit.get("dataset"))
            if self._is_non_patent_dataset(dataset):
                continue

            title = _collapse_whitespace(snippet.get("title") or biblio_ru.get("title")) or "Untitled"
            abstract = _collapse_whitespace(snippet.get("description"))
            publication_date = _parse_dot_date(common.get("publication_date"))
            document_number = _collapse_whitespace(common.get("document_number"))
            source_id = _collapse_whitespace(hit.get("id") or source_meta.get("path") or document_number)
            inventors = self._extract_names(biblio_ru.get("inventor"))
            patentee_names = self._extract_names(biblio_ru.get("patentee"))
            authors = inventors if inventors else patentee_names

            doc_payload = await self._fetch_doc_payload(source_id) if source_id else None
            if doc_payload:
                abstract = _collapse_whitespace(
                    abstract
                    or ((doc_payload.get("abstract") or {}).get("ru"))
                    or ((doc_payload.get("abstract") or {}).get("en"))
                )
                doc_biblio_ru = ((doc_payload.get("biblio") or {}).get("ru") or {})
                inventors = self._extract_names(doc_biblio_ru.get("inventor"))
                patentee_names = self._extract_names(doc_biblio_ru.get("patentee"))
                authors = inventors if inventors else patentee_names

            doc_url = self._build_doc_url(source_id)
            pdf_url = await self._resolve_pdf_url_from_doc(doc_payload) if doc_payload else None

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
                            _collapse_whitespace(hit.get("index")),
                            _collapse_whitespace(common.get("kind")),
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
        if not item_id:
            return None
        return self._build_doc_url(item_id)


AVAILABLE_EXTERNAL_SOURCES = {
    "OpenAlex": OpenAlexClient,
    "Crossref": CrossrefClient,
    "EuropePMC": EuropePMCClient,
    "eLibrary": ELibraryClient,
    "Rospatent": RosPatentClient,
    "FreePatent": FreePatentClient,
    "PATENTSCOPE": PatentScopeClient,
}
