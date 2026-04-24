"""Async Playwright client for JS-rendered sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)

try:
    from playwright_stealth import stealth_async
except Exception:  # pragma: no cover - optional dependency
    stealth_async = None


class BasePlaywrightClient:
    """Reusable async Playwright client for dynamic pages."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30000,
        user_agent: str | None = None,
        locale: str = "en-US",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self.locale = locale
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> None:
        async with self._lock:
            if self._browser and self._context:
                return

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            self._context = await self._browser.new_context(
                user_agent=self.user_agent,
                locale=self.locale,
                viewport={"width": 1440, "height": 1080},
                ignore_https_errors=True,
            )
            self._context.set_default_timeout(self.timeout_ms)

    async def new_page(self) -> Page:
        await self._ensure_browser()
        assert self._context is not None
        page = await self._context.new_page()

        if stealth_async is not None:
            try:
                await stealth_async(page)
            except Exception as exc:  # pragma: no cover - optional addon failures
                logger.debug("playwright-stealth setup failed: %s", exc)

        return page

    async def fetch_html(
        self,
        url: str,
        *,
        wait_selector: str | None = None,
        wait_until: str = "domcontentloaded",
        extra_wait_ms: int = 0,
    ) -> str:
        page = await self.new_page()
        try:
            await page.goto(url, wait_until=wait_until)
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=self.timeout_ms)
            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)
            return await page.content()
        finally:
            await page.close()

    async def evaluate_json(
        self,
        url: str,
        expression: str,
        *,
        wait_selector: str | None = None,
        wait_until: str = "domcontentloaded",
        extra_wait_ms: int = 0,
    ) -> Any:
        page = await self.new_page()
        try:
            await page.goto(url, wait_until=wait_until)
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=self.timeout_ms)
            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)
            return await page.evaluate(expression)
        finally:
            await page.close()

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
