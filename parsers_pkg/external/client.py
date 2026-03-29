"""External source clients (OpenAlex, Crossref, Semantic Scholar, Europe PMC)."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient


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


class _RetryingClient(BaseAPIClient):
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.5

    async def _request_json(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        client = await self._get_client()

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(path, params=params)

                if response.status_code in (408, 429) or 500 <= response.status_code < 600:
                    if attempt >= self.MAX_RETRIES:
                        response.raise_for_status()
                    sleep_for = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "{} transient status {} (attempt {}/{}), retry in {:.1f}s",
                        self.__class__.__name__,
                        response.status_code,
                        attempt,
                        self.MAX_RETRIES,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.MAX_RETRIES:
                    logger.error("{} network error: {}", self.__class__.__name__, exc)
                    return None
                await asyncio.sleep(self.RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            except Exception as exc:
                logger.error("{} request error: {}", self.__class__.__name__, exc)
                return None

        return None


class OpenAlexClient(_RetryingClient):
    BASE_URL = "https://api.openalex.org"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        page = max(1, (offset // max(1, limit)) + 1)
        data = await self._request_json(
            "/works",
            {
                "search": query,
                "per-page": min(limit, 50),
                "page": page,
            },
        )
        if not data:
            return []

        results: list[dict[str, Any]] = []
        for item in data.get("results", []):
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
            primary = item.get("primary_location") or {}
            pdf_url = primary.get("pdf_url")
            landing = primary.get("landing_page_url")
            work_id = (item.get("id") or "").split("/")[-1]

            results.append(
                {
                    "title": item.get("display_name") or "Untitled",
                    "authors": authors,
                    "published_date": _parse_iso_date(item.get("publication_date")),
                    "journal": (item.get("primary_location") or {}).get("source", {}).get("display_name"),
                    "doi": doi,
                    "abstract": None,
                    "keywords": concepts,
                    "source": "OpenAlex",
                    "source_id": work_id,
                    "url": pdf_url or landing,
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        data = await self._request_json(f"/works/{item_id}", {})
        if not data:
            return None
        primary = data.get("primary_location") or {}
        return primary.get("pdf_url") or primary.get("landing_page_url")


class CrossrefClient(_RetryingClient):
    BASE_URL = "https://api.crossref.org"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        data = await self._request_json(
            "/works",
            {
                "query": query,
                "rows": min(limit, 50),
                "offset": max(offset, 0),
            },
        )
        if not data:
            return []

        items = (data.get("message") or {}).get("items", [])
        results: list[dict[str, Any]] = []

        for item in items:
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


class SemanticScholarClient(_RetryingClient):
    BASE_URL = "https://api.semanticscholar.org"

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)
        self.api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

    async def _get_client(self) -> httpx.AsyncClient:
        client = await super()._get_client()
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        client.headers.update(headers)
        return client

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        data = await self._request_json(
            "/graph/v1/paper/search",
            {
                "query": query,
                "limit": min(limit, 50),
                "offset": max(offset, 0),
                "fields": "paperId,title,abstract,authors,year,venue,url,externalIds,openAccessPdf,fieldsOfStudy",
            },
        )
        if not data:
            return []

        results: list[dict[str, Any]] = []
        for item in data.get("data", []):
            doi = (item.get("externalIds") or {}).get("DOI")
            year = item.get("year")
            publication_date = f"{year}-01-01T00:00:00" if year else None
            pdf_url = (item.get("openAccessPdf") or {}).get("url")

            results.append(
                {
                    "title": item.get("title") or "Untitled",
                    "authors": [a.get("name", "") for a in item.get("authors", []) if isinstance(a, dict)],
                    "published_date": publication_date,
                    "journal": item.get("venue"),
                    "doi": doi,
                    "abstract": item.get("abstract"),
                    "keywords": item.get("fieldsOfStudy") or [],
                    "source": "SemanticScholar",
                    "source_id": item.get("paperId"),
                    "url": pdf_url or item.get("url"),
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        if not item_id:
            return None
        data = await self._request_json(
            f"/graph/v1/paper/{item_id}",
            {"fields": "openAccessPdf,url"},
        )
        if not data:
            return None
        return (data.get("openAccessPdf") or {}).get("url") or data.get("url")


class EuropePMCClient(_RetryingClient):
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

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
        if not data:
            return []

        results: list[dict[str, Any]] = []
        for item in (data.get("resultList") or {}).get("result", []):
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
            article_url = item.get("doi")
            if doi:
                article_url = f"https://doi.org/{doi}"

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
                    "url": pdf_url or article_url,
                }
            )

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        return None


AVAILABLE_EXTERNAL_SOURCES = {
    "OpenAlex": OpenAlexClient,
    "Crossref": CrossrefClient,
    "SemanticScholar": SemanticScholarClient,
    "EuropePMC": EuropePMCClient,
}
