"""Унифицированный HTTP-слой для scraper-источников."""

from __future__ import annotations

import asyncio
import importlib.util
import random

import httpx

BROWSER_HEADERS: list[dict[str, str]] = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    },
]


class BaseScraperClient:
    """Базовый HTTP-клиент для сайтов без официального API."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
    ):
        self.timeout = timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._session: httpx.AsyncClient | None = None

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            http2_enabled = importlib.util.find_spec("h2") is not None
            self._session = httpx.AsyncClient(
                headers=random.choice(BROWSER_HEADERS),
                timeout=self.timeout,
                follow_redirects=True,
                http2=http2_enabled,
            )
        return self._session

    async def _polite_get(self, url: str, **kwargs) -> httpx.Response:
        await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))
        session = await self._get_session()
        return await session.get(url, **kwargs)

    async def _polite_post(self, url: str, **kwargs) -> httpx.Response:
        await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))
        session = await self._get_session()
        return await session.post(url, **kwargs)

    async def close(self):
        if self._session and not self._session.is_closed:
            await self._session.aclose()
            self._session = None
