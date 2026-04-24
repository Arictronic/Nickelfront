"""arXiv API client."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient, RetryConfig, decide_for_exception, decide_for_status
from parsers_pkg.errors import (
    ParsingError,
    SourceUnavailableError,
)

ARXIV_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys",
    "nickel alloys high temperature",
    "Ni-based superalloys",
    "inconel",
    "hastelloy",
]

ARXIV_CATEGORIES = [
    "cond-mat.mtrl-sci",
    "physics.chem-ph",
    "physics.app-ph",
]


class ArxivClient(BaseAPIClient):
    """Client for arXiv API."""

    BASE_URL = "https://export.arxiv.org/api/query"
    RATE_LIMIT_DELAY = 3.0
    MAX_RETRIES = 4
    RETRY_BACKOFF_BASE = 2.0

    def __init__(self, timeout: float = 30.0, rate_limit: bool = True):
        super().__init__(base_url="", api_key=None, timeout=timeout)
        self.rate_limit = rate_limit
        self._last_request_time: datetime | None = None
        self._retry_config = RetryConfig(
            max_retries=self.MAX_RETRIES,
            base_delay=self.RATE_LIMIT_DELAY / 2.0,
            backoff_base=self.RETRY_BACKOFF_BASE,
            jitter_max=0.8,
        )

    async def _apply_rate_limit(self) -> None:
        if not self.rate_limit:
            return

        if self._last_request_time:
            elapsed = (datetime.now() - self._last_request_time).total_seconds()
            if elapsed < self.RATE_LIMIT_DELAY:
                await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)

        self._last_request_time = datetime.now()

    async def search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        await self._apply_rate_limit()
        client = await self._get_client()

        search_query = f"all:{query}"
        if categories:
            category_filter = " OR ".join(f"cat:{cat}" for cat in categories)
            search_query = f"({search_query}) AND ({category_filter})"

        params = {
            "search_query": search_query,
            "start": offset,
            "max_results": min(limit, 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        logger.info("arXiv: query='{}', limit={}", query, limit)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(self.BASE_URL, params=params)
                if response.status_code >= 400:
                    decision = decide_for_status(
                        source="arXiv",
                        status_code=response.status_code,
                        attempt=attempt,
                        config=self._retry_config,
                        retry_after_header=response.headers.get("Retry-After"),
                    )
                    if decision.retry:
                        logger.warning(
                            "arXiv transient status {} for query='{}' (attempt {}/{}), retry in {:.1f}s",
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

                results = self._parse_xml_response(response.text)
                logger.info("arXiv: found {} records", len(results))
                return results

            except Exception as exc:
                decision = decide_for_exception(
                    source="arXiv",
                    exc=exc,
                    attempt=attempt,
                    config=self._retry_config,
                )
                if decision.retry:
                    logger.warning(
                        "arXiv transient error for query='{}' (attempt {}/{}): {}. Retry in {:.1f}s",
                        query,
                        attempt,
                        self.MAX_RETRIES,
                        str(exc),
                        decision.delay_seconds,
                    )
                    await asyncio.sleep(decision.delay_seconds)
                    continue
                if decision.error is not None:
                    raise decision.error from exc
                raise SourceUnavailableError(source="arXiv", message=f"Search failure: {exc}") from exc

        raise SourceUnavailableError(source="arXiv", message="Search failed without a response")

    def _parse_xml_response(self, xml_text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        try:
            namespaces = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }

            root = ET.fromstring(xml_text)
            entries = root.findall("atom:entry", namespaces)

            for entry in entries:
                article = self._parse_entry(entry, namespaces)
                if article:
                    results.append(article)

        except ET.ParseError as exc:
            raise ParsingError(source="arXiv", message=f"XML parse error: {exc}") from exc

        return results

    def _parse_entry(self, entry: ET.Element, namespaces: dict[str, str]) -> dict[str, Any] | None:
        try:
            id_elem = entry.find("atom:id", namespaces)
            arxiv_id = id_elem.text.strip() if id_elem is not None and id_elem.text else None
            pdf_url = None
            if arxiv_id:
                clean_id = arxiv_id.replace("http://arxiv.org/abs/", "").replace("https://arxiv.org/abs/", "")
                pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"

            title_elem = entry.find("atom:title", namespaces)
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled"
            title = " ".join(title.split())

            authors = []
            for author_elem in entry.findall("atom:author", namespaces):
                name_elem = author_elem.find("atom:name", namespaces)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            published_elem = entry.find("atom:published", namespaces)
            published_date = None
            if published_elem is not None and published_elem.text:
                try:
                    pub_date_str = published_elem.text.strip().replace("Z", "")
                    if "+" in pub_date_str:
                        pub_date_str = pub_date_str.split("+")[0]
                    if "T" not in pub_date_str:
                        pub_date_str += "T00:00:00"
                    published_date = pub_date_str
                except Exception:
                    pass

            categories = []
            for cat_elem in entry.findall("atom:category", namespaces):
                term = cat_elem.get("term")
                if term:
                    categories.append(term)

            summary_elem = entry.find("atom:summary", namespaces)
            abstract = None
            if summary_elem is not None and summary_elem.text:
                abstract = " ".join(summary_elem.text.strip().split())

            return {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "published_date": published_date,
                "categories": categories,
                "abstract": abstract,
                "url": arxiv_id,
                "pdf_url": pdf_url,
                "source": "arXiv",
            }
        except Exception as exc:
            logger.warning("Error parsing arXiv entry: {}", exc)
            return None

    async def get_full_text(self, item_id: str) -> str | None:
        clean_id = item_id
        if clean_id.startswith("arXiv:"):
            clean_id = clean_id[6:]
        clean_id = clean_id.split("/")[-1].split("v")[0]
        return f"https://arxiv.org/pdf/{clean_id}.pdf"

    async def close(self):
        await super().close()
        self._last_request_time = None
