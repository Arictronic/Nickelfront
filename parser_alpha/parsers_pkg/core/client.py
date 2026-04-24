"""CORE API client."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient, RetryConfig, decide_for_exception, decide_for_status
from parsers_pkg.errors import (
    ParsingError,
    SourceUnavailableError,
)


class COREClient(BaseAPIClient):
    """Client for CORE API v3."""

    BASE_URL = "https://api.core.ac.uk/v3"
    MAX_RETRIES = 4
    RETRY_BACKOFF_BASE = 2.0
    RETRY_BASE_SLEEP = 1.5
    USER_AGENT = "Nickelfront/1.0 (CORE parser)"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        resolved_api_key = api_key or os.getenv("CORE_API_KEY")
        if not resolved_api_key:
            logger.warning("CORE_API_KEY is not set. CORE API may return 429 rate-limit responses.")
        super().__init__(base_url=self.BASE_URL, api_key=resolved_api_key, timeout=timeout)
        self._retry_config = RetryConfig(
            max_retries=self.MAX_RETRIES,
            base_delay=self.RETRY_BASE_SLEEP,
            backoff_base=self.RETRY_BACKOFF_BASE,
            jitter_max=0.7,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        client = await super()._get_client()
        client.headers.update({"User-Agent": self.USER_AGENT, "Accept": "application/json"})
        return client

    async def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        full_text_only: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        client = await self._get_client()

        params = {"q": query, "limit": min(limit, 100), "offset": offset}
        params.update(kwargs)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get("/search/works/", params=params)
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source="CORE",
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        logger.warning(
                            "CORE transient status {} for query='{}' (attempt {}/{}), retry in {:.1f}s",
                            response.status_code,
                            query,
                            attempt,
                            self.MAX_RETRIES,
                            decision.delay_seconds,
                        )
                        await asyncio.sleep(decision.delay_seconds)
                        continue
                    if decision.error is not None:
                        raise decision.error
                    response.raise_for_status()

                data = response.json()
                if not isinstance(data, dict):
                    raise ParsingError(source="CORE", message=f"Unexpected payload type: {type(data).__name__}")

                results = data.get("results", [])
                if not isinstance(results, list):
                    raise ParsingError(source="CORE", message="Payload field 'results' is not a list")

                if full_text_only:
                    results = [
                        item
                        for item in results
                        if isinstance(item, dict)
                        and (item.get("downloadUrl") or item.get("fullText") or item.get("sourceFulltextUrls"))
                    ]

                logger.info("CORE: found {} papers for query '{}'", len(results), query)
                return results

            except ParsingError:
                raise

            except Exception as exc:
                decision = decide_for_exception(
                    source="CORE",
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    logger.warning(
                        "CORE transient error for query='{}' (attempt {}/{}): {}. Retry in {:.1f}s",
                        query,
                        attempt,
                        self.MAX_RETRIES,
                        exc,
                        decision.delay_seconds,
                    )
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source="CORE", message=f"Search failure: {exc}") from exc

        raise SourceUnavailableError(source="CORE", message="Search failed without a response")

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        client = await self._get_client()

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(f"/works/{article_id}")
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source="CORE",
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        logger.warning(
                            "CORE get_article transient status {} for id={} (attempt {}/{}), retry in {:.1f}s",
                            response.status_code,
                            article_id,
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
                    raise ParsingError(source="CORE", message=f"Unexpected article payload: {type(payload).__name__}")
                return payload

            except ParsingError:
                raise

            except Exception as exc:
                decision = decide_for_exception(
                    source="CORE",
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source="CORE", message=f"Article request failure: {exc}") from exc

        return None

    async def get_full_text(self, item_id: str) -> str | None:
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

    async def suggest(self, query: str, limit: int = 10) -> list[str]:
        client = await self._get_client()

        try:
            response = await client.get("/search/works/", params={"q": query, "limit": min(limit, 20)})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return []
            suggestions = []
            for item in data.get("results", []):
                title = item.get("title") if isinstance(item, dict) else None
                if title and title not in suggestions:
                    suggestions.append(title)
            return suggestions[:limit]
        except Exception as exc:
            logger.error("CORE suggest error: {}", exc)
            return []
