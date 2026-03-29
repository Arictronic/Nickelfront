"""CORE API client."""

import asyncio
import os
import random
from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient


class COREClient(BaseAPIClient):
    """Client for CORE API v3."""

    BASE_URL = "https://api.core.ac.uk/v3"
    MAX_RETRIES = 4
    RETRY_BACKOFF_BASE = 2.0
    RETRY_BASE_SLEEP = 1.5
    USER_AGENT = "Nickelfront/1.0 (CORE parser)"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        resolved_api_key = api_key or os.getenv("CORE_API_KEY")
        if not resolved_api_key:
            logger.warning("CORE_API_KEY is not set. CORE API may return 429 rate-limit responses.")
        super().__init__(
            base_url=self.BASE_URL,
            api_key=resolved_api_key,
            timeout=timeout,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        client = await super()._get_client()
        client.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            }
        )
        return client

    async def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        full_text_only: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search papers in CORE."""
        client = await self._get_client()

        params = {
            "q": query,
            "limit": min(limit, 100),
            "offset": offset,
        }
        params.update(kwargs)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get("/search/works/", params=params)

                if response.status_code in (408, 429) or 500 <= response.status_code < 600:
                    if attempt >= self.MAX_RETRIES:
                        response.raise_for_status()

                    sleep_for = self.RETRY_BASE_SLEEP * (self.RETRY_BACKOFF_BASE ** (attempt - 1)) + random.uniform(0, 0.7)
                    logger.warning(
                        "CORE transient status {} for query='{}' (attempt {}/{}), retry in {:.1f}s",
                        response.status_code,
                        query,
                        attempt,
                        self.MAX_RETRIES,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])

                if full_text_only:
                    results = [
                        item
                        for item in results
                        if item.get("downloadUrl") or item.get("fullText") or item.get("sourceFulltextUrls")
                    ]

                logger.info("CORE: found {} papers for query '{}'", len(results), query)
                return results

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt >= self.MAX_RETRIES:
                    logger.error("CORE API network error after {} attempts: {}", attempt, e)
                    return []

                sleep_for = self.RETRY_BASE_SLEEP * (self.RETRY_BACKOFF_BASE ** (attempt - 1))
                logger.warning(
                    "CORE API transient network error for query='{}' (attempt {}/{}): {}. Retry in {:.1f}s",
                    query,
                    attempt,
                    self.MAX_RETRIES,
                    e,
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)

            except httpx.HTTPStatusError as e:
                logger.error("CORE API error: {}", e)
                if e.response is not None:
                    logger.error("CORE response: {}", e.response.text[:500])
                return []
            except httpx.HTTPError as e:
                logger.error("CORE API error: {}", e)
                return []
            except Exception as e:
                logger.error("CORE search error: {}", e)
                return []

        return []

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get a paper by CORE id."""
        client = await self._get_client()

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(f"/works/{article_id}")

                if response.status_code in (408, 429) or 500 <= response.status_code < 600:
                    if attempt >= self.MAX_RETRIES:
                        response.raise_for_status()
                    sleep_for = self.RETRY_BASE_SLEEP * (self.RETRY_BACKOFF_BASE ** (attempt - 1)) + random.uniform(0, 0.7)
                    logger.warning(
                        "CORE get_article transient status {} for id={} (attempt {}/{}), retry in {:.1f}s",
                        response.status_code,
                        article_id,
                        attempt,
                        self.MAX_RETRIES,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt >= self.MAX_RETRIES:
                    logger.error("CORE get article network error after {} attempts: {}", attempt, e)
                    return None
                sleep_for = self.RETRY_BASE_SLEEP * (self.RETRY_BACKOFF_BASE ** (attempt - 1))
                await asyncio.sleep(sleep_for)
            except httpx.HTTPError as e:
                logger.error("CORE get article error: {}", e)
                return None
            except Exception as e:
                logger.error("CORE get article error: {}", e)
                return None

        return None

    async def get_full_text(self, item_id: str) -> str | None:
        """Get full-text URL for a paper."""
        article = await self.get_article(item_id)

        if article:
            if article.get("downloadUrl"):
                return article.get("downloadUrl")

            fulltext_urls = article.get("sourceFulltextUrls") or []
            if isinstance(fulltext_urls, list) and fulltext_urls:
                return fulltext_urls[0]

            if article.get("fullText"):
                return article.get("fullText")

        return None

    async def suggest(
        self,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        """Build simple query suggestions from top titles."""
        client = await self._get_client()

        try:
            response = await client.get("/search/works/", params={"q": query, "limit": min(limit, 20)})
            response.raise_for_status()
            data = response.json()
            suggestions = []
            for item in data.get("results", []):
                title = item.get("title")
                if title and title not in suggestions:
                    suggestions.append(title)
            return suggestions[:limit]
        except Exception as e:
            logger.error("CORE suggest error: {}", e)
            return []
