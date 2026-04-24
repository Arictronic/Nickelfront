"""CyberLeninka client for Russian scientific articles."""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any

from loguru import logger

from parsers_pkg.base import BaseAPIClient, RetryConfig, decide_for_exception, decide_for_status
from parsers_pkg.errors import SourceUnavailableError


class CyberLeninkaClient(BaseAPIClient):
    """Client for CyberLeninka (https://cyberleninka.ru)."""

    BASE_URL = "https://cyberleninka.ru"
    API_SEARCH_PATH = "/api/search"
    SOURCE_NAME = "CyberLeninka"
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0

    def __init__(self, timeout: float = 30.0):
        super().__init__(base_url=self.BASE_URL, timeout=timeout)
        self._retry_config = RetryConfig(
            max_retries=self.MAX_RETRIES,
            base_delay=self.RETRY_BASE_DELAY,
            backoff_base=2.0,
            jitter_max=0.5,
        )

    async def search(self, query: str, limit: int = 25, offset: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
        """Search articles via CyberLeninka internal JSON API."""
        page_index = offset // max(1, limit)
        from_offset = page_index * limit

        payload = {
            "mode": "articles",
            "q": query,
            "size": max(1, min(limit, 100)),
            "from": max(0, from_offset),
        }

        try:
            data = await self._post_json(self.API_SEARCH_PATH, payload)
            results = self._parse_api_results(data, limit)
            logger.info("{}: found {} articles for query '{}'", self.SOURCE_NAME, len(results), query)
            return results
        except Exception as exc:
            logger.error("{}: search failed for query '{}': {}", self.SOURCE_NAME, query, exc)
            raise SourceUnavailableError(source=self.SOURCE_NAME, message=str(exc)) from exc

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON with retry policy."""
        client = await self._get_client()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/search",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.post(path, json=payload, headers=headers)

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

                return response.json()

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
                raise SourceUnavailableError(source=self.SOURCE_NAME, message=f"Request failed: {exc}") from exc

        raise SourceUnavailableError(source=self.SOURCE_NAME, message="Max retries exceeded")

    @staticmethod
    def _clean_markup(text: str | None) -> str | None:
        if not text:
            return None
        no_tags = re.sub(r"<[^>]+>", "", text)
        return html.unescape(" ".join(no_tags.split()))

    def _parse_api_results(self, data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        """Parse /api/search JSON response into normalized records."""
        articles = data.get("articles") or []
        results: list[dict[str, Any]] = []

        for article in articles[:limit]:
            try:
                article_path = str(article.get("link") or "").strip()
                if not article_path:
                    continue

                article_url = f"{self.BASE_URL}{article_path}" if article_path.startswith("/") else article_path
                source_id = article_path.strip("/")

                title = self._clean_markup(article.get("name")) or "Без названия"
                authors = [str(a).strip() for a in (article.get("authors") or []) if str(a).strip()]
                abstract = self._clean_markup(article.get("annotation"))
                journal = self._clean_markup(article.get("journal"))

                year = article.get("year")
                published_date = None
                if isinstance(year, int) and 1900 <= year <= 2100:
                    published_date = f"{year}-01-01T00:00:00"

                pdf_url = None
                if article_path.startswith("/article/"):
                    pdf_url = f"{self.BASE_URL}{article_path}/pdf"

                doi = None
                ocr_parts = article.get("ocr") or []
                if ocr_parts:
                    ocr_text = " ".join(str(part) for part in ocr_parts if part)
                    doi_match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", ocr_text)
                    if doi_match:
                        doi = doi_match.group(1)

                results.append(
                    {
                        "title": title,
                        "authors": authors,
                        "published_date": published_date,
                        "journal": journal,
                        "doi": doi,
                        "abstract": abstract,
                        "keywords": [],
                        "source": self.SOURCE_NAME,
                        "source_id": source_id,
                        "url": article_url,
                        "pdf_url": pdf_url,
                    }
                )
            except Exception as exc:
                logger.warning("{}: failed to parse article: {}", self.SOURCE_NAME, exc)
                continue

        return results

    async def get_full_text(self, item_id: str) -> str | None:
        if not item_id:
            return None
        if item_id.startswith("http://") or item_id.startswith("https://"):
            return item_id
        return f"{self.BASE_URL}/{item_id.lstrip('/')}"
